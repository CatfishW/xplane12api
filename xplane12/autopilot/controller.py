from __future__ import annotations

from dataclasses import dataclass
import json
import time
from http.client import HTTPResponse
from typing import TypeAlias, cast
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8086/api/v3"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

DEFAULT_AIRCRAFT_PATH = "Aircraft/Laminar Research/Sikorsky S-76/S-76C.acf"
CENTER_LATITUDE = 33.6407
CENTER_LONGITUDE = -84.4277
ORBIT_RADIUS_DEG = 0.015
ORBIT_CLOCKWISE = True
API_READY_POLL_SECONDS = 5.0
LOAD_SETTLE_SECONDS = 8.0

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class FlightProfile:
    altitude_m: float
    speed_mps: float
    pitch_deg: float
    roll_deg: float = 0.0


DEFAULT_FLIGHT_PROFILE = FlightProfile(
    altitude_m=2800.0,
    speed_mps=90.0,
    pitch_deg=1.0,
)

S76_FLIGHT_PROFILE = FlightProfile(
    altitude_m=2500.0,
    speed_mps=55.0,
    pitch_deg=2.5,
)

R22_FLIGHT_PROFILE = FlightProfile(
    altitude_m=1500.0,
    speed_mps=32.0,
    pitch_deg=4.0,
)


def request_json(method: str, path: str, body: JSONValue | None = None, *, base_url: str = BASE_URL) -> JSONValue:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        data=payload,
        headers=HEADERS,
    )
    with cast(HTTPResponse, urlopen(request, timeout=30)) as response:
        raw = response.read()
    if not raw:
        return None
    return cast(JSONValue, json.loads(raw.decode("utf-8")))


def wait_for_api_ready(*, base_url: str = BASE_URL) -> None:
    while True:
        try:
            _ = request_json("GET", "/datarefs/count", base_url=base_url)
            print("[xplane12_web_autoflight] api_ready", flush=True)
            return
        except Exception as error:
            print(f"[xplane12_web_autoflight] waiting_for_api_ready error={error}", flush=True)
            time.sleep(API_READY_POLL_SECONDS)


def build_initial_air_start() -> tuple[float, float, float]:
    latitude = CENTER_LATITUDE + ORBIT_RADIUS_DEG
    longitude = CENTER_LONGITUDE
    heading_deg = 90.0 if ORBIT_CLOCKWISE else 270.0
    return latitude, longitude, heading_deg


def aircraft_profile_for_path(aircraft_path: str) -> FlightProfile:
    normalized = aircraft_path.casefold()
    if "sikorsky s-76" in normalized:
        return S76_FLIGHT_PROFILE
    if "robinson r22" in normalized:
        return R22_FLIGHT_PROFILE
    return DEFAULT_FLIGHT_PROFILE


def build_air_start_payload(*, aircraft_path: str = DEFAULT_AIRCRAFT_PATH) -> dict[str, JSONValue]:
    latitude, longitude, heading_deg = build_initial_air_start()
    profile = aircraft_profile_for_path(aircraft_path)
    return {
        "aircraft": {"path": aircraft_path},
        "lle_air_start": {
            "latitude": latitude,
            "longitude": longitude,
            "elevation_in_meters": profile.altitude_m,
            "heading_true": heading_deg,
            "speed_in_meters_per_second": profile.speed_mps,
            "pitch_in_degrees": profile.pitch_deg,
            "roll_in_degrees": profile.roll_deg,
        },
        "engine_status": {"all_engines": {"running": True}},
    }


def start_air_session_once(*, base_url: str = BASE_URL, aircraft_path: str = DEFAULT_AIRCRAFT_PATH) -> None:
    payload = build_air_start_payload(aircraft_path=aircraft_path)
    _ = request_json("POST", "/flight", payload, base_url=base_url)
    time.sleep(LOAD_SETTLE_SECONDS)
    lle_air_start = payload["lle_air_start"]
    print(
        "[xplane12_web_autoflight] air_start "
        f"aircraft={payload['aircraft']['path']} "
        f"lat={float(lle_air_start['latitude']):.6f} "
        f"lon={float(lle_air_start['longitude']):.6f} "
        f"heading={float(lle_air_start['heading_true']):.1f} "
        f"alt_m={float(lle_air_start['elevation_in_meters']):.1f} "
        f"speed_mps={float(lle_air_start['speed_in_meters_per_second']):.1f}",
        flush=True,
    )
