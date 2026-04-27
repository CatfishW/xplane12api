import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xplane12.autopilot import controller as CONTROLLER
from xplane12.host import xplane_remote_relay as RELAY


def make_snapshot(*, roll_deg: float, pitch_deg: float, altitude_agl_m: float, ground_speed_kt: float, true_airspeed_kt: float, indicated_airspeed_kt: float) -> RELAY.TelemetrySnapshot:
    ownship = RELAY.OwnshipState(
        latitude=33.6,
        longitude=-84.4,
        altitude_m=500.0,
        altitude_agl_m=altitude_agl_m,
        pitch_deg=pitch_deg,
        roll_deg=roll_deg,
        heading_deg=90.0,
        track_deg=90.0,
        flight_path_angle_deg=0.0,
        slip_skid=0.0,
        indicated_airspeed_kt=indicated_airspeed_kt,
        true_airspeed_kt=true_airspeed_kt,
        ground_speed_kt=ground_speed_kt,
        vertical_speed_fpm=0.0,
        autopilot_engaged=True,
        autopilot_mode=0,
        gear_down=False,
        on_ground=False,
        gps_valid=True,
        ils_valid=False,
        throttle_ratio=0.0,
        elevator_input=0.0,
        aileron_input=0.0,
        rudder_input=0.0,
        flaps_ratio=0.0,
        speedbrake_ratio=0.0,
        parking_brake_ratio=0.0,
    )
    weather = RELAY.WeatherState(
        wind_speed_kt=0.0,
        wind_direction_deg=0.0,
        barometer_inhg=29.92,
        temperature_c=15.0,
        visibility_m=12000.0,
        cloud_base_m=2000.0,
    )
    return RELAY.TelemetrySnapshot(
        timestamp_utc="2026-04-27T06:40:00+00:00",
        source_mode="rref",
        ownship=ownship,
        weather=weather,
    )


class FlightProfileTests(unittest.TestCase):
    def test_s76_uses_safer_rotorcraft_profile(self):
        payload = CONTROLLER.build_air_start_payload(
            aircraft_path="Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf"
        )
        lle_air_start = payload["lle_air_start"]
        self.assertEqual(55.0, lle_air_start["speed_in_meters_per_second"])
        self.assertEqual(2.5, lle_air_start["pitch_in_degrees"])
        self.assertEqual(0.0, lle_air_start["roll_in_degrees"])

    def test_r22_uses_light_helicopter_profile(self):
        payload = CONTROLLER.build_air_start_payload(
            aircraft_path="Aircraft/Laminar Research/Robinson R22 Beta II/Robinson R22 Beta II.acf"
        )
        lle_air_start = payload["lle_air_start"]
        self.assertEqual(32.0, lle_air_start["speed_in_meters_per_second"])
        self.assertEqual(4.0, lle_air_start["pitch_in_degrees"])


class RecoveryControllerTests(unittest.TestCase):
    def test_restarts_after_confirmed_upset(self):
        controller = RELAY.WebApiRecoveryController(
            base_url="http://127.0.0.1:8086/api/v3",
            aircraft_path="Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf",
            confirm_seconds=5.0,
            min_restart_interval_seconds=30.0,
            grace_seconds=10.0,
        )
        controller._last_restart_at = 0.0
        controller._unhealthy_since = 90.0
        snapshot = make_snapshot(
            roll_deg=88.0,
            pitch_deg=6.0,
            altitude_agl_m=0.0,
            ground_speed_kt=0.5,
            true_airspeed_kt=0.2,
            indicated_airspeed_kt=307.0,
        )
        with mock.patch.object(RELAY.time, "monotonic", return_value=100.0), mock.patch.object(
            RELAY, "start_air_session_once"
        ) as restart_mock:
            restarted = controller.observe(snapshot)

        self.assertTrue(restarted)
        restart_mock.assert_called_once_with(
            base_url="http://127.0.0.1:8086/api/v3",
            aircraft_path="Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf",
        )

    def test_healthy_snapshot_clears_pending_restart(self):
        controller = RELAY.WebApiRecoveryController(
            base_url="http://127.0.0.1:8086/api/v3",
            aircraft_path="Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf",
            confirm_seconds=5.0,
            min_restart_interval_seconds=30.0,
            grace_seconds=10.0,
        )
        controller._last_restart_at = 0.0
        controller._unhealthy_since = 90.0
        snapshot = make_snapshot(
            roll_deg=5.0,
            pitch_deg=2.0,
            altitude_agl_m=400.0,
            ground_speed_kt=105.0,
            true_airspeed_kt=108.0,
            indicated_airspeed_kt=110.0,
        )
        with mock.patch.object(RELAY.time, "monotonic", return_value=100.0), mock.patch.object(
            RELAY, "start_air_session_once"
        ) as restart_mock:
            restarted = controller.observe(snapshot)

        self.assertFalse(restarted)
        self.assertIsNone(controller._unhealthy_since)
        restart_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
