from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from xplane12.compat import Subscription, build_subscriptions, category_members
from xplane12.models import (
    AutomationState,
    CapabilityState,
    CloudLayer,
    HealthState,
    OwnshipState,
    Snapshot,
    TrafficTarget,
    WeatherState,
    WEATHER_LAYER_COUNT,
    utc_now_iso,
)


@dataclass
class BridgeState:
    values: dict[str, float]
    last_packet_ts: float
    last_sender: str
    rx_packets: int
    rx_pairs: int
    last_error: str


class XPlaneState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._last_packet_ts: float = 0.0
        self._last_sender: str = ""
        self._rx_packets: int = 0
        self._rx_pairs: int = 0
        self._last_error: str = ""

    def update_values(self, updates: dict[str, float], sender: str) -> None:
        now = time.time()
        with self._lock:
            self._values.update(updates)
            self._last_packet_ts = now
            self._last_sender = sender
            self._rx_packets += 1
            self._rx_pairs += len(updates)

    def set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

    def snapshot(self) -> BridgeState:
        with self._lock:
            return BridgeState(
                values=dict(self._values),
                last_packet_ts=self._last_packet_ts,
                last_sender=self._last_sender,
                rx_packets=self._rx_packets,
                rx_pairs=self._rx_pairs,
                last_error=self._last_error,
            )


class XPlaneWebApiClient:
    def __init__(
        self,
        state: XPlaneState,
        subscriptions: list[Subscription],
        base_url: str = "http://127.0.0.1:8086/api/v3",
        poll_seconds: float = 2.0,
        resolve_retry_seconds: float = 30.0,
        max_workers: int = 8,
    ) -> None:
        self.state = state
        self.subscriptions = subscriptions
        self.base_url = base_url.rstrip("/")
        self.poll_seconds = poll_seconds
        self.resolve_retry_seconds = resolve_retry_seconds
        self.running = False
        self.poll_thread: threading.Thread | None = None
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.resolved_ids: dict[str, int] = {}
        self.unresolved_datarefs: set[str] = set()
        self.cooldown_until: float = 0.0
        self._catalog_loaded = False
        self._dataref_catalog: dict[str, int] = {}

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def stop(self) -> None:
        self.running = False
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _request_json(self, path: str, timeout: float = 10.0) -> Any:
        request = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
        if not payload:
            return None
        return json.loads(payload.decode("utf-8"))

    def _resolve_subscription(self, dataref: str) -> tuple[str, int | None]:
        payload = self._request_json(
            f"/datarefs?limit=1&filter[name]={quote(dataref, safe='')}",
            timeout=10.0,
        )
        items = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return dataref, None
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("name") != dataref:
                continue
            identifier = item.get("id")
            if isinstance(identifier, int):
                return dataref, identifier
        return dataref, None

    def _load_dataref_catalog(self) -> bool:
        payload = self._request_json("/datarefs?limit=10000", timeout=20.0)
        items = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return False

        catalog: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            identifier = item.get("id")
            if isinstance(name, str) and isinstance(identifier, int):
                catalog[name] = identifier
        if not catalog:
            return False

        self._dataref_catalog = catalog
        self._catalog_loaded = True
        return True

    def _coerce_numeric(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, list) and len(value) == 1:
            return self._coerce_numeric(value[0])
        return None

    def _read_value(self, dataref: str, identifier: int) -> tuple[str, float | None, bool]:
        payload = self._request_json(f"/datarefs/{identifier}/value", timeout=5.0)
        raw_value = payload.get("data") if isinstance(payload, dict) else payload
        return dataref, self._coerce_numeric(raw_value), False

    def _resolve_all_subscriptions(self) -> None:
        if time.time() < self.cooldown_until:
            return
        known_datarefs = sorted({subscription.dataref for subscription in self.subscriptions})
        pending = [dataref for dataref in known_datarefs if dataref not in self.resolved_ids]
        if not pending:
            return

        first_error: str | None = None
        if not self._catalog_loaded:
            try:
                self._load_dataref_catalog()
            except Exception as error:
                first_error = f"catalog_error:{type(error).__name__}:{error}"
        if self._catalog_loaded:
            for dataref in pending:
                identifier = self._dataref_catalog.get(dataref)
                if identifier is None:
                    self.unresolved_datarefs.add(dataref)
                    continue
                self.resolved_ids[dataref] = identifier
                self.unresolved_datarefs.discard(dataref)
            if self.resolved_ids:
                self.state.set_error(first_error or "")
                return

        futures: dict[Future[tuple[str, int | None]], str] = {
            self.executor.submit(self._resolve_subscription, dataref): dataref for dataref in pending
        }
        timed_out = False
        for future in as_completed(futures):
            dataref = futures[future]
            try:
                resolved_dataref, identifier = future.result()
            except Exception as error:
                self.unresolved_datarefs.add(dataref)
                if isinstance(error, (TimeoutError, URLError)):
                    timed_out = True
                if first_error is None:
                    first_error = f"resolve_error:{type(error).__name__}:{error}"
                continue
            if identifier is None:
                self.unresolved_datarefs.add(resolved_dataref)
                continue
            self.resolved_ids[resolved_dataref] = identifier
            self.unresolved_datarefs.discard(resolved_dataref)

        if timed_out:
            self.cooldown_until = time.time() + self.resolve_retry_seconds

        if self.resolved_ids:
            self.state.set_error(first_error or "")
            return
        self.state.set_error(first_error or "no_supported_datarefs")

    def _poll_once(self) -> None:
        if not self.resolved_ids:
            self.state.set_error("no_supported_datarefs")
            return

        updates: dict[str, float] = {}
        stale_datarefs: list[str] = []
        first_error: str | None = None
        futures: dict[Future[tuple[str, float | None, bool]], str] = {
            self.executor.submit(self._read_value, dataref, identifier): dataref
            for dataref, identifier in list(self.resolved_ids.items())
        }
        timed_out = False
        for future in as_completed(futures):
            dataref = futures[future]
            try:
                resolved_dataref, value, _ = future.result()
            except HTTPError as error:
                if error.code == 404:
                    stale_datarefs.append(dataref)
                    continue
                if first_error is None:
                    first_error = f"poll_error:{type(error).__name__}:{error}"
                continue
            except Exception as error:
                if isinstance(error, (TimeoutError, URLError)):
                    timed_out = True
                if first_error is None:
                    first_error = f"poll_error:{type(error).__name__}:{error}"
                continue
            if value is not None:
                updates[resolved_dataref] = value

        for dataref in stale_datarefs:
            self.resolved_ids.pop(dataref, None)
            self.unresolved_datarefs.add(dataref)

        if timed_out:
            self.cooldown_until = time.time() + self.poll_seconds * 2

        if updates:
            self.state.update_values(updates, "webapi")
            self.state.set_error(first_error or "")
            return
        if not self.resolved_ids:
            self.state.set_error("no_supported_datarefs")
            return
        self.state.set_error(first_error or "poll_no_values")

    def _poll_loop(self) -> None:
        last_resolve = 0.0
        while self.running:
            now = time.time()
            if now - last_resolve >= self.resolve_retry_seconds or not self.resolved_ids:
                self._resolve_all_subscriptions()
                last_resolve = now
            try:
                self._poll_once()
            except Exception as error:
                self.state.set_error(f"poll_error:{type(error).__name__}:{error}")
            slept = 0.0
            while self.running and slept < self.poll_seconds:
                time.sleep(0.1)
                slept += 0.1


def compute_range_and_bearing_nm(
    own_lat: float,
    own_lon: float,
    target_lat: float,
    target_lon: float,
) -> tuple[float | None, float | None]:
    if (
        abs(own_lat) < 0.0001
        and abs(own_lon) < 0.0001
        and abs(target_lat) < 0.0001
        and abs(target_lon) < 0.0001
    ):
        return None, None
    lat1 = math.radians(own_lat)
    lat2 = math.radians(target_lat)
    d_lat = lat2 - lat1
    d_lon = math.radians(target_lon - own_lon)
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    range_nm = 3440.065 * c
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return range_nm, bearing


class SnapshotAdapter:
    def __init__(self, state: XPlaneState, subscriptions: list[Subscription]) -> None:
        self.state = state
        self.subscriptions = subscriptions
        self.category_members = category_members(subscriptions)

    def state_snapshot(self) -> BridgeState:
        return self.state.snapshot()

    def category_values(self, category: str | None = None) -> dict[str, float]:
        snapshot = self.state.snapshot()
        if category is None:
            return snapshot.values
        allowed = self.category_members.get(category, set())
        return {key: value for key, value in snapshot.values.items() if key in allowed}

    def health_payload(self) -> dict[str, Any]:
        snapshot = self.state.snapshot()
        age: float | None = None
        if snapshot.last_packet_ts > 0:
            age = time.time() - float(snapshot.last_packet_ts)
        status = "ok" if age is not None and age < 10 else "degraded"
        return {
            "status": status,
            "last_packet_age_sec": age,
            "last_sender": snapshot.last_sender,
            "rx_packets": snapshot.rx_packets,
            "rx_pairs": snapshot.rx_pairs,
            "subscription_count": len(self.subscriptions),
            "last_error": snapshot.last_error,
        }

    def canonical_snapshot(self) -> Snapshot:
        bridge = self.state.snapshot()
        health_data = self.health_payload()
        values = bridge.values
        ownship = OwnshipState(
            latitude=values.get("sim/flightmodel/position/latitude", 0.0),
            longitude=values.get("sim/flightmodel/position/longitude", 0.0),
            altitude_m=values.get("sim/flightmodel/position/elevation", 0.0),
            altitude_agl_m=values.get("sim/flightmodel/position/y_agl", 0.0),
            pitch_deg=values.get("sim/flightmodel/position/theta", 0.0),
            roll_deg=values.get("sim/flightmodel/position/phi", 0.0),
            heading_deg=values.get("sim/flightmodel/position/psi", 0.0),
            track_deg=values.get("sim/flightmodel/position/psi", 0.0),
            indicated_airspeed_kt=values.get("sim/flightmodel/position/indicated_airspeed", 0.0),
            true_airspeed_kt=values.get("sim/flightmodel/position/true_airspeed", 0.0),
            ground_speed_kt=values.get("sim/flightmodel/position/groundspeed", 0.0),
            vertical_speed_fpm=values.get("sim/flightmodel/position/local_vz", 0.0) * 196.8504,
            autopilot_engaged=values.get("sim/cockpit/autopilot/autopilot_state", 0.0) > 0,
            autopilot_mode=int(values.get("sim/cockpit/autopilot/autopilot_mode", 0.0)),
        )
        cloud_layers = [
            CloudLayer(
                coverage_percent=values.get(f"sim/weather/aircraft/cloud_coverage_percent[{i}]", 0.0),
                base_msl_m=values.get(f"sim/weather/aircraft/cloud_base_msl_m[{i}]", 0.0),
                tops_msl_m=values.get(f"sim/weather/aircraft/cloud_tops_msl_m[{i}]", 0.0),
                cloud_type=int(values.get(f"sim/weather/aircraft/cloud_type[{i}]", 0.0)),
                precipitation_ratio=values.get(f"sim/weather/aircraft/precipitation_ratio[{i}]", 0.0),
                turbulence_ratio=values.get(f"sim/weather/aircraft/turbulence_ratio[{i}]", 0.0),
            )
            for i in range(WEATHER_LAYER_COUNT)
        ]
        weather = WeatherState(
            wind_speed_kt=values.get("sim/weather/aircraft/wind_speed_kts[0]", 0.0),
            wind_direction_deg=values.get("sim/weather/aircraft/wind_direction_degt[0]", 0.0),
            barometer_inhg=values.get("sim/weather/aircraft/barometer_current_pas", 0.0) * 0.0002953,
            temperature_c=values.get("sim/weather/aircraft/temperature_ambient_deg_c", 0.0),
            visibility_m=values.get("sim/weather/aircraft/visibility_reported_sm", 0.0) * 1609.344,
            cloud_base_m=values.get("sim/weather/aircraft/cloud_base_msl_m[0]", 0.0),
            precipitation_on_aircraft_ratio=values.get("sim/weather/aircraft/precipitation_on_aircraft_ratio", 0.0),
            cloud_layers=cloud_layers,
        )
        traffic = self._build_traffic(values, ownship.latitude, ownship.longitude, ownship.heading_deg)
        automation = AutomationState(
            controller="xp12-webapi",
            mode="observe",
            recovery_active=False,
            target_altitude_m=values.get("sim/cockpit2/autopilot/altitude_dial_ft", 0.0) * 0.3048,
            target_heading_deg=values.get("sim/cockpit2/autopilot/heading_dial_deg_mag_pilot", 0.0),
            target_speed_kt=values.get("sim/cockpit2/autopilot/airspeed_dial_kts", 0.0),
        )
        return Snapshot(
            timestamp_utc=utc_now_iso(),
            source_mode=bridge.last_sender or "webapi",
            health=HealthState(
                status=health_data["status"],
                last_error=bridge.last_error,
                last_update_utc=utc_now_iso(),
                last_packet_age_sec=health_data["last_packet_age_sec"],
            ),
            ownship=ownship,
            weather=weather,
            traffic=traffic,
            automation=automation,
            raw=values,
            capabilities=CapabilityState(
                weather=["wind", "visibility", "clouds", "precipitation-derived"],
                traffic=["multiplayer", "tcas", "relative-bearing"],
                autopilot=["observe"],
                api=["health", "legacy-data", "snapshot", "unity-ndjson"],
            ),
        )

    def _build_traffic(
        self,
        values: dict[str, float],
        own_lat: float,
        own_lon: float,
        own_heading_deg: float,
    ) -> list[TrafficTarget]:
        targets: list[TrafficTarget] = []
        for plane_index in range(1, 20):
            lat = values.get(f"sim/multiplayer/position/plane{plane_index}_lat", 0.0)
            lon = values.get(f"sim/multiplayer/position/plane{plane_index}_lon", 0.0)
            alt = values.get(f"sim/multiplayer/position/plane{plane_index}_el", 0.0)
            heading = values.get(f"sim/multiplayer/position/plane{plane_index}_psi", 0.0)
            vx = values.get(f"sim/multiplayer/position/plane{plane_index}_v_x", 0.0)
            vy = values.get(f"sim/multiplayer/position/plane{plane_index}_v_y", 0.0)
            vz = values.get(f"sim/multiplayer/position/plane{plane_index}_v_z", 0.0)
            if abs(lat) < 0.0001 and abs(lon) < 0.0001 and abs(alt) < 1.0 and abs(heading) < 0.1:
                continue
            range_nm, bearing_deg = compute_range_and_bearing_nm(own_lat, own_lon, lat, lon)
            targets.append(
                TrafficTarget(
                    icao24=f"plane{plane_index:02d}",
                    callsign=f"AC-{plane_index:02d}",
                    latitude=lat,
                    longitude=lon,
                    altitude_m=alt,
                    heading_deg=heading,
                    velocity_mps=(vx * vx + vy * vy + vz * vz) ** 0.5,
                    vertical_rate_mps=vz,
                    on_ground=alt < 3.0,
                    source="multiplayer",
                    range_nm=range_nm,
                    bearing_deg=bearing_deg,
                    confidence=1.0,
                    relative_altitude_ft=None,
                    flight_level=None,
                )
            )
        for slot in range(8):
            mode_s = values.get(f"sim/cockpit2/tcas/targets/modeS_id[{slot}]", 0.0)
            rel_distance_m = values.get(f"sim/cockpit2/tcas/targets/relative_distance_m[{slot}]", 0.0)
            rel_bearing_deg = values.get(f"sim/cockpit2/tcas/targets/relative_bearing_degt[{slot}]", 0.0)
            alt_ft = values.get(f"sim/cockpit2/tcas/targets/altitude_ft[{slot}]", 0.0)
            rel_alt_ft = values.get(f"sim/cockpit2/tcas/targets/relative_altitude_ft[{slot}]", 0.0)
            flight_level_val = values.get(f"sim/cockpit2/tcas/targets/flight_level[{slot}]", 0.0)
            vs_fpm = values.get(f"sim/cockpit2/tcas/targets/vertical_speed_fpm[{slot}]", 0.0)
            hvel_mps = values.get(f"sim/cockpit2/tcas/targets/horizontal_velocity_mps[{slot}]", 0.0)
            lat = values.get(f"sim/cockpit2/tcas/targets/position/lat[{slot}]", 0.0)
            lon = values.get(f"sim/cockpit2/tcas/targets/position/lon[{slot}]", 0.0)
            ele = values.get(f"sim/cockpit2/tcas/targets/position/ele[{slot}]", 0.0)
            vx = values.get(f"sim/cockpit2/tcas/targets/position/vx[{slot}]", 0.0)
            vy = values.get(f"sim/cockpit2/tcas/targets/position/vy[{slot}]", 0.0)
            vz = values.get(f"sim/cockpit2/tcas/targets/position/vz[{slot}]", 0.0)
            psi = values.get(f"sim/cockpit2/tcas/targets/position/psi[{slot}]", 0.0)
            has_position = abs(lat) > 0.0001 or abs(lon) > 0.0001 or abs(ele) > 1.0
            has_relative = abs(rel_distance_m) > 1.0 or abs(rel_bearing_deg) > 0.1
            if abs(mode_s) <= 0.5 and not has_position and not has_relative and abs(alt_ft) <= 1.0:
                continue
            range_nm = None
            bearing_deg = None
            altitude_m = ele
            if has_position:
                range_nm, bearing_deg = compute_range_and_bearing_nm(own_lat, own_lon, lat, lon)
            elif has_relative:
                range_nm = rel_distance_m / 1852.0
                bearing_deg = (own_heading_deg + rel_bearing_deg + 360.0) % 360.0
                altitude_m = alt_ft * 0.3048
            fl_str = None
            if abs(flight_level_val) > 0.5:
                fl_int = int(round(flight_level_val / 100.0))
                fl_str = f"FL{fl_int:03d}"
            targets.append(
                TrafficTarget(
                    icao24=(f"{int(mode_s):06X}" if abs(mode_s) > 0.5 else f"tcas{slot:02d}"),
                    callsign=(f"TCAS-{int(mode_s):X}" if abs(mode_s) > 0.5 else f"TCAS-{slot}"),
                    latitude=lat,
                    longitude=lon,
                    altitude_m=altitude_m,
                    heading_deg=psi if abs(psi) > 0.1 else rel_bearing_deg,
                    velocity_mps=hvel_mps if abs(hvel_mps) > 0.1 else (vx * vx + vy * vy + vz * vz) ** 0.5,
                    vertical_rate_mps=vs_fpm / 196.8504 if abs(vs_fpm) > 0.5 else vz,
                    on_ground=altitude_m < 3.0,
                    source="tcas",
                    range_nm=range_nm,
                    bearing_deg=bearing_deg,
                    confidence=0.6 if has_position else 0.35,
                    relative_altitude_ft=rel_alt_ft if abs(rel_alt_ft) > 0.5 else None,
                    flight_level=fl_str,
                )
            )
        return targets


def create_runtime(*, base_url: str = "http://127.0.0.1:8086/api/v3") -> tuple[XPlaneState, list[Subscription], XPlaneWebApiClient, SnapshotAdapter]:
    state = XPlaneState()
    subscriptions = build_subscriptions()
    client = XPlaneWebApiClient(state=state, subscriptions=subscriptions, base_url=base_url)
    adapter = SnapshotAdapter(state=state, subscriptions=subscriptions)
    return state, subscriptions, client, adapter
