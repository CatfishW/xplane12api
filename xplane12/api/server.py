from __future__ import annotations

import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from xplane12.api.plugin_artifacts import ArtifactUnavailable, PluginArtifactStore
from xplane12.api.rendering import render_dashboard_html, render_traffic_svg, render_weather_svg
from xplane12.bridge import SnapshotAdapter, XPlaneWebApiClient, create_runtime
from xplane12.compat import Subscription
from xplane12.stream import NdjsonBroadcastServer


class ApiHandler(BaseHTTPRequestHandler):
    adapter: ClassVar[SnapshotAdapter | None] = None
    subscriptions: ClassVar[list[Subscription]] = []
    artifacts: ClassVar[PluginArtifactStore | None] = None

    def _write_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._write_bytes(status, payload, content_type="application/json")

    def _write_text(self, status: int, body: str, content_type: str) -> None:
        self._write_bytes(status, body.encode("utf-8"), content_type=content_type)

    def _write_bytes(self, status: int, body: bytes, *, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    def do_GET(self) -> None:
        adapter = ApiHandler.adapter
        if adapter is None:
            self._write_json(503, {"error": "state_unavailable"})
            return

        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._write_json(200, adapter.health_payload())
            return

        if path == "/data":
            category = qs.get("category", [None])[0]
            bridge = adapter.state_snapshot()
            self._write_json(
                200,
                {
                    "values": adapter.category_values(category),
                    "last_packet_ts": bridge.last_packet_ts,
                    "last_sender": bridge.last_sender,
                    "rx_packets": bridge.rx_packets,
                    "rx_pairs": bridge.rx_pairs,
                    "last_error": bridge.last_error,
                },
            )
            return

        if path == "/datarefs":
            self._write_json(
                200,
                {
                    "subscriptions": [
                        {
                            "index": subscription.index,
                            "category": subscription.category,
                            "dataref": subscription.dataref,
                        }
                        for subscription in ApiHandler.subscriptions
                    ]
                },
            )
            return

        snapshot = adapter.canonical_snapshot()
        payload = snapshot.to_dict()
        if path in ("/", "/ui/radar", "/ui/displays"):
            self._write_text(200, render_dashboard_html(), "text/html; charset=utf-8")
            return
        if path == "/v1/snapshot":
            self._write_json(200, payload)
            return
        if path == "/v1/ownship":
            self._write_json(200, payload["ownship"])
            return
        if path == "/v1/weather":
            self._write_json(200, payload["weather"])
            return
        if path == "/v1/render/weather.png":
            artifacts = ApiHandler.artifacts
            if artifacts is None:
                self._write_json(503, {"error": "artifact_store_unavailable"})
                return
            try:
                self._write_bytes(200, artifacts.render_png("weather"), content_type="image/png")
            except ArtifactUnavailable as error:
                self._write_json(503, {"error": str(error)})
            return
        if path == "/v1/render/weather.svg":
            self._write_text(200, render_weather_svg(snapshot), "image/svg+xml; charset=utf-8")
            return
        if path == "/v1/traffic":
            self._write_json(200, {"traffic": payload["traffic"]})
            return
        if path == "/v1/render/traffic.png":
            artifacts = ApiHandler.artifacts
            if artifacts is None:
                self._write_json(503, {"error": "artifact_store_unavailable"})
                return
            try:
                self._write_bytes(200, artifacts.render_png("traffic"), content_type="image/png")
            except ArtifactUnavailable as error:
                self._write_json(503, {"error": str(error)})
            return
        if path == "/v1/render/traffic.svg":
            max_range_nm = 40.0
            requested_range = qs.get("range_nm", [None])[0]
            if requested_range is not None:
                try:
                    max_range_nm = float(requested_range)
                except ValueError:
                    max_range_nm = 40.0
            max_range_nm = max(5.0, min(max_range_nm, 120.0))
            self._write_text(
                200,
                render_traffic_svg(snapshot, max_range_nm=max_range_nm),
                "image/svg+xml; charset=utf-8",
            )
            return
        if path == "/v1/render/gauges.json":
            artifacts = ApiHandler.artifacts
            if artifacts is None:
                self._write_json(503, {"error": "artifact_store_unavailable"})
                return
            self._write_json(200, artifacts.artifact_manifest())
            return
        if path.startswith("/v1/render/gauges/") and path.endswith(".png"):
            artifacts = ApiHandler.artifacts
            if artifacts is None:
                self._write_json(503, {"error": "artifact_store_unavailable"})
                return
            slug = path.removeprefix("/v1/render/gauges/").removesuffix(".png")
            try:
                self._write_bytes(200, artifacts.render_png(slug), content_type="image/png")
            except ArtifactUnavailable as error:
                self._write_json(503, {"error": str(error)})
            return
        if path == "/v1/render/gauges.png":
            artifacts = ApiHandler.artifacts
            if artifacts is None:
                self._write_json(503, {"error": "artifact_store_unavailable"})
                return
            try:
                self._write_bytes(200, artifacts.render_png("gauges"), content_type="image/png")
            except ArtifactUnavailable as error:
                self._write_json(503, {"error": str(error)})
            return
        if path == "/v1/autopilot":
            self._write_json(200, payload.get("automation") or {})
            return
        if path == "/v1/capabilities":
            self._write_json(200, payload["capabilities"])
            return
        if path == "/v1/raw":
            category = qs.get("category", [None])[0]
            values = adapter.category_values(category) if category else payload["raw"]
            self._write_json(200, {"values": values})
            return

        self._write_json(404, {"error": "not_found", "path": path})

    def log_message(self, format: str, *args: object) -> None:
        return


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SnapshotBroadcaster:
    def __init__(self, adapter: SnapshotAdapter, server: NdjsonBroadcastServer, interval_seconds: float = 1.0) -> None:
        self._adapter = adapter
        self._server = server
        self._interval_seconds = interval_seconds
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="XPlaneSnapshotBroadcaster", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            self._server.broadcast(self._adapter.canonical_snapshot().to_unity_dict())
            time.sleep(self._interval_seconds)


def run_server(
    *,
    bind_host: str = "127.0.0.1",
    bind_port: int = 12678,
    stream_host: str = "127.0.0.1",
    stream_port: int = 37212,
    xp_base_url: str = "http://127.0.0.1:8086/api/v3",
) -> None:
    _state, subscriptions, client, adapter = create_runtime(base_url=xp_base_url)
    client.start()

    ApiHandler.adapter = adapter
    ApiHandler.subscriptions = subscriptions
    ApiHandler.artifacts = PluginArtifactStore()

    server = ApiServer((bind_host, bind_port), ApiHandler)
    stream_server = NdjsonBroadcastServer(stream_host, stream_port)
    broadcaster = SnapshotBroadcaster(adapter, stream_server)
    broadcaster.start()
    stop_event = threading.Event()
    shutdown_thread: threading.Thread | None = None

    def shutdown_components() -> None:
        broadcaster.stop()
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            stream_server.close()
        except Exception:
            pass
        client.stop()

    def stop(_sig: int, _frame: object) -> None:
        nonlocal shutdown_thread
        if stop_event.is_set():
            return
        stop_event.set()
        shutdown_thread = threading.Thread(target=shutdown_components, name="XPlaneApiShutdown", daemon=True)
        shutdown_thread.start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        if shutdown_thread is not None and shutdown_thread.is_alive():
            shutdown_thread.join(timeout=5.0)
        broadcaster.stop()
        stream_server.close()
        client.stop()
        server.server_close()
