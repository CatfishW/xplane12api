from __future__ import annotations

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
AIR_START_ALTITUDE_M = 2800.0
AIR_START_SPEED_MPS = 90.0
ORBIT_RADIUS_DEG = 0.015
ORBIT_CLOCKWISE = True
API_READY_POLL_SECONDS = 5.0
LOAD_SETTLE_SECONDS = 8.0

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


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


def build_air_start_payload(*, aircraft_path: str = DEFAULT_AIRCRAFT_PATH) -> dict[str, JSONValue]:
    latitude, longitude, heading_deg = build_initial_air_start()
    return {
        "aircraft": {"path": aircraft_path},
        "lle_air_start": {
            "latitude": latitude,
            "longitude": longitude,
            "elevation_in_meters": AIR_START_ALTITUDE_M,
            "heading_true": heading_deg,
            "speed_in_meters_per_second": AIR_START_SPEED_MPS,
            "pitch_in_degrees": 1.0,
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
        f"heading={float(lle_air_start['heading_true']):.1f}",
        flush=True,
    )
