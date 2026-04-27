import json
import sys
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xplane12.api import server as MODULE
from xplane12.models import (
    CloudLayer,
    HealthState,
    OwnshipState,
    Snapshot,
    TrafficTarget,
    WeatherState,
)


class FakeAdapter:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            timestamp_utc="2026-04-24T12:34:56+00:00",
            source_mode="test",
            health=HealthState(status="ok", last_update_utc="2026-04-24T12:34:56+00:00"),
            ownship=OwnshipState(
                heading_deg=313.0,
                track_deg=241.0,
                true_airspeed_kt=159.0,
                ground_speed_kt=156.0,
            ),
            weather=WeatherState(
                wind_speed_kt=18.0,
                wind_direction_deg=227.0,
                visibility_m=19700.0,
                precipitation_on_aircraft_ratio=0.38,
                cloud_layers=[
                    CloudLayer(coverage_percent=84.0, precipitation_ratio=0.72, turbulence_ratio=0.28),
                    CloudLayer(coverage_percent=62.0, precipitation_ratio=0.24, turbulence_ratio=0.14),
                    CloudLayer(coverage_percent=40.0, precipitation_ratio=0.1, turbulence_ratio=0.08),
                ],
            ),
            traffic=[
                TrafficTarget(
                    icao24="ABCDEF",
                    callsign="TST123",
                    latitude=33.0,
                    longitude=-84.0,
                    altitude_m=3000.0,
                    heading_deg=30.0,
                    velocity_mps=120.0,
                    vertical_rate_mps=2.0,
                    source="tcas",
                    range_nm=6.2,
                    bearing_deg=330.0,
                    relative_altitude_ft=500.0,
                ),
                TrafficTarget(
                    icao24="plane01",
                    callsign="AC-01",
                    latitude=33.0,
                    longitude=-84.0,
                    altitude_m=2700.0,
                    heading_deg=180.0,
                    velocity_mps=90.0,
                    vertical_rate_mps=-1.5,
                    source="multiplayer",
                    range_nm=18.0,
                    bearing_deg=20.0,
                ),
            ],
        )

    def canonical_snapshot(self) -> Snapshot:
        return self._snapshot

    def state_snapshot(self):
        raise NotImplementedError

    def health_payload(self):
        return {"status": "ok"}

    def category_values(self, _category=None):
        return {}


class FakeArtifacts:
    def render_png(self, key: str) -> bytes:
        return f"PNG:{key}".encode("utf-8")

    def artifact_manifest(self) -> dict[str, object]:
        return {
            "weather": "weather_radar_pilot",
            "traffic": "primus_mfd_2",
            "gauges": [{"slug": "primus_pfd_1", "path": "/v1/render/gauges/primus_pfd_1.png"}],
        }


class ApiServerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        MODULE.ApiHandler.adapter = FakeAdapter()
        MODULE.ApiHandler.subscriptions = []
        MODULE.ApiHandler.artifacts = FakeArtifacts()
        cls.server = MODULE.ApiServer(("127.0.0.1", 0), MODULE.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _get(self, path: str) -> tuple[bytes, str]:
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.read(), response.headers.get("Content-Type", "")

    def test_snapshot_endpoint_returns_json(self):
        payload, content_type = self._get("/v1/snapshot")
        data = json.loads(payload.decode("utf-8"))
        self.assertEqual("application/json", content_type.split(";")[0])
        self.assertEqual("test", data["source_mode"])
        self.assertEqual(2, len(data["traffic"]))

    def test_weather_render_endpoint_returns_svg(self):
        payload, content_type = self._get("/v1/render/weather.svg")
        text = payload.decode("utf-8")
        self.assertEqual("image/svg+xml", content_type.split(";")[0])
        self.assertIn("<svg", text)
        self.assertIn("WX SYNTH", text)
        self.assertIn("WIND 227/18", text)

    def test_traffic_render_endpoint_returns_svg(self):
        payload, content_type = self._get("/v1/render/traffic.svg?range_nm=20")
        text = payload.decode("utf-8")
        self.assertEqual("image/svg+xml", content_type.split(";")[0])
        self.assertIn("<svg", text)
        self.assertIn("HDG 313", text)
        self.assertIn("TGT 2", text)

    def test_weather_render_png_endpoint_returns_image(self):
        payload, content_type = self._get("/v1/render/weather.png")
        self.assertEqual("image/png", content_type.split(";")[0])
        self.assertEqual(b"PNG:weather", payload)

    def test_traffic_render_png_endpoint_returns_image(self):
        payload, content_type = self._get("/v1/render/traffic.png")
        self.assertEqual("image/png", content_type.split(";")[0])
        self.assertEqual(b"PNG:traffic", payload)

    def test_gauges_render_png_endpoint_returns_image(self):
        payload, content_type = self._get("/v1/render/gauges.png")
        self.assertEqual("image/png", content_type.split(";")[0])
        self.assertEqual(b"PNG:gauges", payload)

    def test_gauge_manifest_endpoint_returns_json(self):
        payload, content_type = self._get("/v1/render/gauges.json")
        data = json.loads(payload.decode("utf-8"))
        self.assertEqual("application/json", content_type.split(";")[0])
        self.assertEqual("weather_radar_pilot", data["weather"])

    def test_specific_gauge_render_endpoint_returns_image(self):
        payload, content_type = self._get("/v1/render/gauges/primus_pfd_1.png")
        self.assertEqual("image/png", content_type.split(";")[0])
        self.assertEqual(b"PNG:primus_pfd_1", payload)

    def test_dashboard_route_returns_html(self):
        payload, content_type = self._get("/ui/radar")
        text = payload.decode("utf-8")
        self.assertEqual("text/html", content_type.split(";")[0])
        self.assertIn("X-Plane 12 Original Displays", text)
        self.assertIn("/v1/render/weather.png", text)
        self.assertIn("/v1/render/traffic.png", text)
        self.assertIn("/v1/render/gauges.png", text)


if __name__ == "__main__":
    unittest.main()
