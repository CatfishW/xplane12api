from __future__ import annotations

import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from xplane12.bridge import SnapshotAdapter, XPlaneWebApiClient, create_runtime
from xplane12.compat import Subscription
from xplane12.stream import NdjsonBroadcastServer


class ApiHandler(BaseHTTPRequestHandler):
    adapter: ClassVar[SnapshotAdapter | None] = None
    subscriptions: ClassVar[list[Subscription]] = []

    def _write_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        _ = self.wfile.write(payload)

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
        if path == "/v1/snapshot":
            self._write_json(200, payload)
            return
        if path == "/v1/ownship":
            self._write_json(200, payload["ownship"])
            return
        if path == "/v1/weather":
            self._write_json(200, payload["weather"])
            return
        if path == "/v1/traffic":
            self._write_json(200, {"traffic": payload["traffic"]})
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

    server = ApiServer((bind_host, bind_port), ApiHandler)
    stream_server = NdjsonBroadcastServer(stream_host, stream_port)
    broadcaster = SnapshotBroadcaster(adapter, stream_server)
    broadcaster.start()
    stop_event = threading.Event()

    def stop(_sig: int, _frame: object) -> None:
        if stop_event.is_set():
            return
        stop_event.set()
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

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        broadcaster.stop()
        stream_server.close()
        client.stop()
        server.server_close()
