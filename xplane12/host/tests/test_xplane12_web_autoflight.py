import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xplane12.host import xplane12_web_autoflight as MODULE


class XPlane12WebAutoflightTests(unittest.TestCase):
    def test_wait_for_api_ready_returns_when_api_becomes_ready(self):
        with mock.patch.object(MODULE, "api_is_ready", side_effect=[False, False, True]), mock.patch.object(
            MODULE.time, "sleep"
        ) as sleep_mock:
            MODULE.wait_for_api_ready(
                base_url="http://127.0.0.1:8086/api/v3",
                poll_seconds=2.0,
                timeout_seconds=30.0,
                process=None,
            )

        self.assertEqual(2, sleep_mock.call_count)

    def test_wait_for_api_ready_raises_when_process_exits(self):
        process = mock.Mock()
        process.poll.return_value = 17
        with mock.patch.object(MODULE, "api_is_ready", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "exited before API became ready"):
                MODULE.wait_for_api_ready(
                    base_url="http://127.0.0.1:8086/api/v3",
                    poll_seconds=1.0,
                    timeout_seconds=10.0,
                    process=process,
                )

    def test_build_relay_args_copies_runtime_fields(self):
        args = argparse.Namespace(
            mode="rref",
            listen_host="127.0.0.1",
            listen_port=37211,
            broadcast_hz=5.0,
            duration_seconds=0.0,
            target_altitude_ft=8500.0,
            target_heading_deg=90.0,
            target_speed_kt=160.0,
            recovery_altitude_ft=4500.0,
            xplane_host="127.0.0.1",
            xplane_port=49009,
            xplane_udp_port=49000,
            rref_listen_host="0.0.0.0",
            rref_listen_port=49004,
            rref_frequency_hz=10.0,
            rref_sample_timeout_seconds=1.25,
            traffic_slots=5,
        )

        relay_args = MODULE.build_relay_args(args)

        self.assertEqual("rref", relay_args.mode)
        self.assertEqual(37211, relay_args.listen_port)
        self.assertEqual(8500.0, relay_args.target_altitude_ft)
        self.assertEqual(49009, relay_args.xplane_port)
        self.assertEqual(49004, relay_args.rref_listen_port)

    def test_run_launches_xplane_when_command_is_provided(self):
        args = MODULE.build_arg_parser().parse_args(
            [
                "--api-base-url",
                "http://127.0.0.1:8086/api/v3",
                "--aircraft-path",
                "Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf",
                "--xplane-command",
                "/bin/echo start-xplane",
            ]
        )
        fake_process = mock.Mock()
        with mock.patch.object(MODULE, "api_is_ready", return_value=False), mock.patch.object(
            MODULE, "launch_xplane_process", return_value=fake_process
        ) as launch_mock, mock.patch.object(MODULE, "wait_for_api_ready") as wait_mock, mock.patch.object(
            MODULE, "start_air_session_once"
        ) as air_start_mock, mock.patch.object(MODULE.xplane_remote_relay, "run") as relay_run_mock, mock.patch.object(
            MODULE, "stop_process"
        ) as stop_mock:
            MODULE.run(args)

        launch_mock.assert_called_once_with("/bin/echo start-xplane", None)
        wait_mock.assert_called_once_with(
            base_url="http://127.0.0.1:8086/api/v3",
            poll_seconds=args.api_ready_poll_seconds,
            timeout_seconds=args.api_ready_timeout_seconds,
            process=fake_process,
        )
        air_start_mock.assert_called_once_with(
            base_url="http://127.0.0.1:8086/api/v3",
            aircraft_path="Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf",
        )
        relay_run_mock.assert_called_once()
        stop_mock.assert_called_once_with(fake_process)

    def test_run_uses_existing_simulator_when_api_not_ready_and_no_command(self):
        args = MODULE.build_arg_parser().parse_args(["--skip-air-start"])
        with mock.patch.object(MODULE, "api_is_ready", return_value=False), mock.patch.object(
            MODULE, "launch_xplane_process"
        ) as launch_mock, mock.patch.object(MODULE, "wait_for_api_ready") as wait_mock, mock.patch.object(
            MODULE, "start_air_session_once"
        ) as air_start_mock, mock.patch.object(MODULE.xplane_remote_relay, "run") as relay_run_mock, mock.patch.object(
            MODULE, "stop_process"
        ) as stop_mock:
            MODULE.run(args)

        launch_mock.assert_not_called()
        wait_mock.assert_called_once_with(
            base_url=args.api_base_url,
            poll_seconds=args.api_ready_poll_seconds,
            timeout_seconds=args.api_ready_timeout_seconds,
            process=None,
        )
        air_start_mock.assert_not_called()
        relay_run_mock.assert_called_once()
        stop_mock.assert_not_called()

    def test_run_uses_default_aircraft_when_no_aircraft_path_is_provided(self):
        args = MODULE.build_arg_parser().parse_args([])
        with mock.patch.object(MODULE, "api_is_ready", return_value=True), mock.patch.object(
            MODULE, "wait_for_api_ready"
        ) as wait_mock, mock.patch.object(MODULE, "start_air_session_once") as air_start_mock, mock.patch.object(
            MODULE.xplane_remote_relay, "run"
        ) as relay_run_mock:
            MODULE.run(args)

        wait_mock.assert_called_once()
        air_start_mock.assert_called_once_with(base_url="http://127.0.0.1:8086/api/v3")
        relay_run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
