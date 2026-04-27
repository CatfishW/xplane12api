#!/usr/bin/env python3
"""Remote X-Plane 12 telemetry relay for SSH-accessible GPU hosts.

This process runs beside X-Plane on the remote simulator host. For the XP12 host runtime,
production telemetry is pinned to direct RREF/Web API paths; the optional
XPlaneConnect mode remains available for explicit use or testing. In mock mode
it generates a synthetic endless-flight feed so Unity can be tested without a
live simulator.

The relay publishes newline-delimited JSON over plain TCP so downstream
consumers can ingest the live feed through a simple SSH port forward.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import socket
import struct
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, cast

from xplane12.autopilot import start_air_session_once
from xplane12.autopilot.controller import (
    DEFAULT_AIRCRAFT_PATH,
    activate_command,
    set_dataref,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def normalize_heading(heading: float) -> float:
    return heading % 360.0


def heading_delta(target: float, current: float) -> float:
    delta = (target - current + 180.0) % 360.0 - 180.0
    return delta


AP_STATE_HEADING_SELECT = 2
AP_STATE_ROLL_HOLD = 4
AP_STATE_VERTICAL_SPEED = 16
AP_STATE_ALTITUDE_ARM = 32
AP_STATE_PITCH_HOLD = 128
AP_STATE_ALTITUDE_HOLD = 16384
AP_STATE_HEADING_HOLD = 1048576


def offset_lat_lon(
    latitude: float, longitude: float, bearing_deg: float, distance_m: float
) -> Tuple[float, float]:
    distance_nm = distance_m / 1852.0
    bearing_rad = math.radians(bearing_deg)
    lat_delta = math.cos(bearing_rad) * distance_nm / 60.0
    lon_scale = max(math.cos(math.radians(latitude)), 0.01)
    lon_delta = math.sin(bearing_rad) * distance_nm / (60.0 * lon_scale)
    return latitude + lat_delta, longitude + lon_delta


@dataclass(frozen=True)
class RrefSubscription:
    index: int
    dataref: str


def build_rref_packet(freq_hz: int, index: int, dataref: str) -> bytes:
    packet = bytearray(413)
    packet[0:5] = b"RREF\x00"
    packet[5:9] = int(freq_hz).to_bytes(4, byteorder="little", signed=True)
    packet[9:13] = int(index).to_bytes(4, byteorder="little", signed=True)
    encoded = dataref.encode("ascii", errors="ignore")[:399]
    packet[13 : 13 + len(encoded)] = encoded
    packet[13 + len(encoded)] = 0
    return bytes(packet)


def parse_rref_payload(
    packet: bytes, index_to_dataref: Dict[int, str]
) -> Dict[str, float]:
    if len(packet) < 13 or packet[0:4] != b"RREF":
        return {}

    updates: Dict[str, float] = {}
    offset = 5
    while offset + 8 <= len(packet):
        index, value = struct.unpack_from("<if", packet, offset)
        dataref = index_to_dataref.get(index)
        if dataref is not None and math.isfinite(value):
            updates[dataref] = float(value)
        offset += 8
    return updates


@dataclass
class OwnshipState:
    latitude: float
    longitude: float
    altitude_m: float
    altitude_agl_m: float
    pitch_deg: float
    roll_deg: float
    heading_deg: float
    track_deg: float
    flight_path_angle_deg: float
    slip_skid: float
    indicated_airspeed_kt: float
    true_airspeed_kt: float
    ground_speed_kt: float
    vertical_speed_fpm: float
    autopilot_engaged: bool
    autopilot_mode: int
    gear_down: bool
    on_ground: bool
    gps_valid: bool
    ils_valid: bool
    throttle_ratio: float
    elevator_input: float
    aileron_input: float
    rudder_input: float
    flaps_ratio: float
    speedbrake_ratio: float
    parking_brake_ratio: float


@dataclass
class WeatherState:
    wind_speed_kt: float
    wind_direction_deg: float
    barometer_inhg: float
    temperature_c: float
    visibility_m: float
    cloud_base_m: float


@dataclass
class TrafficTarget:
    icao24: str
    callsign: str
    latitude: float
    longitude: float
    altitude_m: float
    heading_deg: float
    velocity_mps: float
    vertical_rate_mps: float
    on_ground: bool


@dataclass
class AutomationState:
    controller: str
    mode: str
    recovery_active: bool
    target_altitude_m: float
    target_heading_deg: float
    target_speed_kt: float


@dataclass
class TelemetrySnapshot:
    timestamp_utc: str
    source_mode: str
    ownship: OwnshipState
    weather: WeatherState
    traffic: List[TrafficTarget] = field(default_factory=list)
    raw: Dict[str, float] = field(default_factory=dict)
    automation: Optional[AutomationState] = None


class WebApiRecoveryController:
    def __init__(
        self,
        *,
        base_url: str,
        aircraft_path: str,
        confirm_seconds: float,
        min_restart_interval_seconds: float,
        grace_seconds: float,
    ) -> None:
        self._base_url = base_url
        self._aircraft_path = aircraft_path
        self._confirm_seconds = max(1.0, confirm_seconds)
        self._min_restart_interval_seconds = max(10.0, min_restart_interval_seconds)
        self._grace_seconds = max(5.0, grace_seconds)
        self._unhealthy_since: float | None = None
        self._last_restart_at = time.monotonic()

    def observe(self, snapshot: TelemetrySnapshot) -> bool:
        now = time.monotonic()
        if now - self._last_restart_at < self._grace_seconds:
            self._unhealthy_since = None
            return False
        if not self._is_unhealthy(snapshot):
            self._unhealthy_since = None
            return False
        if self._unhealthy_since is None:
            self._unhealthy_since = now
            return False
        if now - self._unhealthy_since < self._confirm_seconds:
            return False
        if now - self._last_restart_at < self._min_restart_interval_seconds:
            return False

        ownship = snapshot.ownship
        print(
            "[xplane_remote_relay] restarting flight after upset "
            f"agl_m={ownship.altitude_agl_m:.1f} gs_kt={ownship.ground_speed_kt:.1f} "
            f"pitch={ownship.pitch_deg:.1f} roll={ownship.roll_deg:.1f}",
            flush=True,
        )
        start_air_session_once(
            base_url=self._base_url,
            aircraft_path=self._aircraft_path,
        )
        self._last_restart_at = time.monotonic()
        self._unhealthy_since = None
        return True

    @staticmethod
    def _is_unhealthy(snapshot: TelemetrySnapshot) -> bool:
        ownship = snapshot.ownship
        severe_attitude = abs(ownship.roll_deg) >= 70.0 or abs(ownship.pitch_deg) >= 35.0
        broken_airspeed = (
            ownship.indicated_airspeed_kt >= 180.0
            and ownship.true_airspeed_kt <= 10.0
            and ownship.ground_speed_kt <= 10.0
        )
        crashed_on_surface = (
            ownship.altitude_agl_m <= 3.0
            and ownship.ground_speed_kt <= 8.0
            and (abs(ownship.roll_deg) >= 35.0 or abs(ownship.pitch_deg) >= 20.0)
        )
        return severe_attitude or broken_airspeed or crashed_on_surface


class WebApiHoldController:
    def __init__(
        self,
        *,
        base_url: str,
        aircraft_path: str,
        target_altitude_ft: float,
        target_heading_deg: float,
        target_speed_kt: float,
    ) -> None:
        self._base_url = base_url
        self._aircraft_path = aircraft_path
        self._normalized_path = aircraft_path.casefold()
        self._target_altitude_ft = target_altitude_ft
        self._target_altitude_m = target_altitude_ft * 0.3048
        self._target_heading_deg = normalize_heading(target_heading_deg)
        self._target_speed_kt = target_speed_kt
        self._is_rotorcraft = any(
            token in self._normalized_path for token in ("sikorsky s-76", "robinson r22")
        )
        self._supports_efis_weather = any(
            token in self._normalized_path
            for token in ("citation x", "baron 58", "737-800", "md-82", "a330")
        )
        self._supports_primus_tcas_window = "citation x" in self._normalized_path
        self._uses_gns = any(
            token in self._normalized_path
            for token in ("g530", "g430", "sikorsky s-76", "robinson r22", "172 sp", "king air", "baron 58")
        )
        self._display_setup_done = False
        self._last_gns_ack_at = 0.0
        self._last_target_sync_at = 0.0
        self._last_mode_arm_at = 0.0
        self._last_manual_trim_at = 0.0
        self._last_throttle_assist_at = 0.0
        self._last_log_at = 0.0

    def observe(self, snapshot: TelemetrySnapshot) -> AutomationState:
        now = time.monotonic()
        self._apply_display_setup(snapshot)
        self._dismiss_gns_startup(snapshot, now)

        if self._is_rotorcraft:
            return AutomationState(
                controller="webapi-rotorcraft-observer",
                mode="observe",
                recovery_active=False,
                target_altitude_m=self._target_altitude_m,
                target_heading_deg=self._target_heading_deg,
                target_speed_kt=self._target_speed_kt,
            )

        self._sync_targets(now)

        ownship = snapshot.ownship
        altitude_error_ft = (self._target_altitude_m - ownship.altitude_m) * 3.28084
        autopilot_state = self._read_raw_int(
            snapshot, "sim/cockpit/autopilot/autopilot_state"
        )
        servos_on = self._read_raw(snapshot, "sim/cockpit2/autopilot/servos_on") > 0.5
        autothrottle_on = (
            self._read_raw(snapshot, "sim/cockpit2/autopilot/autothrottle_on") > 0.5
        )
        slow_flight = ownship.indicated_airspeed_kt < max(
            150.0, self._target_speed_kt - 35.0
        )
        unstable_attitude = abs(ownship.roll_deg) >= 20.0 or abs(ownship.pitch_deg) >= 10.0
        needs_lateral_rearm = not servos_on or not self._heading_mode_active(
            snapshot, autopilot_state
        )
        needs_vertical_rearm = unstable_attitude or self._vertical_mode_mismatch(
            snapshot, autopilot_state, altitude_error_ft
        )
        needs_rearm = needs_lateral_rearm or needs_vertical_rearm

        mode = "hold"
        recovery_active = False
        if needs_rearm and now - self._last_mode_arm_at >= 6.0:
            self._engage_hold_modes(
                snapshot,
                altitude_error_ft=altitude_error_ft,
                unstable_attitude=unstable_attitude,
            )
            self._last_mode_arm_at = now
            mode = "rearm"
            recovery_active = True

        if not servos_on and now - self._last_manual_trim_at >= 0.6:
            self._apply_direct_trim(snapshot)
            self._last_manual_trim_at = now
            recovery_active = True
            if mode == "hold":
                mode = "assist"
        elif servos_on and now - self._last_manual_trim_at >= 2.0:
            self._neutralize_manual_inputs()
            self._last_manual_trim_at = now

        if (
            not autothrottle_on
            and (slow_flight or abs(self._target_speed_kt - ownship.indicated_airspeed_kt) >= 4.0)
            and now - self._last_throttle_assist_at >= 0.8
        ):
            self._apply_throttle_assist(snapshot)
            self._last_throttle_assist_at = now
            recovery_active = True
            if mode == "hold":
                mode = "assist"

        return AutomationState(
            controller="webapi-fixed-wing-hold",
            mode=mode,
            recovery_active=recovery_active,
            target_altitude_m=self._target_altitude_m,
            target_heading_deg=self._target_heading_deg,
            target_speed_kt=self._target_speed_kt,
        )

    def _apply_display_setup(self, snapshot: TelemetrySnapshot) -> None:
        if (
            self._display_setup_done
            or not self._supports_efis_weather
            or snapshot.ownship.altitude_agl_m <= 10.0
        ):
            return
        for dataref_name, value in (
            ("sim/cockpit2/EFIS/EFIS_tcas_on", 1.0),
            ("sim/cockpit2/EFIS/EFIS_tcas_on_copilot", 1.0),
        ):
            self._try_set_dataref(dataref_name, value)
        for command_name in (
            "sim/instruments/EFIS_wxr",
            "sim/instruments/EFIS_copilot_wxr",
            "sim/instruments/EFIS_wxr_radar_wx",
            "sim/instruments/EFIS_wxr_radar_wx_copilot",
            "sim/instruments/EFIS_wxr_auto_tilt_on",
            "sim/instruments/EFIS_wxr_auto_tilt_on_copilot",
            "sim/instruments/EFIS_wxr_gcs_on",
            "sim/instruments/EFIS_wxr_gcs_on_copilot",
            "sim/instruments/EFIS_wxr_pws_on",
            "sim/instruments/EFIS_wxr_multiscan_auto",
            "sim/instruments/EFIS_wxr_multiscan_auto_copilot",
        ):
            self._try_activate(command_name)
        if self._supports_primus_tcas_window:
            for command_name in (
                "sim/instruments/EFIS_tcas_window",
                "sim/instruments/EFIS_copilot_tcas_window",
            ):
                self._try_activate(command_name)
        self._display_setup_done = True

    def _dismiss_gns_startup(self, snapshot: TelemetrySnapshot, now: float) -> None:
        if (
            not self._uses_gns
            or now - self._last_gns_ack_at < 15.0
            or snapshot.ownship.altitude_agl_m <= 10.0
        ):
            return
        self._try_activate("sim/GPS/g430n1_ent")
        self._try_activate("sim/GPS/g430n1_ent")
        self._last_gns_ack_at = now

    def _sync_targets(self, now: float) -> None:
        if now - self._last_target_sync_at < 2.0:
            return
        for dataref_name, value in (
            ("sim/cockpit2/autopilot/autopilot_electric_master", 1.0),
            ("sim/cockpit2/autopilot/master_flight_director", 1.0),
            ("sim/cockpit/autopilot/heading_mag", self._target_heading_deg),
            ("sim/cockpit/autopilot/heading_mag2", self._target_heading_deg),
            ("sim/cockpit/autopilot/altitude", self._target_altitude_ft),
            ("sim/cockpit/autopilot/airspeed", self._target_speed_kt),
            ("sim/cockpit2/autopilot/heading_dial_deg_mag_pilot", self._target_heading_deg),
            ("sim/cockpit2/autopilot/heading_dial_deg_mag_copilot", self._target_heading_deg),
            ("sim/cockpit2/autopilot/altitude_dial_ft", self._target_altitude_ft),
            ("sim/cockpit2/autopilot/airspeed_dial_kts", self._target_speed_kt),
            ("sim/cockpit2/autopilot/airspeed_dial_kts_mach", self._target_speed_kt),
        ):
            self._try_set_dataref(dataref_name, value)
        self._last_target_sync_at = now

    def _engage_hold_modes(
        self,
        snapshot: TelemetrySnapshot,
        *,
        altitude_error_ft: float,
        unstable_attitude: bool,
    ) -> None:
        if unstable_attitude:
            self._try_activate("sim/autopilot/return_to_level")
        for command_name in (
            "sim/autopilot/fdir_on",
            "sim/autopilot/servos_on",
            "sim/autopilot/heading",
        ):
            self._try_activate(command_name)
        if self._read_raw(snapshot, "sim/cockpit2/autopilot/autothrottle_arm") > 0.5:
            self._try_activate("sim/autopilot/autothrottle_on")

        vertical_speed_fpm = snapshot.ownship.vertical_speed_fpm
        if abs(altitude_error_ft) <= 250.0 and abs(vertical_speed_fpm) <= 600.0:
            self._try_activate("sim/autopilot/altitude_hold")
            return

        target_vvi_fpm = clamp(altitude_error_ft * 1.4, -1800.0, 1800.0)
        if abs(target_vvi_fpm) < 500.0:
            target_vvi_fpm = 500.0 if target_vvi_fpm >= 0.0 else -500.0
        self._try_activate("sim/autopilot/vertical_speed")
        for dataref_name in (
            "sim/cockpit/autopilot/vertical_velocity",
            "sim/cockpit2/autopilot/vvi_dial_fpm",
        ):
            self._try_set_dataref(dataref_name, target_vvi_fpm)
        self._try_activate("sim/autopilot/altitude_arm")

    def _apply_direct_trim(self, snapshot: TelemetrySnapshot) -> None:
        ownship = snapshot.ownship
        pitch_cmd = clamp(
            ((self._target_altitude_m - ownship.altitude_m) * 3.28084) / 4500.0
            - ownship.vertical_speed_fpm / 3200.0,
            -0.12,
            0.12,
        )
        roll_cmd = clamp(
            heading_delta(self._target_heading_deg, ownship.heading_deg) / 70.0
            - ownship.roll_deg / 55.0,
            -0.15,
            0.15,
        )
        self._try_set_dataref("sim/joystick/yoke_pitch_ratio", pitch_cmd)
        self._try_set_dataref("sim/joystick/yoke_roll_ratio", roll_cmd)
        self._try_set_dataref("sim/joystick/yoke_heading_ratio", 0.0)
        self._apply_throttle_assist(snapshot)

    def _apply_throttle_assist(self, snapshot: TelemetrySnapshot) -> None:
        ownship = snapshot.ownship
        throttle_cmd = clamp(
            0.56 + (self._target_speed_kt - ownship.indicated_airspeed_kt) / 135.0,
            0.32,
            0.9,
        )
        self._try_set_dataref("sim/cockpit2/engine/actuators/throttle_ratio_all", throttle_cmd)

    def _neutralize_manual_inputs(self) -> None:
        for dataref_name in (
            "sim/joystick/yoke_pitch_ratio",
            "sim/joystick/yoke_roll_ratio",
            "sim/joystick/yoke_heading_ratio",
        ):
            self._try_set_dataref(dataref_name, 0.0)

    def _try_activate(self, command_name: str) -> None:
        try:
            activate_command(command_name, base_url=self._base_url)
        except Exception as error:
            self._maybe_log_error(f"command {command_name} failed: {error}")

    def _try_set_dataref(self, dataref_name: str, value: float) -> None:
        try:
            set_dataref(dataref_name, float(value), base_url=self._base_url)
        except Exception as error:
            self._maybe_log_error(f"dataref {dataref_name} failed: {error}")

    def _maybe_log_error(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_log_at < 15.0:
            return
        self._last_log_at = now
        print(f"[xplane_remote_relay] {message}", flush=True)

    @staticmethod
    def _read_raw(snapshot: TelemetrySnapshot, dataref_name: str, default: float = 0.0) -> float:
        value = snapshot.raw.get(dataref_name, default)
        return float(value) if math.isfinite(value) else default

    @classmethod
    def _read_raw_int(
        cls, snapshot: TelemetrySnapshot, dataref_name: str, default: int = 0
    ) -> int:
        return int(round(cls._read_raw(snapshot, dataref_name, float(default))))

    def _heading_mode_active(
        self, snapshot: TelemetrySnapshot, autopilot_state: int
    ) -> bool:
        if autopilot_state & (AP_STATE_HEADING_SELECT | AP_STATE_HEADING_HOLD):
            return True
        heading_status = self._read_raw_int(
            snapshot, "sim/cockpit2/autopilot/heading_status"
        )
        heading_hold_status = self._read_raw_int(
            snapshot, "sim/cockpit2/autopilot/heading_hold_status"
        )
        return heading_status >= 2 or heading_hold_status >= 2

    def _vertical_mode_mismatch(
        self,
        snapshot: TelemetrySnapshot,
        autopilot_state: int,
        altitude_error_ft: float,
    ) -> bool:
        altitude_hold_status = self._read_raw_int(
            snapshot, "sim/cockpit2/autopilot/altitude_hold_status"
        )
        altitude_mode = self._read_raw_int(snapshot, "sim/cockpit2/autopilot/altitude_mode")
        altitude_hold_active = bool(autopilot_state & AP_STATE_ALTITUDE_HOLD) or altitude_hold_status >= 2
        altitude_capture_armed = bool(autopilot_state & AP_STATE_ALTITUDE_ARM) or altitude_hold_status == 1
        vertical_speed_active = bool(autopilot_state & AP_STATE_VERTICAL_SPEED) or altitude_mode == 4

        if abs(altitude_error_ft) <= 250.0:
            return not altitude_hold_active
        return not (altitude_capture_armed and vertical_speed_active)


class FlightSource(Protocol):
    def next_snapshot(self) -> TelemetrySnapshot: ...

    def close(self) -> None: ...


class XpcClientProtocol(Protocol):
    def close(self) -> None: ...

    def getPOSI(self) -> Sequence[float]: ...

    def getCTRL(self) -> Sequence[float]: ...

    def getDREFs(self, drefs: Sequence[str]) -> List[Sequence[float]]: ...

    def pauseSim(self, pause: bool) -> None: ...

    def sendPOSI(self, values: Sequence[float]) -> None: ...

    def sendCTRL(self, values: Sequence[float]) -> None: ...


class BroadcastServer:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen()
        self._clients: List[socket.socket] = []
        self._lock = threading.Lock()
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="XPlaneRelayAccept", daemon=True
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client, _ = self._server.accept()
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self._lock:
                    self._clients.append(client)
            except OSError:
                return

    def broadcast(self, snapshot: TelemetrySnapshot) -> None:
        payload = json.dumps(asdict(snapshot), separators=(",", ":")) + "\n"
        encoded = payload.encode("utf-8")
        stale: List[socket.socket] = []
        with self._lock:
            for client in self._clients:
                try:
                    client.sendall(encoded)
                except OSError:
                    stale.append(client)
            for client in stale:
                self._clients.remove(client)
                try:
                    client.close()
                except OSError:
                    pass

    def close(self) -> None:
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()


class MockFlightSource:
    def __init__(
        self,
        target_altitude_ft: float,
        target_speed_kt: float,
        target_heading_deg: float,
        traffic_count: int,
    ) -> None:
        self._lat = 33.6407
        self._lon = -84.4277
        self._alt_m = target_altitude_ft * 0.3048
        self._heading = target_heading_deg
        self._speed = target_speed_kt
        self._vertical_speed_fpm = 0.0
        self._traffic_count = traffic_count
        self._start = time.time()

    def next_snapshot(self) -> TelemetrySnapshot:
        elapsed = time.time() - self._start
        heading_wobble = math.sin(elapsed / 20.0) * 8.0
        self._heading = normalize_heading(self._heading + 0.4)
        track = normalize_heading(self._heading + heading_wobble)
        self._vertical_speed_fpm = math.sin(elapsed / 12.0) * 120.0
        self._alt_m += (self._vertical_speed_fpm / 196.8504) * 0.2
        self._lat += math.cos(math.radians(track)) * 0.00012
        self._lon += math.sin(math.radians(track)) * 0.00012

        ownship = OwnshipState(
            latitude=self._lat,
            longitude=self._lon,
            altitude_m=self._alt_m,
            altitude_agl_m=max(250.0, self._alt_m - 120.0),
            pitch_deg=math.sin(elapsed / 8.0) * 2.0,
            roll_deg=math.sin(elapsed / 6.0) * 6.0,
            heading_deg=self._heading,
            track_deg=track,
            flight_path_angle_deg=self._vertical_speed_fpm / 600.0,
            slip_skid=math.sin(elapsed / 4.5) * 0.08,
            indicated_airspeed_kt=self._speed,
            true_airspeed_kt=self._speed + 6.0,
            ground_speed_kt=self._speed - 4.0,
            vertical_speed_fpm=self._vertical_speed_fpm,
            autopilot_engaged=True,
            autopilot_mode=2,
            gear_down=False,
            on_ground=False,
            gps_valid=True,
            ils_valid=False,
            throttle_ratio=0.62,
            elevator_input=clamp(self._vertical_speed_fpm / 700.0, -0.2, 0.2),
            aileron_input=clamp(heading_wobble / 20.0, -0.3, 0.3),
            rudder_input=0.0,
            flaps_ratio=0.0,
            speedbrake_ratio=0.0,
            parking_brake_ratio=0.0,
        )

        weather = WeatherState(
            wind_speed_kt=18.0,
            wind_direction_deg=235.0,
            barometer_inhg=29.92,
            temperature_c=11.0,
            visibility_m=12000.0,
            cloud_base_m=2200.0,
        )

        traffic: List[TrafficTarget] = []
        for idx in range(self._traffic_count):
            bearing = normalize_heading(
                self._heading + idx * (360.0 / max(1, self._traffic_count))
            )
            distance_nm = 4.0 + idx * 2.5
            offset_lat = math.cos(math.radians(bearing)) * distance_nm * 0.0166
            offset_lon = math.sin(math.radians(bearing)) * distance_nm * 0.0166
            traffic.append(
                TrafficTarget(
                    icao24=f"MOCK{idx:02d}",
                    callsign=f"M{idx:03d}",
                    latitude=self._lat + offset_lat,
                    longitude=self._lon + offset_lon,
                    altitude_m=self._alt_m + (idx - 1) * 180.0,
                    heading_deg=normalize_heading(bearing + 180.0),
                    velocity_mps=70.0 + idx * 8.0,
                    vertical_rate_mps=(-1.5 + idx) * 0.4,
                    on_ground=False,
                )
            )

        raw = {
            "sim/flightmodel/position/latitude": ownship.latitude,
            "sim/flightmodel/position/longitude": ownship.longitude,
            "sim/flightmodel/position/elevation": ownship.altitude_m,
            "sim/flightmodel/position/theta": ownship.pitch_deg,
            "sim/flightmodel/position/phi": ownship.roll_deg,
            "sim/flightmodel/position/psi": ownship.heading_deg,
            "sim/weather/aircraft/wind_speed_kt": weather.wind_speed_kt,
            "sim/weather/aircraft/wind_direction_deg": weather.wind_direction_deg,
        }

        automation = AutomationState(
            controller="mock-envelope-keeper",
            mode="hold",
            recovery_active=False,
            target_altitude_m=self._alt_m,
            target_heading_deg=self._heading,
            target_speed_kt=self._speed,
        )

        return TelemetrySnapshot(
            timestamp_utc=utc_now(),
            source_mode="mock",
            ownship=ownship,
            weather=weather,
            traffic=traffic,
            raw=raw,
            automation=automation,
        )


class XPlaneConnectSource:
    WEATHER_DREFS = [
        "sim/weather/wind_speed_kt[0]",
        "sim/weather/wind_direction_degt[0]",
        "sim/weather/barometer_sealevel_inhg",
        "sim/weather/temperature_ambient_c",
    ]

    XP11_WEATHER_DREFS = [
        "sim/weather/barometer_sealevel_inhg",
        "sim/weather/temperature_sealevel_c",
    ]

    OWN_DREFS = [
        "sim/flightmodel/position/indicated_airspeed",
        "sim/flightmodel/position/true_airspeed",
        "sim/flightmodel/position/groundspeed",
        "sim/flightmodel/position/vh_ind",
        "sim/cockpit/autopilot/autopilot_state",
        "sim/cockpit/switches/gear_handle_status",
    ]

    def __init__(
        self,
        xp_host: str,
        xp_port: int,
        target_altitude_ft: float,
        target_heading_deg: float,
        target_speed_kt: float,
        recovery_altitude_ft: float,
        traffic_slots: int,
    ) -> None:
        try:
            xpc_module = importlib.import_module("xpc")
        except (
            ImportError
        ) as exc:  # pragma: no cover - runtime dependency on remote host
            raise RuntimeError(
                "Python xpc module not available. Install NASA XPlaneConnect client on the X-Plane host."
            ) from exc

        client = xpc_module.XPlaneConnect(xpHost=xp_host, xpPort=xp_port, timeout=1000)
        self._xpc = cast(XpcClientProtocol, client)
        self._target_altitude_m = target_altitude_ft * 0.3048
        self._target_heading_deg = target_heading_deg
        self._target_speed_kt = target_speed_kt
        self._recovery_altitude_m = recovery_altitude_ft * 0.3048
        self._traffic_slots = traffic_slots

    def close(self) -> None:
        self._xpc.close()

    def next_snapshot(self) -> TelemetrySnapshot:
        posi = self._xpc.getPOSI()
        ctrl = self._xpc.getCTRL()
        own_values = self._xpc.getDREFs(self.OWN_DREFS)
        weather_values = self._safe_get_drefs(
            self.WEATHER_DREFS, self.XP11_WEATHER_DREFS
        )

        lat, lon, altitude_m, pitch_deg, roll_deg, heading_deg, gear = posi
        indicated_airspeed = own_values[0][0]
        true_airspeed = own_values[1][0]
        ground_speed_kt = own_values[2][0] * 1.94384
        vertical_speed_fpm = own_values[3][0] * 196.8504
        autopilot_mode = int(own_values[4][0])
        gear_down = bool(own_values[5][0] > 0.5)

        recovery_active = (
            altitude_m < self._recovery_altitude_m
            or abs(roll_deg) > 70.0
            or ground_speed_kt < 55.0
        )
        mode = "recover" if recovery_active else "hold"
        if recovery_active:
            self._xpc.pauseSim(True)
            self._xpc.sendPOSI(
                [
                    lat,
                    lon,
                    self._target_altitude_m,
                    0.0,
                    0.0,
                    self._target_heading_deg,
                    1.0,
                ]
            )
            self._xpc.pauseSim(False)
        else:
            pitch_cmd = clamp(
                ((self._target_altitude_m - altitude_m) * 3.28084) / 2500.0
                - vertical_speed_fpm / 3000.0,
                -0.35,
                0.35,
            )
            roll_cmd = clamp(
                heading_delta(self._target_heading_deg, heading_deg) / 45.0, -0.35, 0.35
            )
            throttle_cmd = clamp(
                0.55 + (self._target_speed_kt - ground_speed_kt) / 120.0, 0.15, 1.0
            )
            self._xpc.sendCTRL(
                [pitch_cmd, roll_cmd, 0.0, throttle_cmd, 1.0 if gear_down else 0.0, 0.0]
            )

        weather = WeatherState(
            wind_speed_kt=float(weather_values[0][0]) if weather_values else 0.0,
            wind_direction_deg=float(weather_values[1][0])
            if len(weather_values) > 1
            else 0.0,
            barometer_inhg=float(weather_values[2][0])
            if len(weather_values) > 2
            else 29.92,
            temperature_c=float(weather_values[3][0])
            if len(weather_values) > 3
            else 15.0,
            visibility_m=12000.0,
            cloud_base_m=max(altitude_m + 500.0, 1800.0),
        )

        ownship = OwnshipState(
            latitude=float(lat),
            longitude=float(lon),
            altitude_m=float(altitude_m),
            altitude_agl_m=max(altitude_m - 150.0, 100.0),
            pitch_deg=float(pitch_deg),
            roll_deg=float(roll_deg),
            heading_deg=normalize_heading(float(heading_deg)),
            track_deg=normalize_heading(float(heading_deg)),
            flight_path_angle_deg=clamp(vertical_speed_fpm / 600.0, -10.0, 10.0),
            slip_skid=0.0,
            indicated_airspeed_kt=float(indicated_airspeed),
            true_airspeed_kt=float(true_airspeed),
            ground_speed_kt=float(ground_speed_kt),
            vertical_speed_fpm=float(vertical_speed_fpm),
            autopilot_engaged=autopilot_mode >= 2,
            autopilot_mode=autopilot_mode,
            gear_down=gear_down,
            on_ground=altitude_m < 3.0,
            gps_valid=True,
            ils_valid=False,
            throttle_ratio=float(ctrl[3]),
            elevator_input=float(ctrl[0]),
            aileron_input=float(ctrl[1]),
            rudder_input=float(ctrl[2]),
            flaps_ratio=float(ctrl[5]),
            speedbrake_ratio=float(ctrl[6]) if len(ctrl) > 6 else 0.0,
            parking_brake_ratio=0.0,
        )

        traffic = self._read_traffic(float(lat), float(lon), float(altitude_m))
        raw = {
            "sim/flightmodel/position/latitude": float(lat),
            "sim/flightmodel/position/longitude": float(lon),
            "sim/flightmodel/position/elevation": float(altitude_m),
            "sim/flightmodel/position/theta": float(pitch_deg),
            "sim/flightmodel/position/phi": float(roll_deg),
            "sim/flightmodel/position/psi": float(heading_deg),
            "sim/cockpit/autopilot/autopilot_state": float(autopilot_mode),
            "sim/weather/barometer_sealevel_inhg": weather.barometer_inhg,
        }

        automation = AutomationState(
            controller="xpc-envelope-keeper",
            mode=mode,
            recovery_active=recovery_active,
            target_altitude_m=self._target_altitude_m,
            target_heading_deg=self._target_heading_deg,
            target_speed_kt=self._target_speed_kt,
        )

        return TelemetrySnapshot(
            timestamp_utc=utc_now(),
            source_mode="xpc",
            ownship=ownship,
            weather=weather,
            traffic=traffic,
            raw=raw,
            automation=automation,
        )

    def _safe_get_drefs(
        self, primary: Sequence[str], fallback: Sequence[str]
    ) -> List[Sequence[float]]:
        try:
            return self._xpc.getDREFs(list(primary))
        except Exception:
            return self._xpc.getDREFs(list(fallback))

    def _read_traffic(
        self, own_lat: float, own_lon: float, own_alt: float
    ) -> List[TrafficTarget]:
        targets: List[TrafficTarget] = []
        for slot in range(1, self._traffic_slots + 1):
            drefs = [
                f"sim/multiplayer/position/plane{slot}_lat",
                f"sim/multiplayer/position/plane{slot}_lon",
                f"sim/multiplayer/position/plane{slot}_el",
                f"sim/multiplayer/position/plane{slot}_psi",
                f"sim/multiplayer/position/plane{slot}_v_x",
                f"sim/multiplayer/position/plane{slot}_v_y",
                f"sim/multiplayer/position/plane{slot}_v_z",
                f"sim/multiplayer/position/plane{slot}_gear_deploy",
            ]
            try:
                values = self._xpc.getDREFs(drefs)
            except Exception:
                continue

            lat = float(values[0][0])
            lon = float(values[1][0])
            if abs(lat) < 0.001 and abs(lon) < 0.001:
                continue

            vx = float(values[4][0])
            vy = float(values[5][0])
            vz = float(values[6][0])
            velocity_mps = math.sqrt(vx * vx + vy * vy + vz * vz)
            targets.append(
                TrafficTarget(
                    icao24=f"XPL{slot:04d}",
                    callsign=f"XP{slot:02d}",
                    latitude=lat,
                    longitude=lon,
                    altitude_m=float(values[2][0]),
                    heading_deg=normalize_heading(float(values[3][0])),
                    velocity_mps=velocity_mps,
                    vertical_rate_mps=vy,
                    on_ground=bool(values[7][0] > 0.5),
                )
            )

        if not targets:
            for idx in range(3):
                targets.append(
                    TrafficTarget(
                        icao24=f"SYN{idx:04d}",
                        callsign=f"SYN{idx:02d}",
                        latitude=own_lat + 0.04 * (idx + 1),
                        longitude=own_lon - 0.03 * (idx + 1),
                        altitude_m=own_alt + idx * 250.0,
                        heading_deg=normalize_heading(
                            self._target_heading_deg + idx * 40.0
                        ),
                        velocity_mps=80.0 + idx * 15.0,
                        vertical_rate_mps=0.0,
                        on_ground=False,
                    )
                )

        return targets


class RrefFlightSource:
    OWN_DREFS = [
        "sim/flightmodel/position/latitude",
        "sim/flightmodel/position/longitude",
        "sim/flightmodel/position/elevation",
        "sim/flightmodel/position/y_agl",
        "sim/flightmodel/position/theta",
        "sim/flightmodel/position/phi",
        "sim/flightmodel/position/psi",
        "sim/flightmodel/position/indicated_airspeed",
        "sim/flightmodel/position/true_airspeed",
        "sim/flightmodel/position/groundspeed",
        "sim/flightmodel/position/vh_ind",
        "sim/cockpit/autopilot/autopilot_mode",
        "sim/cockpit/autopilot/autopilot_state",
        "sim/cockpit2/autopilot/autopilot_mode",
        "sim/cockpit2/autopilot/servos_on",
        "sim/cockpit2/autopilot/flight_director_mode",
        "sim/cockpit2/autopilot/flight_director_master_pilot",
        "sim/cockpit2/autopilot/heading_status",
        "sim/cockpit2/autopilot/heading_hold_status",
        "sim/cockpit2/autopilot/altitude_hold_status",
        "sim/cockpit2/autopilot/altitude_mode",
        "sim/cockpit2/autopilot/autothrottle_on",
        "sim/cockpit2/autopilot/autothrottle_arm",
        "sim/cockpit2/gauges/indicators/gps_status",
        "sim/cockpit2/radios/nav1_has_glideslope",
        "sim/cockpit/switches/gear_handle_status",
    ]

    WEATHER_DREFS = [
        "sim/weather/wind_speed_kt",
        "sim/weather/wind_direction_degt",
        "sim/weather/barometer_sealevel_inhg",
        "sim/weather/temperature_ambient_c",
        "sim/weather/visibility_reported_m",
        "sim/weather/cloud_base_msl_m[0]",
    ]

    CONTROL_DREFS = [
        "sim/joystick/yoke_pitch_ratio",
        "sim/joystick/yoke_roll_ratio",
        "sim/joystick/yoke_heading_ratio",
        "sim/cockpit2/engine/actuators/throttle_ratio_all",
        "sim/cockpit2/controls/flap_ratio",
        "sim/cockpit2/controls/speedbrake_ratio",
        "sim/cockpit2/controls/parking_brake_ratio",
    ]

    TRAFFIC_DREFS = [
        "sim/cockpit2/tcas/targets/modeS_id",
        "sim/cockpit2/tcas/targets/relative_distance_m",
        "sim/cockpit2/tcas/targets/relative_bearing_degt",
        "sim/cockpit2/tcas/targets/altitude_ft",
    ]

    def __init__(
        self,
        xp_host: str,
        udp_port: int,
        listen_host: str,
        listen_port: int,
        subscription_hz: float,
        sample_timeout_seconds: float,
        target_altitude_ft: float,
        target_heading_deg: float,
        target_speed_kt: float,
        traffic_slots: int,
    ) -> None:
        self._target = (xp_host, udp_port)
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._subscription_hz = max(1, int(round(subscription_hz)))
        self._sample_timeout_seconds = max(0.1, sample_timeout_seconds)
        self._target_altitude_m = target_altitude_ft * 0.3048
        self._target_heading_deg = target_heading_deg
        self._target_speed_kt = target_speed_kt
        self._traffic_slots = traffic_slots
        self._last_rx_time = 0.0
        self._next_subscription_refresh = 0.0
        self._values: Dict[str, float] = {}
        self._subscriptions = self._build_subscriptions(traffic_slots)
        self._index_to_dataref = {
            subscription.index: subscription.dataref
            for subscription in self._subscriptions
        }
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((listen_host, listen_port))
        self._socket.settimeout(self._sample_timeout_seconds)
        self._refresh_subscriptions(force=True)

    def close(self) -> None:
        for subscription in self._subscriptions:
            try:
                self._socket.sendto(
                    build_rref_packet(0, subscription.index, subscription.dataref),
                    self._target,
                )
            except OSError:
                break
        try:
            self._socket.close()
        except OSError:
            pass

    def next_snapshot(self) -> TelemetrySnapshot:
        self._refresh_subscriptions()
        self._drain_updates(self._sample_timeout_seconds)
        if not self._values:
            raise RuntimeError(
                "No X-Plane RREF telemetry received. Verify the simulator is in-flight and UDP data output is enabled."
            )
        if time.time() - self._last_rx_time > max(
            2.0, self._sample_timeout_seconds * 3.0
        ):
            raise RuntimeError("X-Plane RREF telemetry became stale.")
        return self._build_snapshot(dict(self._values))

    def _refresh_subscriptions(self, force: bool = False) -> None:
        now = time.time()
        if not force and now < self._next_subscription_refresh:
            return
        for subscription in self._subscriptions:
            self._socket.sendto(
                build_rref_packet(
                    self._subscription_hz, subscription.index, subscription.dataref
                ),
                self._target,
            )
        self._next_subscription_refresh = now + 10.0

    def _drain_updates(self, timeout_seconds: float) -> None:
        deadline = time.time() + timeout_seconds
        received_any = False
        while time.time() < deadline:
            remaining = max(0.05, min(0.25, deadline - time.time()))
            self._socket.settimeout(remaining)
            try:
                payload, _ = self._socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                raise RuntimeError(f"RREF receive failed: {exc}") from exc

            updates = parse_rref_payload(payload, self._index_to_dataref)
            if not updates:
                continue
            self._values.update(updates)
            self._last_rx_time = time.time()
            received_any = True
            if len(updates) >= 4:
                break

        if not received_any and self._values:
            self._socket.settimeout(self._sample_timeout_seconds)

    @classmethod
    def _build_subscriptions(cls, traffic_slots: int) -> List[RrefSubscription]:
        refs = list(cls.OWN_DREFS) + list(cls.WEATHER_DREFS) + list(cls.CONTROL_DREFS)
        for slot in range(traffic_slots):
            for base in cls.TRAFFIC_DREFS:
                refs.append(f"{base}[{slot}]")
        return [
            RrefSubscription(index=1000 + idx, dataref=dataref)
            for idx, dataref in enumerate(refs)
        ]

    def _build_snapshot(self, values: Dict[str, float]) -> TelemetrySnapshot:
        def read(dataref: str, default: float = 0.0) -> float:
            value = values.get(dataref, default)
            return float(value) if math.isfinite(value) else default

        altitude_m = read("sim/flightmodel/position/elevation")
        altitude_agl_m = max(read("sim/flightmodel/position/y_agl"), 0.0)
        heading_deg = normalize_heading(read("sim/flightmodel/position/psi"))
        ground_speed_kt = read("sim/flightmodel/position/groundspeed") * 1.94384
        vertical_speed_fpm = read("sim/flightmodel/position/vh_ind") * 196.8504
        autopilot_mode = int(
            round(
                read(
                    "sim/cockpit/autopilot/autopilot_mode",
                    read("sim/cockpit2/autopilot/autopilot_mode"),
                )
            )
        )
        servos_on = read("sim/cockpit2/autopilot/servos_on") > 0.5
        flight_director_mode = int(round(read("sim/cockpit2/autopilot/flight_director_mode")))

        weather_cloud_base = read("sim/weather/cloud_base_msl_m[0]")
        if weather_cloud_base <= 0.0:
            weather_cloud_base = max(altitude_m + 500.0, 1800.0)

        ownship = OwnshipState(
            latitude=read("sim/flightmodel/position/latitude"),
            longitude=read("sim/flightmodel/position/longitude"),
            altitude_m=altitude_m,
            altitude_agl_m=altitude_agl_m,
            pitch_deg=read("sim/flightmodel/position/theta"),
            roll_deg=read("sim/flightmodel/position/phi"),
            heading_deg=heading_deg,
            track_deg=heading_deg,
            flight_path_angle_deg=clamp(vertical_speed_fpm / 600.0, -10.0, 10.0),
            slip_skid=0.0,
            indicated_airspeed_kt=read("sim/flightmodel/position/indicated_airspeed"),
            true_airspeed_kt=read("sim/flightmodel/position/true_airspeed"),
            ground_speed_kt=ground_speed_kt,
            vertical_speed_fpm=vertical_speed_fpm,
            autopilot_engaged=servos_on or flight_director_mode >= 2 or autopilot_mode >= 2,
            autopilot_mode=autopilot_mode,
            gear_down=read("sim/cockpit/switches/gear_handle_status") > 0.5,
            on_ground=altitude_agl_m < 3.0,
            gps_valid=read("sim/cockpit2/gauges/indicators/gps_status", 1.0) > 0.5,
            ils_valid=read("sim/cockpit2/radios/nav1_has_glideslope") > 0.5,
            throttle_ratio=clamp(
                read("sim/cockpit2/engine/actuators/throttle_ratio_all"), 0.0, 1.0
            ),
            elevator_input=clamp(read("sim/joystick/yoke_pitch_ratio"), -1.0, 1.0),
            aileron_input=clamp(read("sim/joystick/yoke_roll_ratio"), -1.0, 1.0),
            rudder_input=clamp(read("sim/joystick/yoke_heading_ratio"), -1.0, 1.0),
            flaps_ratio=clamp(read("sim/cockpit2/controls/flap_ratio"), 0.0, 1.0),
            speedbrake_ratio=clamp(
                read("sim/cockpit2/controls/speedbrake_ratio"), 0.0, 1.0
            ),
            parking_brake_ratio=clamp(
                read("sim/cockpit2/controls/parking_brake_ratio"), 0.0, 1.0
            ),
        )

        weather = WeatherState(
            wind_speed_kt=read("sim/weather/wind_speed_kt"),
            wind_direction_deg=normalize_heading(
                read("sim/weather/wind_direction_degt")
            ),
            barometer_inhg=read("sim/weather/barometer_sealevel_inhg", 29.92),
            temperature_c=read("sim/weather/temperature_ambient_c", 15.0),
            visibility_m=read("sim/weather/visibility_reported_m", 12000.0),
            cloud_base_m=weather_cloud_base,
        )

        traffic = self._build_traffic(values, ownship)
        raw = {
            key: float(value) for key, value in values.items() if math.isfinite(value)
        }
        automation = AutomationState(
            controller="rref-telemetry-observer",
            mode="observe",
            recovery_active=False,
            target_altitude_m=self._target_altitude_m,
            target_heading_deg=self._target_heading_deg,
            target_speed_kt=self._target_speed_kt,
        )

        return TelemetrySnapshot(
            timestamp_utc=utc_now(),
            source_mode="rref",
            ownship=ownship,
            weather=weather,
            traffic=traffic,
            raw=raw,
            automation=automation,
        )

    def _build_traffic(
        self, values: Dict[str, float], ownship: OwnshipState
    ) -> List[TrafficTarget]:
        targets: List[TrafficTarget] = []
        for slot in range(self._traffic_slots):
            mode_s = int(
                round(values.get(f"sim/cockpit2/tcas/targets/modeS_id[{slot}]", 0.0))
            )
            distance_m = float(
                values.get(
                    f"sim/cockpit2/tcas/targets/relative_distance_m[{slot}]", 0.0
                )
            )
            relative_bearing = float(
                values.get(
                    f"sim/cockpit2/tcas/targets/relative_bearing_degt[{slot}]", 0.0
                )
            )
            altitude_ft = float(
                values.get(f"sim/cockpit2/tcas/targets/altitude_ft[{slot}]", 0.0)
            )
            if mode_s <= 0 and distance_m <= 1.0 and altitude_ft <= 0.0:
                continue

            bearing_deg = normalize_heading(ownship.heading_deg + relative_bearing)
            latitude, longitude = offset_lat_lon(
                ownship.latitude, ownship.longitude, bearing_deg, max(distance_m, 0.0)
            )
            altitude_m = (
                altitude_ft * 0.3048 if altitude_ft > 0.0 else ownship.altitude_m
            )
            icao24 = f"{mode_s:06X}" if mode_s > 0 else f"RRF{slot:02d}"
            targets.append(
                TrafficTarget(
                    icao24=icao24,
                    callsign=icao24,
                    latitude=latitude,
                    longitude=longitude,
                    altitude_m=altitude_m,
                    heading_deg=bearing_deg,
                    velocity_mps=0.0,
                    vertical_rate_mps=0.0,
                    on_ground=altitude_m < 5.0,
                )
            )
        if targets:
            return targets

        for idx in range(3):
            targets.append(
                TrafficTarget(
                    icao24=f"SRR{idx:04d}",
                    callsign=f"SRR{idx:02d}",
                    latitude=ownship.latitude + 0.04 * (idx + 1),
                    longitude=ownship.longitude - 0.03 * (idx + 1),
                    altitude_m=ownship.altitude_m + idx * 250.0,
                    heading_deg=normalize_heading(
                        self._target_heading_deg + idx * 40.0
                    ),
                    velocity_mps=80.0 + idx * 15.0,
                    vertical_rate_mps=0.0,
                    on_ground=False,
                )
            )

        return targets


class AutoFlightSource:
    def __init__(
        self,
        xp_host: str,
        xpc_port: int,
        udp_port: int,
        listen_host: str,
        listen_port: int,
        subscription_hz: float,
        sample_timeout_seconds: float,
        target_altitude_ft: float,
        target_heading_deg: float,
        target_speed_kt: float,
        recovery_altitude_ft: float,
        traffic_slots: int,
    ) -> None:
        self._xp_host = xp_host
        self._xpc_port = xpc_port
        self._udp_port = udp_port
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._subscription_hz = subscription_hz
        self._sample_timeout_seconds = sample_timeout_seconds
        self._target_altitude_ft = target_altitude_ft
        self._target_heading_deg = target_heading_deg
        self._target_speed_kt = target_speed_kt
        self._recovery_altitude_ft = recovery_altitude_ft
        self._traffic_slots = traffic_slots
        self._active_source: Optional[FlightSource] = None
        self._active_mode = ""
        self._activate_primary()

    def close(self) -> None:
        active = self._active_source
        if active is None:
            return
        close_method = getattr(active, "close", None)
        if callable(close_method):
            close_method()

    def next_snapshot(self) -> TelemetrySnapshot:
        if self._active_source is None:
            self._activate_fallback("xpc source unavailable")

        active = self._active_source
        if active is None:
            raise RuntimeError("No relay source is available.")

        if self._active_mode == "xpc":
            try:
                return active.next_snapshot()
            except Exception as exc:
                self._activate_fallback(str(exc))

        active = self._active_source
        if active is None:
            raise RuntimeError("RREF fallback source is unavailable.")
        return active.next_snapshot()

    def _activate_primary(self) -> None:
        try:
            self._active_source = XPlaneConnectSource(
                self._xp_host,
                self._xpc_port,
                self._target_altitude_ft,
                self._target_heading_deg,
                self._target_speed_kt,
                self._recovery_altitude_ft,
                self._traffic_slots,
            )
            self._active_mode = "xpc"
        except Exception as exc:
            self._activate_fallback(str(exc))

    def _activate_fallback(self, reason: str) -> None:
        active = self._active_source
        close_method = getattr(active, "close", None) if active is not None else None
        if callable(close_method):
            close_method()
        print(f"[xplane_remote_relay] falling back to rref mode: {reason}")
        self._active_source = RrefFlightSource(
            self._xp_host,
            self._udp_port,
            self._listen_host,
            self._listen_port,
            self._subscription_hz,
            self._sample_timeout_seconds,
            self._target_altitude_ft,
            self._target_heading_deg,
            self._target_speed_kt,
            self._traffic_slots,
        )
        self._active_mode = "rref"


def run(args: argparse.Namespace) -> None:
    server = BroadcastServer(args.listen_host, args.listen_port)
    hold_controller: WebApiHoldController | None = None
    recovery_controller: WebApiRecoveryController | None = None
    if args.mode == "mock":
        source = MockFlightSource(
            args.target_altitude_ft,
            args.target_speed_kt,
            args.target_heading_deg,
            args.mock_traffic_count,
        )
        closer = None
    elif args.mode == "xpc":
        source = XPlaneConnectSource(
            args.xplane_host,
            args.xplane_port,
            args.target_altitude_ft,
            args.target_heading_deg,
            args.target_speed_kt,
            args.recovery_altitude_ft,
            args.traffic_slots,
        )
        closer = source.close
    elif args.mode == "rref":
        source = RrefFlightSource(
            args.xplane_host,
            args.xplane_udp_port,
            args.rref_listen_host,
            args.rref_listen_port,
            args.rref_frequency_hz,
            args.rref_sample_timeout_seconds,
            args.target_altitude_ft,
            args.target_heading_deg,
            args.target_speed_kt,
            args.traffic_slots,
        )
        closer = source.close
    else:
        source = AutoFlightSource(
            args.xplane_host,
            args.xplane_port,
            args.xplane_udp_port,
            args.rref_listen_host,
            args.rref_listen_port,
            args.rref_frequency_hz,
            args.rref_sample_timeout_seconds,
            args.target_altitude_ft,
            args.target_heading_deg,
            args.target_speed_kt,
            args.recovery_altitude_ft,
            args.traffic_slots,
        )
        closer = source.close

    if args.restart_on_crash and args.webapi_base_url:
        recovery_controller = WebApiRecoveryController(
            base_url=args.webapi_base_url,
            aircraft_path=args.aircraft_path or DEFAULT_AIRCRAFT_PATH,
            confirm_seconds=args.restart_confirm_seconds,
            min_restart_interval_seconds=args.restart_min_interval_seconds,
            grace_seconds=args.restart_grace_seconds,
        )
    if args.webapi_base_url and args.mode in {"rref", "auto"}:
        hold_controller = WebApiHoldController(
            base_url=args.webapi_base_url,
            aircraft_path=args.aircraft_path or DEFAULT_AIRCRAFT_PATH,
            target_altitude_ft=args.target_altitude_ft,
            target_heading_deg=args.target_heading_deg,
            target_speed_kt=args.target_speed_kt,
        )

    period = 1.0 / args.broadcast_hz
    deadline = (
        time.time() + args.duration_seconds if args.duration_seconds > 0 else None
    )

    print(
        f"[xplane_remote_relay] mode={args.mode} listen={args.listen_host}:{args.listen_port} hz={args.broadcast_hz}"
    )
    try:
        while deadline is None or time.time() < deadline:
            started = time.time()
            snapshot = source.next_snapshot()
            if hold_controller is not None:
                snapshot.automation = hold_controller.observe(snapshot)
            server.broadcast(snapshot)
            if recovery_controller is not None:
                recovery_controller.observe(snapshot)
            time.sleep(max(0.0, period - (time.time() - started)))
    finally:
        server.close()
        if closer is not None:
            closer()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Endless X-Plane 12 telemetry relay for remote ingestion"
    )
    parser.add_argument(
        "--mode", choices=("mock", "xpc", "rref", "auto"), default="mock"
    )
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=37211)
    parser.add_argument("--broadcast-hz", type=float, default=5.0)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--target-altitude-ft", type=float, default=12000.0)
    parser.add_argument("--target-heading-deg", type=float, default=90.0)
    parser.add_argument("--target-speed-kt", type=float, default=240.0)
    parser.add_argument("--recovery-altitude-ft", type=float, default=8000.0)
    parser.add_argument("--mock-traffic-count", type=int, default=5)
    parser.add_argument("--xplane-host", default="127.0.0.1")
    parser.add_argument("--xplane-port", type=int, default=49009)
    parser.add_argument("--xplane-udp-port", type=int, default=49000)
    parser.add_argument("--rref-listen-host", default="0.0.0.0")
    parser.add_argument("--rref-listen-port", type=int, default=49004)
    parser.add_argument("--rref-frequency-hz", type=float, default=10.0)
    parser.add_argument("--rref-sample-timeout-seconds", type=float, default=1.25)
    parser.add_argument("--traffic-slots", type=int, default=5)
    parser.add_argument("--webapi-base-url")
    parser.add_argument("--aircraft-path", default=DEFAULT_AIRCRAFT_PATH)
    parser.add_argument("--restart-on-crash", action="store_true")
    parser.add_argument("--restart-confirm-seconds", type=float, default=8.0)
    parser.add_argument("--restart-min-interval-seconds", type=float, default=45.0)
    parser.add_argument("--restart-grace-seconds", type=float, default=25.0)
    return parser


if __name__ == "__main__":
    run(build_arg_parser().parse_args())
