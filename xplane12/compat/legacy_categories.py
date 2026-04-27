from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Subscription:
    index: int
    category: str
    dataref: str


AIRCRAFT_REFS = [
    "sim/flightmodel/position/theta",
    "sim/flightmodel/position/phi",
    "sim/flightmodel/position/psi",
    "sim/flightmodel/position/mag_psi",
    "sim/flightmodel/position/indicated_airspeed",
    "sim/flightmodel/position/true_airspeed",
    "sim/flightmodel/position/groundspeed",
    "sim/flightmodel/position/latitude",
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/elevation",
    "sim/flightmodel/position/y_agl",
    "sim/flightmodel/position/vh_ind",
    "sim/flightmodel/position/P",
    "sim/flightmodel/position/Q",
    "sim/flightmodel/position/R",
    "sim/flightmodel/position/local_vx",
    "sim/flightmodel/position/local_vy",
    "sim/flightmodel/position/local_vz",
    "sim/flightmodel/forces/g_nrml",
    "sim/flightmodel/forces/g_axil",
    "sim/flightmodel/forces/g_side",
]

WEATHER_REFS = [
    # Wind at aircraft
    "sim/weather/aircraft/wind_now_speed_msc",
    "sim/weather/aircraft/wind_now_direction_degt",
    "sim/weather/aircraft/wind_speed_kts[0]",
    "sim/weather/aircraft/wind_direction_degt[0]",
    "sim/weather/aircraft/temperature_ambient_deg_c",
    "sim/weather/aircraft/qnh_pas",
    "sim/weather/aircraft/barometer_current_pas",
    "sim/weather/aircraft/visibility_reported_sm",
    "sim/weather/aircraft/precipitation_on_aircraft_ratio",
    # Cloud layer 0 (lowest)
    "sim/weather/aircraft/cloud_base_msl_m[0]",
    "sim/weather/aircraft/cloud_tops_msl_m[0]",
    "sim/weather/aircraft/cloud_coverage_percent[0]",
    "sim/weather/aircraft/cloud_type[0]",
    "sim/weather/aircraft/precipitation_ratio[0]",
    "sim/weather/aircraft/turbulence_ratio[0]",
    # Cloud layer 1
    "sim/weather/aircraft/cloud_base_msl_m[1]",
    "sim/weather/aircraft/cloud_tops_msl_m[1]",
    "sim/weather/aircraft/cloud_coverage_percent[1]",
    "sim/weather/aircraft/cloud_type[1]",
    "sim/weather/aircraft/precipitation_ratio[1]",
    "sim/weather/aircraft/turbulence_ratio[1]",
    # Cloud layer 2
    "sim/weather/aircraft/cloud_base_msl_m[2]",
    "sim/weather/aircraft/cloud_tops_msl_m[2]",
    "sim/weather/aircraft/cloud_coverage_percent[2]",
    "sim/weather/aircraft/cloud_type[2]",
    "sim/weather/aircraft/precipitation_ratio[2]",
    "sim/weather/aircraft/turbulence_ratio[2]",
    # Global weather
    "sim/weather/wind_speed_kt[0]",
    "sim/weather/wind_direction_degt[0]",
    "sim/weather/barometer_sealevel_inhg",
    "sim/weather/temperature_ambient_c",
    "sim/weather/visibility_reported_m",
    "sim/weather/cloud_base_msl_m[0]",
    "sim/weather/cloud_tops_msl_m[0]",
    "sim/weather/cloud_coverage_percent[0]",
]

SYSTEM_REFS = [
    "sim/cockpit/autopilot/autopilot_mode",
    "sim/cockpit/autopilot/autopilot_state",
    "sim/cockpit/autopilot/heading_mag",
    "sim/cockpit/autopilot/altitude",
    "sim/cockpit/autopilot/vertical_velocity",
    "sim/cockpit/autopilot/airspeed",
    "sim/cockpit2/autopilot/heading_dial_deg_mag_pilot",
    "sim/cockpit2/autopilot/altitude_dial_ft",
    "sim/cockpit2/autopilot/vvi_dial_fpm",
    "sim/cockpit2/autopilot/airspeed_dial_kts",
    "sim/cockpit2/autopilot/flight_director_mode",
    "sim/cockpit2/autopilot/heading_status",
    "sim/cockpit2/autopilot/nav_status",
    "sim/cockpit2/autopilot/altitude_hold_status",
    "sim/cockpit2/annunciators/master_warning",
    "sim/cockpit2/annunciators/master_caution",
    "sim/time/total_running_time_sec",
    "sim/time/zulu_time_sec",
]

TRAFFIC_SUFFIXES = [
    "lat",
    "lon",
    "el",
    "psi",
    "the",
    "phi",
    "v_x",
    "v_y",
    "v_z",
    "gear_deploy[0]",
    "flap_ratio",
    "speedbrake_ratio",
]

TCAS_TEMPLATES = [
    "sim/cockpit2/tcas/targets/modeS_id[{slot}]",
    "sim/cockpit2/tcas/targets/relative_distance_m[{slot}]",
    "sim/cockpit2/tcas/targets/relative_bearing_degt[{slot}]",
    "sim/cockpit2/tcas/targets/altitude_ft[{slot}]",
    "sim/cockpit2/tcas/targets/vertical_speed_fpm[{slot}]",
    "sim/cockpit2/tcas/targets/position/lat[{slot}]",
    "sim/cockpit2/tcas/targets/position/lon[{slot}]",
    "sim/cockpit2/tcas/targets/position/ele[{slot}]",
    "sim/cockpit2/tcas/targets/position/vx[{slot}]",
    "sim/cockpit2/tcas/targets/position/vy[{slot}]",
    "sim/cockpit2/tcas/targets/position/vz[{slot}]",
    "sim/cockpit2/tcas/targets/position/psi[{slot}]",
    "sim/cockpit2/tcas/targets/position/gear_deploy[{slot}]",
    "sim/cockpit2/tcas/targets/flight_level[{slot}]",
    "sim/cockpit2/tcas/targets/relative_altitude_ft[{slot}]",
    "sim/cockpit2/tcas/targets/horizontal_velocity_mps[{slot}]",
]


def build_subscriptions() -> list[Subscription]:
    refs: list[tuple[str, str]] = []
    refs.extend(("aircraft", ref) for ref in AIRCRAFT_REFS)
    refs.extend(("weather", ref) for ref in WEATHER_REFS)
    refs.extend(("systems", ref) for ref in SYSTEM_REFS)

    for plane_index in range(1, 20):
        for suffix in TRAFFIC_SUFFIXES:
            refs.append(("traffic", f"sim/multiplayer/position/plane{plane_index}_{suffix}"))

    for slot in range(8):
        for template in TCAS_TEMPLATES:
            refs.append(("traffic", template.format(slot=slot)))

    return [
        Subscription(index=index, category=category, dataref=dataref)
        for index, (category, dataref) in enumerate(refs, start=2000)
    ]


def category_members(subscriptions: list[Subscription]) -> dict[str, set[str]]:
    return {
        category: {subscription.dataref for subscription in subscriptions if subscription.category == category}
        for category in {subscription.category for subscription in subscriptions}
    }