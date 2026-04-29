# Web UI

This directory tracks the static frontend deployed at `faa.agaii.org/xplane12/`.

## Layout

- `xplane12/index.html` — dashboard markup
- `xplane12/styles.css` — static styling
- `xplane12/dashboard.js` — live data polling, radar image refresh, gauge cards, and modal UI
- `xplane12/public-xplane12-check.png` — deployed static check asset

## Runtime expectations

The frontend is written as a static site and uses relative paths so it can be hosted directly under `/xplane12/`.

It expects these server-side endpoints at runtime:

- `./api/`
- `./v1/render/weather.png`
- `./v1/render/traffic.png`
- `./v1/render/gauges.png`
- `./v1/render/gauges.json`
