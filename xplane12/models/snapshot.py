from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


CATEGORY_NAMES = ("aircraft", "weather", "systems", "traffic")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OwnshipState:
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float = 0.0
    altitude_agl_m: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    heading_deg: float = 0.0
    track_deg: float = 0.0
    flight_path_angle_deg: float = 0.0
    slip_skid: float = 0.0
    indicated_airspeed_kt: float = 0.0
    true_airspeed_kt: float = 0.0
    ground_speed_kt: float = 0.0
    vertical_speed_fpm: float = 0.0
    autopilot_engaged: bool = False
    autopilot_mode: int = 0
    gear_down: bool = False
    on_ground: bool = False
    gps_valid: bool = False
    ils_valid: bool = False
    throttle_ratio: float = 0.0
    elevator_input: float = 0.0
    aileron_input: float = 0.0
    rudder_input: float = 0.0
    flaps_ratio: float = 0.0
    speedbrake_ratio: float = 0.0
    parking_brake_ratio: float = 0.0


WEATHER_LAYER_COUNT = 3


@dataclass
class CloudLayer:
    coverage_percent: float = 0.0
    base_msl_m: float = 0.0
    tops_msl_m: float = 0.0
    cloud_type: int = 0
    precipitation_ratio: float = 0.0
    turbulence_ratio: float = 0.0


@dataclass
class WeatherState:
    wind_speed_kt: float = 0.0
    wind_direction_deg: float = 0.0
    barometer_inhg: float = 29.92
    temperature_c: float = 15.0
    visibility_m: float = 0.0
    cloud_base_m: float = 0.0
    precipitation_on_aircraft_ratio: float = 0.0
    cloud_layers: list[CloudLayer] = field(default_factory=lambda: [CloudLayer() for _ in range(WEATHER_LAYER_COUNT)])


@dataclass
class TrafficTarget:
    icao24: str = ""
    callsign: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float = 0.0
    heading_deg: float = 0.0
    velocity_mps: float = 0.0
    vertical_rate_mps: float = 0.0
    on_ground: bool = False
    source: str = ""
    range_nm: float | None = None
    bearing_deg: float | None = None
    age_seconds: float | None = None
    confidence: float | None = None
    relative_altitude_ft: float | None = None
    flight_level: str | None = None


@dataclass
class AutomationState:
    controller: str = ""
    mode: str = ""
    recovery_active: bool = False
    target_altitude_m: float = 0.0
    target_heading_deg: float = 0.0
    target_speed_kt: float = 0.0


@dataclass
class HealthState:
    status: str = "degraded"
    last_error: str = ""
    last_update_utc: str = ""
    last_packet_age_sec: float | None = None


@dataclass
class CapabilityState:
    weather: list[str] = field(default_factory=list)
    traffic: list[str] = field(default_factory=list)
    autopilot: list[str] = field(default_factory=list)
    api: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    timestamp_utc: str
    source_mode: str
    health: HealthState
    ownship: OwnshipState = field(default_factory=OwnshipState)
    weather: WeatherState = field(default_factory=WeatherState)
    traffic: list[TrafficTarget] = field(default_factory=list)
    automation: AutomationState | None = None
    raw: dict[str, float] = field(default_factory=dict)
    capabilities: CapabilityState = field(default_factory=CapabilityState)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_unity_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("health", None)
        payload.pop("capabilities", None)
        return payload


def default_snapshot(*, source_mode: str = "webapi") -> Snapshot:
    return Snapshot(
        timestamp_utc=utc_now_iso(),
        source_mode=source_mode,
        health=HealthState(last_update_utc=utc_now_iso()),
    )