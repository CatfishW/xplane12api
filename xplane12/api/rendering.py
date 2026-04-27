from __future__ import annotations

import html
import math
from typing import Iterable

from xplane12.models import Snapshot, TrafficTarget


SVG_NS = "http://www.w3.org/2000/svg"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _polar(origin_x: float, origin_y: float, angle_deg: float, distance: float) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return origin_x + math.sin(radians) * distance, origin_y - math.cos(radians) * distance


def _arc_path(cx: float, cy: float, radius: float, start_deg: float, end_deg: float) -> str:
    start = _polar(cx, cy, start_deg, radius)
    end = _polar(cx, cy, end_deg, radius)
    large_arc = 1 if abs(end_deg - start_deg) > 180 else 0
    sweep = 1 if end_deg > start_deg else 0
    return (
        f"M {_fmt(start[0])} {_fmt(start[1])} "
        f"A {_fmt(radius)} {_fmt(radius)} 0 {large_arc} {sweep} {_fmt(end[0])} {_fmt(end[1])}"
    )


def _sector_path(cx: float, cy: float, inner_radius: float, outer_radius: float, start_deg: float, end_deg: float) -> str:
    outer_start = _polar(cx, cy, start_deg, outer_radius)
    outer_end = _polar(cx, cy, end_deg, outer_radius)
    inner_end = _polar(cx, cy, end_deg, inner_radius)
    inner_start = _polar(cx, cy, start_deg, inner_radius)
    large_arc = 1 if abs(end_deg - start_deg) > 180 else 0
    return (
        f"M {_fmt(outer_start[0])} {_fmt(outer_start[1])} "
        f"A {_fmt(outer_radius)} {_fmt(outer_radius)} 0 {large_arc} 1 {_fmt(outer_end[0])} {_fmt(outer_end[1])} "
        f"L {_fmt(inner_end[0])} {_fmt(inner_end[1])} "
        f"A {_fmt(inner_radius)} {_fmt(inner_radius)} 0 {large_arc} 0 {_fmt(inner_start[0])} {_fmt(inner_start[1])} Z"
    )


def _seeded_unit(seed: float) -> float:
    return math.sin(seed * 12.9898 + 78.233) * 43758.5453 % 1.0


def _svg_root(width: int, height: int, body: Iterable[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">',
            *body,
            "</svg>",
        ]
    )


def render_weather_svg(snapshot: Snapshot, *, width: int = 700, height: int = 700) -> str:
    weather = snapshot.weather
    ownship = snapshot.ownship
    origin_x = width / 2
    origin_y = height - 92
    max_radius = min(width * 0.39, height * 0.63)
    start_deg = -34
    end_deg = 34
    cells: list[str] = []
    intensity_scale = _clamp(
        (weather.precipitation_on_aircraft_ratio * 0.9)
        + sum(layer.precipitation_ratio + layer.turbulence_ratio for layer in weather.cloud_layers) * 0.22
        + sum(layer.coverage_percent for layer in weather.cloud_layers) / 300.0,
        0.08,
        1.0,
    )
    for index, layer in enumerate(weather.cloud_layers):
        layer_strength = _clamp(
            layer.coverage_percent / 100.0 + layer.precipitation_ratio * 0.8 + layer.turbulence_ratio * 0.45,
            0.0,
            1.6,
        )
        if layer_strength <= 0.05:
            continue
        band_inner = max_radius * (0.18 + index * 0.18)
        band_outer = min(max_radius * (0.43 + index * 0.22 + layer_strength * 0.08), max_radius)
        cell_count = 2 + index + int(layer.coverage_percent >= 60)
        for cell_index in range(cell_count):
            seed = (
                (index + 1) * 101.0
                + (cell_index + 1) * 17.0
                + weather.wind_direction_deg * 0.13
                + weather.wind_speed_kt * 0.31
                + layer.base_msl_m * 0.0007
                + layer.tops_msl_m * 0.0003
            )
            center_angle = start_deg + (end_deg - start_deg) * _seeded_unit(seed)
            spread = 8 + 16 * _seeded_unit(seed + 3.0) * _clamp(layer_strength, 0.2, 1.0)
            center_radius = band_inner + (band_outer - band_inner) * _seeded_unit(seed + 11.0)
            thickness = 20 + 55 * _seeded_unit(seed + 19.0) * intensity_scale
            path = _sector_path(
                origin_x,
                origin_y,
                max(36.0, center_radius - thickness * 0.55),
                min(max_radius, center_radius + thickness),
                center_angle - spread * 0.8,
                center_angle + spread,
            )
            cell_intensity = _clamp(layer_strength * (0.7 + 0.6 * _seeded_unit(seed + 27.0)), 0.0, 1.5)
            color = "#32d74b"
            if cell_intensity >= 1.1:
                color = "#f44747"
            elif cell_intensity >= 0.82:
                color = "#ffd84d"
            elif cell_intensity >= 0.62:
                color = "#7dff6a"
            opacity = _clamp(0.28 + cell_intensity * 0.34, 0.22, 0.85)
            cells.append(f'<path d="{path}" fill="{color}" fill-opacity="{_fmt(opacity)}" stroke="none" />')
            if cell_intensity >= 1.25:
                core_path = _sector_path(
                    origin_x,
                    origin_y,
                    max(42.0, center_radius - thickness * 0.15),
                    min(max_radius, center_radius + thickness * 0.38),
                    center_angle - spread * 0.32,
                    center_angle + spread * 0.36,
                )
                cells.append(f'<path d="{core_path}" fill="#ff5ef1" fill-opacity="0.55" stroke="none" />')

    rings = []
    for fraction, label in ((0.33, "10"), (0.66, "20"), (1.0, "40")):
        radius = max_radius * fraction
        rings.append(f'<path d="{_arc_path(origin_x, origin_y, radius, start_deg, end_deg)}" fill="none" stroke="#f3f4f6" stroke-opacity="0.74" stroke-width="2" />')
        label_x, label_y = _polar(origin_x, origin_y, 0, radius)
        rings.append(
            f'<text x="{_fmt(label_x + 16)}" y="{_fmt(label_y + 5)}" fill="#d1d5db" font-size="18" font-family="monospace">{label}</text>'
        )

    heading_x1, heading_y1 = _polar(origin_x, origin_y, 0, 26)
    heading_x2, heading_y2 = _polar(origin_x, origin_y, 0, max_radius + 16)
    wedge_outline = [
        f'<path d="{_arc_path(origin_x, origin_y, max_radius, start_deg, end_deg)}" fill="none" stroke="#22d3ee" stroke-opacity="0.3" stroke-width="2" />',
        f'<line x1="{_fmt(origin_x)}" y1="{_fmt(origin_y)}" x2="{_fmt(_polar(origin_x, origin_y, start_deg, max_radius)[0])}" y2="{_fmt(_polar(origin_x, origin_y, start_deg, max_radius)[1])}" stroke="#22d3ee" stroke-opacity="0.3" stroke-width="2" />',
        f'<line x1="{_fmt(origin_x)}" y1="{_fmt(origin_y)}" x2="{_fmt(_polar(origin_x, origin_y, end_deg, max_radius)[0])}" y2="{_fmt(_polar(origin_x, origin_y, end_deg, max_radius)[1])}" stroke="#22d3ee" stroke-opacity="0.3" stroke-width="2" />',
        f'<line x1="{_fmt(heading_x1)}" y1="{_fmt(heading_y1)}" x2="{_fmt(heading_x2)}" y2="{_fmt(heading_y2)}" stroke="#7cf3ff" stroke-width="3" />',
    ]

    body = [
        '<rect width="100%" height="100%" fill="#05070c" />',
        '<rect x="16" y="16" width="668" height="668" rx="26" fill="url(#bg)" stroke="#2b3440" stroke-width="2" />',
        "<defs>",
        '<linearGradient id="bg" x1="0%" y1="0%" x2="0%" y2="100%">',
        '<stop offset="0%" stop-color="#0b1220" />',
        '<stop offset="100%" stop-color="#04070c" />',
        "</linearGradient>",
        "</defs>",
        *wedge_outline,
        *rings,
        *cells,
        f'<text x="34" y="44" fill="#f8fafc" font-size="18" font-family="monospace">GS {int(round(ownship.ground_speed_kt))}  TAS {int(round(ownship.true_airspeed_kt))}</text>',
        f'<text x="{_fmt(width - 134)}" y="44" fill="#f8fafc" font-size="18" font-family="monospace">WIND {int(round(weather.wind_direction_deg)):03d}/{int(round(weather.wind_speed_kt))}</text>',
        f'<text x="{_fmt(width / 2 - 56)}" y="30" fill="#86efac" font-size="18" font-family="monospace">TRK {int(round(ownship.track_deg or ownship.heading_deg)):03d}</text>',
        f'<text x="{_fmt(width / 2 - 18)}" y="62" fill="#fca5a5" font-size="16" font-family="monospace">{int(round(ownship.heading_deg))}</text>',
        f'<text x="{_fmt(width - 154)}" y="72" fill="#e5e7eb" font-size="16" font-family="monospace">VIS {weather.visibility_m / 1852.0:.1f}NM</text>',
        f'<text x="40" y="{_fmt(height - 126)}" fill="#60a5fa" font-size="16" font-family="monospace">WX SYNTH</text>',
        f'<text x="40" y="{_fmt(height - 104)}" fill="#93c5fd" font-size="14" font-family="monospace">L0 {_fmt(weather.cloud_layers[0].coverage_percent)}%  P {_fmt(weather.precipitation_on_aircraft_ratio)}</text>',
        f'<polygon points="{_fmt(origin_x)},{_fmt(origin_y - 8)} {_fmt(origin_x - 18)},{_fmt(origin_y + 28)} {_fmt(origin_x + 18)},{_fmt(origin_y + 28)}" fill="#f97316" stroke="#fed7aa" stroke-width="2" />',
    ]
    return _svg_root(width, height, body)


def _traffic_target_symbol(x: float, y: float, color: str) -> str:
    points = [
        f"{_fmt(x)},{_fmt(y - 10)}",
        f"{_fmt(x + 10)},{_fmt(y)}",
        f"{_fmt(x)},{_fmt(y + 10)}",
        f"{_fmt(x - 10)},{_fmt(y)}",
    ]
    return f'<polygon points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.4" />'


def _traffic_label(target: TrafficTarget) -> str:
    if target.relative_altitude_ft is not None:
        value = int(round(target.relative_altitude_ft / 100.0))
        if value > 0:
            return f"+{value:02d}"
        if value < 0:
            return f"{value:03d}"
        return "+00"
    if target.flight_level:
        return target.flight_level.replace("FL", "")
    altitude_ft = target.altitude_m * 3.28084
    return f"{int(round(altitude_ft / 100.0)):03d}"


def render_traffic_svg(snapshot: Snapshot, *, width: int = 700, height: int = 700, max_range_nm: float = 40.0) -> str:
    ownship = snapshot.ownship
    traffic = snapshot.traffic
    center_x = width / 2
    center_y = height * 0.54
    max_radius = min(width, height) * 0.36
    track_deg = ownship.track_deg or ownship.heading_deg
    body = [
        '<rect width="100%" height="100%" fill="#05070c" />',
        '<rect x="16" y="16" width="668" height="668" rx="26" fill="#0a0e18" stroke="#2f3543" stroke-width="2" />',
        f'<text x="{_fmt(center_x - 46)}" y="42" fill="#86efac" font-size="22" font-family="monospace">HDG {int(round(ownship.heading_deg)):03d}</text>',
        f'<text x="{_fmt(width - 138)}" y="42" fill="#86efac" font-size="18" font-family="monospace">MAG</text>',
        f'<path d="M {_fmt(center_x)} {_fmt(center_y - max_radius - 10)} L {_fmt(center_x)} {_fmt(center_y + max_radius + 10)}" stroke="#e5e7eb" stroke-width="2.2" />',
    ]
    for fraction, label in ((0.25, "10"), (0.5, "20"), (0.75, "30"), (1.0, "40")):
        radius = max_radius * fraction
        body.append(
            f'<circle cx="{_fmt(center_x)}" cy="{_fmt(center_y)}" r="{_fmt(radius)}" fill="none" stroke="#e5e7eb" stroke-opacity="0.72" stroke-width="2" />'
        )
        body.append(
            f'<text x="{_fmt(center_x + radius - 14)}" y="{_fmt(center_y - 8)}" fill="#e5e7eb" font-size="16" font-family="monospace">{label}</text>'
        )

    route_points = [
        (center_x + max_radius * 0.12, center_y + max_radius * 0.08),
        (center_x + max_radius * 0.45, center_y - max_radius * 0.08),
        (center_x + max_radius * 0.85, center_y + max_radius * 0.22),
    ]
    body.append(
        '<path d="M '
        + " L ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in route_points)
        + '" fill="none" stroke="#d946ef" stroke-width="3" stroke-dasharray="9 8" />'
    )
    body.append(
        f'<polygon points="{_fmt(center_x)},{_fmt(center_y - 18)} {_fmt(center_x - 14)},{_fmt(center_y + 18)} {_fmt(center_x + 14)},{_fmt(center_y + 18)}" fill="#7dd3fc" stroke="#e0f2fe" stroke-width="2" />'
    )

    visible = sorted(
        [target for target in traffic if target.range_nm is not None and target.bearing_deg is not None],
        key=lambda target: target.range_nm if target.range_nm is not None else 999.0,
    )
    for target in visible:
        if target.range_nm is None or target.bearing_deg is None:
            continue
        if target.range_nm > max_range_nm * 1.1:
            continue
        scaled = _clamp(target.range_nm / max_range_nm, 0.05, 1.0)
        rel_bearing = ((target.bearing_deg - track_deg + 540.0) % 360.0) - 180.0
        x = center_x + math.sin(math.radians(rel_bearing)) * max_radius * scaled
        y = center_y - math.cos(math.radians(rel_bearing)) * max_radius * scaled
        color = "#7cff8b" if target.source == "multiplayer" else "#6ee7ff"
        body.append(_traffic_target_symbol(x, y, color))
        body.append(
            f'<text x="{_fmt(x + 12)}" y="{_fmt(y - 12)}" fill="{color}" font-size="16" font-family="monospace">{html.escape(_traffic_label(target))}</text>'
        )
        if abs(target.vertical_rate_mps) > 0.6:
            arrow = "↑" if target.vertical_rate_mps > 0 else "↓"
            body.append(
                f'<text x="{_fmt(x + 12)}" y="{_fmt(y + 12)}" fill="{color}" font-size="16" font-family="monospace">{arrow}</text>'
            )

    body.extend(
        [
            '<text x="38" y="92" fill="#60a5fa" font-size="16" font-family="monospace">ARPT</text>',
            '<text x="38" y="116" fill="#60a5fa" font-size="16" font-family="monospace">STA</text>',
            '<text x="38" y="596" fill="#60a5fa" font-size="16" font-family="monospace">TFC</text>',
            '<text x="38" y="620" fill="#60a5fa" font-size="16" font-family="monospace">TCAS</text>',
            '<text x="38" y="644" fill="#4ade80" font-size="18" font-family="monospace">VOR 1</text>',
            f'<text x="{_fmt(width - 140)}" y="644" fill="#86efac" font-size="18" font-family="monospace">RNG {int(round(max_range_nm))}</text>',
            f'<text x="{_fmt(width - 140)}" y="668" fill="#4ade80" font-size="18" font-family="monospace">TGT {len(visible)}</text>',
        ]
    )
    return _svg_root(width, height, body)


def render_dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X-Plane 12 Original Displays</title>
  <style>
    :root {
      --bg: #071018;
      --panel: rgba(10, 17, 29, 0.88);
      --panel-border: rgba(148, 163, 184, 0.18);
      --text: #e5eef7;
      --muted: #8ca0b3;
      --accent: #5eead4;
      --accent-2: #7dd3fc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(34, 211, 238, 0.14), transparent 32%),
        radial-gradient(circle at top right, rgba(217, 70, 239, 0.12), transparent 28%),
        linear-gradient(180deg, #071018 0%, #03060b 100%);
    }
    main {
      width: min(1400px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 16px;
      margin-bottom: 20px;
    }
    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 0.95;
      letter-spacing: -0.03em;
    }
    p {
      margin: 0;
      color: var(--muted);
      max-width: 720px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 24px;
      overflow: hidden;
      box-shadow: 0 20px 80px rgba(0, 0, 0, 0.35);
      backdrop-filter: blur(16px);
    }
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: 18px 20px 8px;
    }
    .panel-header h2 {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    .panel-header span {
      color: var(--muted);
      font-size: 13px;
    }
    .panel img {
      display: block;
      width: 100%;
      aspect-ratio: 1 / 1;
      background: #02040a;
    }
    .panel--wide {
      grid-column: 1 / -1;
    }
    .panel--wide img {
      aspect-ratio: 16 / 7;
      object-fit: cover;
      object-position: center;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      padding: 0 20px 20px;
    }
    .stat {
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(148, 163, 184, 0.12);
    }
    .label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .value {
      font-size: 18px;
      font-weight: 600;
    }
    .status {
      margin-top: 18px;
      padding: 14px 18px;
      border-radius: 18px;
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(148, 163, 184, 0.14);
      color: var(--muted);
    }
    code {
      color: var(--accent-2);
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
    }
    @media (max-width: 700px) {
      main { width: min(100vw - 18px, 1400px); padding-top: 18px; }
      header { display: block; }
      .panel-header { display: block; }
      .panel-header span { display: block; margin-top: 4px; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>X-Plane 12<br>Original Displays</h1>
        <p>Live images are exported by an in-process X-Plane plugin. Weather uses the original radar texture and gauges come from built-in avionics callbacks instead of synthetic redraws.</p>
      </div>
      <div class="status" id="status">Loading <code>/v1/snapshot</code> …</div>
    </header>
    <section class="grid">
      <article class="panel">
        <div class="panel-header">
          <h2>Weather</h2>
          <span>/v1/render/weather.png</span>
        </div>
        <img id="weatherImage" alt="Weather radar style image">
        <div class="stats" id="weatherStats"></div>
      </article>
      <article class="panel">
        <div class="panel-header">
          <h2>Traffic</h2>
          <span>/v1/render/traffic.png</span>
        </div>
        <img id="trafficImage" alt="Traffic navigation display image">
        <div class="stats" id="trafficStats"></div>
      </article>
      <article class="panel panel--wide">
        <div class="panel-header">
          <h2>Gauges</h2>
          <span>/v1/render/gauges.png</span>
        </div>
        <img id="gaugesImage" alt="Live cockpit gauges image">
      </article>
    </section>
  </main>
  <script>
    const weatherImage = document.getElementById("weatherImage");
    const trafficImage = document.getElementById("trafficImage");
    const gaugesImage = document.getElementById("gaugesImage");
    const weatherStats = document.getElementById("weatherStats");
    const trafficStats = document.getElementById("trafficStats");
    const status = document.getElementById("status");

    function stat(label, value) {
      return `<div class="stat"><span class="label">${label}</span><span class="value">${value}</span></div>`;
    }

    function refreshImages(ts) {
      weatherImage.src = `/v1/render/weather.png?t=${ts}`;
      trafficImage.src = `/v1/render/traffic.png?t=${ts}`;
      gaugesImage.src = `/v1/render/gauges.png?t=${ts}`;
    }

    async function refresh() {
      const ts = Date.now();
      refreshImages(ts);
      try {
        const response = await fetch(`/v1/snapshot?t=${ts}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const snapshot = await response.json();
        const weather = snapshot.weather || {};
        const ownship = snapshot.ownship || {};
        const traffic = snapshot.traffic || [];
        const clouds = weather.cloud_layers || [];
        weatherStats.innerHTML = [
          stat("Wind", `${Math.round(weather.wind_direction_deg || 0)}° / ${Math.round(weather.wind_speed_kt || 0)} kt`),
          stat("Visibility", `${(((weather.visibility_m || 0) / 1852)).toFixed(1)} nm`),
          stat("Cloud L0", `${Math.round((clouds[0] && clouds[0].coverage_percent) || 0)}%`),
          stat("Precip", `${(weather.precipitation_on_aircraft_ratio || 0).toFixed(2)}`)
        ].join("");
        trafficStats.innerHTML = [
          stat("Heading", `${Math.round(ownship.heading_deg || 0)}°`),
          stat("Track", `${Math.round((ownship.track_deg || ownship.heading_deg || 0))}°`),
          stat("Ground Speed", `${Math.round(ownship.ground_speed_kt || 0)} kt`),
          stat("Targets", `${traffic.length}`)
        ].join("");
        status.textContent = `Source ${snapshot.source_mode || "unknown"} · ${traffic.length} targets · updated ${new Date(snapshot.timestamp_utc).toLocaleTimeString()}`;
      } catch (error) {
        status.textContent = `Snapshot refresh failed: ${error}`;
      }
    }

    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""
