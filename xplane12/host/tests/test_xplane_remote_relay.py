import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xplane12.host import xplane_remote_relay as MODULE


class XPlaneRemoteRelayTests(unittest.TestCase):
    def test_mock_snapshot_contains_required_sections(self):
        source = MODULE.MockFlightSource(8500.0, 160.0, 90.0, 4)
        snapshot = source.next_snapshot()

        self.assertEqual("mock", snapshot.source_mode)
        self.assertIsNotNone(snapshot.ownship)
        self.assertIsNotNone(snapshot.weather)
        self.assertEqual(4, len(snapshot.traffic))
        self.assertIn("sim/flightmodel/position/latitude", snapshot.raw)
        self.assertTrue(snapshot.ownship.autopilot_engaged)

    def test_broadcast_server_streams_ndjson(self):
        server = MODULE.BroadcastServer("127.0.0.1", 37219)
        client = socket.create_connection(("127.0.0.1", 37219), timeout=2)
        try:
            source = MODULE.MockFlightSource(8500.0, 160.0, 90.0, 2)
            time.sleep(0.1)
            server.broadcast(source.next_snapshot())
            data = client.recv(8192).decode("utf-8")
            payload = json.loads(data.strip())
            self.assertIn("ownship", payload)
            self.assertIn("weather", payload)
            self.assertIn("traffic", payload)
        finally:
            client.close()
            server.close()

    def test_parse_rref_payload_reads_multiple_values(self):
        packet = bytearray(b"RREF\x00")
        packet.extend(MODULE.struct.pack("<if", 1000, 33.6407))
        packet.extend(MODULE.struct.pack("<if", 1001, -84.4277))

        updates = MODULE.parse_rref_payload(
            bytes(packet),
            {
                1000: "sim/flightmodel/position/latitude",
                1001: "sim/flightmodel/position/longitude",
            },
        )

        self.assertAlmostEqual(
            33.6407, updates["sim/flightmodel/position/latitude"], places=4
        )
        self.assertAlmostEqual(
            -84.4277, updates["sim/flightmodel/position/longitude"], places=4
        )

    def test_rref_snapshot_contains_required_sections(self):
        source = object.__new__(MODULE.RrefFlightSource)
        source._target_altitude_m = 8500.0 * 0.3048
        source._target_heading_deg = 90.0
        source._target_speed_kt = 160.0
        source._traffic_slots = 2

        values = {
            "sim/flightmodel/position/latitude": 33.6407,
            "sim/flightmodel/position/longitude": -84.4277,
            "sim/flightmodel/position/elevation": 2590.8,
            "sim/flightmodel/position/y_agl": 500.0,
            "sim/flightmodel/position/theta": 1.5,
            "sim/flightmodel/position/phi": 2.5,
            "sim/flightmodel/position/psi": 90.0,
            "sim/flightmodel/position/indicated_airspeed": 160.0,
            "sim/flightmodel/position/true_airspeed": 166.0,
            "sim/flightmodel/position/groundspeed": 80.0,
            "sim/flightmodel/position/vh_ind": 2.0,
            "sim/cockpit2/autopilot/autopilot_mode": 2.0,
            "sim/cockpit2/gauges/indicators/gps_status": 1.0,
            "sim/cockpit2/radios/nav1_has_glideslope": 0.0,
            "sim/cockpit/switches/gear_handle_status": 0.0,
            "sim/joystick/yoke_pitch_ratio": 0.1,
            "sim/joystick/yoke_roll_ratio": -0.2,
            "sim/joystick/yoke_heading_ratio": 0.05,
            "sim/cockpit2/engine/actuators/throttle_ratio_all": 0.7,
            "sim/cockpit2/controls/flap_ratio": 0.0,
            "sim/cockpit2/controls/speedbrake_ratio": 0.0,
            "sim/cockpit2/controls/parking_brake_ratio": 0.0,
            "sim/weather/wind_speed_kt": 18.0,
            "sim/weather/wind_direction_degt": 235.0,
            "sim/weather/barometer_sealevel_inhg": 29.92,
            "sim/weather/temperature_ambient_c": 11.0,
            "sim/weather/visibility_reported_m": 12000.0,
            "sim/weather/cloud_base_msl_m[0]": 3200.0,
            "sim/cockpit2/tcas/targets/modeS_id[0]": 0xABCDEF,
            "sim/cockpit2/tcas/targets/relative_distance_m[0]": 5000.0,
            "sim/cockpit2/tcas/targets/relative_bearing_degt[0]": 30.0,
            "sim/cockpit2/tcas/targets/altitude_ft[0]": 9000.0,
        }

        snapshot = source._build_snapshot(values)

        self.assertEqual("rref", snapshot.source_mode)
        self.assertIsNotNone(snapshot.ownship)
        self.assertIsNotNone(snapshot.weather)
        self.assertIn("sim/flightmodel/position/latitude", snapshot.raw)
        self.assertEqual("observe", snapshot.automation.mode)
        self.assertEqual(1, len(snapshot.traffic))
        self.assertEqual("ABCDEF", snapshot.traffic[0].icao24)

    def test_auto_source_falls_back_to_rref_when_xpc_read_fails(self):
        original_xpc = getattr(MODULE, "XPlaneConnectSource")
        original_rref = getattr(MODULE, "RrefFlightSource")

        class FailingXpcSource:
            def __init__(self, *args, **kwargs):
                self.closed = False

            def next_snapshot(self):
                raise RuntimeError("xpc timeout")

            def close(self):
                self.closed = True

        class FakeRrefSource:
            def __init__(self, *args, **kwargs):
                self.closed = False

            def next_snapshot(self):
                return MODULE.MockFlightSource(8500.0, 160.0, 90.0, 1).next_snapshot()

            def close(self):
                self.closed = True

        setattr(MODULE, "XPlaneConnectSource", FailingXpcSource)
        setattr(MODULE, "RrefFlightSource", FakeRrefSource)
        source = None
        try:
            source = MODULE.AutoFlightSource(
                "127.0.0.1",
                49009,
                49000,
                "0.0.0.0",
                49004,
                10.0,
                1.0,
                8500.0,
                90.0,
                160.0,
                4500.0,
                2,
            )
            snapshot = source.next_snapshot()
            self.assertEqual("mock", snapshot.source_mode)
            self.assertEqual("rref", source._active_mode)
        finally:
            if source is not None:
                source.close()
            setattr(MODULE, "XPlaneConnectSource", original_xpc)
            setattr(MODULE, "RrefFlightSource", original_rref)


if __name__ == "__main__":
    unittest.main()
