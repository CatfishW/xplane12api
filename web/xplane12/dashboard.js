const API_BASE = './api/';
const WEATHER_IMAGE_URL = './v1/render/weather.png';
const TRAFFIC_IMAGE_URL = './v1/render/traffic.png';
const GAUGES_IMAGE_URL = './v1/render/gauges.png';
const GAUGES_MANIFEST_URL = './v1/render/gauges.json';
const REFRESH_MS = 2000;

const sections = {
  aircraft: document.getElementById('aircraft-body'),
  weather: document.getElementById('weather-body'),
  systems: document.getElementById('systems-body'),
  traffic: document.getElementById('traffic-body'),
};

const weatherImage = document.getElementById('weather-image');
const trafficImage = document.getElementById('traffic-image');
const gaugesImage = document.getElementById('gauges-image');
const gaugesPanel = document.querySelector('[data-section="gauges"]');
const gaugesPanelBody = gaugesPanel?.querySelector('.panel-body');
const gaugesHeading = gaugesPanel?.querySelector('.panel-header h2');
const pageRoot = document.querySelector('.page');

if (gaugesHeading) {
  gaugesHeading.textContent = 'Glass Deck';
}

let gaugeGrid = document.getElementById('gauge-grid');
if (!gaugeGrid && gaugesPanelBody) {
  gaugesPanelBody.classList.add('gauges-layout');
  gaugeGrid = document.createElement('div');
  gaugeGrid.id = 'gauge-grid';
  gaugeGrid.className = 'gauge-grid';
  gaugeGrid.innerHTML = '<p class="panel-state">Loading avionics displays…</p>';
  gaugesPanelBody.appendChild(gaugeGrid);
}

const runtimeStyle = document.createElement('style');
runtimeStyle.textContent = `
  .gauges-image {
    height: auto !important;
    max-height: 80vh !important;
    aspect-ratio: auto !important;
    object-fit: contain !important;
    object-position: top center !important;
  }
  .gauges-layout {
    gap: 1.25rem !important;
  }
  .gauge-grid {
    display: grid !important;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)) !important;
    gap: 1rem !important;
  }
  .gauge-card__image {
    height: auto !important;
    aspect-ratio: auto !important;
    object-fit: contain !important;
  }
  .gauge-card {
    position: relative !important;
    cursor: pointer !important;
    transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease !important;
  }
  .gauge-card:hover,
  .gauge-card:focus-within {
    transform: translateY(-3px) !important;
    box-shadow: 0 18px 36px rgba(15, 23, 42, 0.14) !important;
    border-color: rgba(11, 75, 155, 0.28) !important;
  }
  .gauge-card__trigger {
    appearance: none !important;
    border: 0 !important;
    background: transparent !important;
    color: inherit !important;
    padding: 0 !important;
    margin: 0 !important;
    width: 100% !important;
    text-align: left !important;
    cursor: pointer !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 0.75rem !important;
    font: inherit !important;
  }
  .gauge-card__cta {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 0.6rem !important;
    padding: 0.68rem 0.85rem !important;
    border-radius: 0.85rem !important;
    background: linear-gradient(135deg, rgba(11, 75, 155, 0.08), rgba(0, 162, 255, 0.14)) !important;
    border: 1px solid rgba(11, 75, 155, 0.14) !important;
    color: #0b4b9b !important;
    font-size: 0.78rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
  }
  .page.is-modal-open {
    filter: blur(14px) saturate(0.88) !important;
    transform: scale(0.995) !important;
    pointer-events: none !important;
    user-select: none !important;
    transition: filter 180ms ease, transform 180ms ease !important;
  }
  .gauge-modal {
    position: fixed !important;
    inset: 0 !important;
    z-index: 1000 !important;
    display: none !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 2rem !important;
  }
  .gauge-modal.is-open {
    display: flex !important;
  }
  .gauge-modal__backdrop {
    position: absolute !important;
    inset: 0 !important;
    background: rgba(7, 16, 24, 0.34) !important;
    backdrop-filter: blur(10px) !important;
  }
  .gauge-modal__panel {
    position: relative !important;
    width: min(1080px, calc(100vw - 32px)) !important;
    max-height: calc(100vh - 48px) !important;
    overflow: auto !important;
    border-radius: 1.4rem !important;
    border: 1px solid rgba(210, 218, 230, 0.95) !important;
    background: rgba(255, 255, 255, 0.98) !important;
    box-shadow: 0 36px 120px rgba(15, 23, 42, 0.26) !important;
    padding: 1.35rem !important;
  }
  .gauge-modal__header {
    display: flex !important;
    justify-content: space-between !important;
    align-items: flex-start !important;
    gap: 1rem !important;
    margin-bottom: 1rem !important;
  }
  .gauge-modal__eyebrow {
    margin: 0 0 0.35rem !important;
    color: #5d728a !important;
    text-transform: uppercase !important;
    letter-spacing: 0.16em !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
  }
  .gauge-modal__title {
    margin: 0 !important;
    font-family: var(--mono) !important;
    font-size: clamp(1.45rem, 2.4vw, 2.2rem) !important;
    line-height: 1.02 !important;
  }
  .gauge-modal__subtitle {
    margin: 0.5rem 0 0 !important;
    color: #475467 !important;
    max-width: 62ch !important;
    line-height: 1.55 !important;
  }
  .gauge-modal__close {
    appearance: none !important;
    border: 1px solid rgba(11, 75, 155, 0.14) !important;
    background: rgba(11, 75, 155, 0.06) !important;
    color: #0b4b9b !important;
    border-radius: 999px !important;
    width: 2.5rem !important;
    height: 2.5rem !important;
    cursor: pointer !important;
    font-size: 1.2rem !important;
    font-weight: 700 !important;
  }
  .gauge-modal__layout {
    display: grid !important;
    grid-template-columns: minmax(320px, 460px) minmax(0, 1fr) !important;
    gap: 1.1rem !important;
  }
  .gauge-modal__visual {
    border-radius: 1rem !important;
    overflow: hidden !important;
    background: #04070c !important;
    border: 1px solid rgba(11, 75, 155, 0.12) !important;
    padding: 0.9rem !important;
    align-self: start !important;
  }
  .gauge-modal__image {
    width: 100% !important;
    height: auto !important;
    display: block !important;
    object-fit: contain !important;
    border-radius: 0.8rem !important;
    background: #02040a !important;
  }
  .gauge-modal__meta {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 0.65rem !important;
    margin-top: 0.9rem !important;
  }
  .gauge-modal__pill {
    display: inline-flex !important;
    padding: 0.45rem 0.7rem !important;
    border-radius: 999px !important;
    background: rgba(11, 75, 155, 0.08) !important;
    color: #0b4b9b !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
  }
  .gauge-modal__body {
    display: grid !important;
    gap: 0.95rem !important;
  }
  .gauge-modal__section {
    border: 1px solid rgba(210, 218, 230, 0.75) !important;
    border-radius: 1rem !important;
    padding: 1rem 1rem 0.9rem !important;
    background: rgba(248, 249, 251, 0.92) !important;
  }
  .gauge-modal__section h3 {
    margin: 0 0 0.7rem !important;
    font-size: 0.9rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: #35506e !important;
  }
  .gauge-modal__section-note {
    margin: -0.2rem 0 0.8rem !important;
    color: #66778c !important;
    font-size: 0.78rem !important;
    line-height: 1.45 !important;
  }
  .gauge-modal__list {
    margin: 0 !important;
    padding-left: 1.1rem !important;
    color: #243649 !important;
    line-height: 1.55 !important;
  }
  .gauge-modal__list li + li {
    margin-top: 0.55rem !important;
  }
  .gauge-modal__grid {
    display: grid !important;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)) !important;
    gap: 0.8rem !important;
  }
  .gauge-modal__fact {
    padding: 0.8rem !important;
    border-radius: 0.85rem !important;
    background: #fff !important;
    border: 1px solid rgba(210, 218, 230, 0.72) !important;
  }
  .gauge-modal__fact-label {
    margin: 0 0 0.38rem !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.09em !important;
    color: #66778c !important;
    font-weight: 700 !important;
  }
  .gauge-modal__fact-value {
    margin: 0 !important;
    color: #0f172a !important;
    line-height: 1.45 !important;
  }
  @media (max-width: 920px) {
    .gauge-modal {
      padding: 1rem !important;
    }
    .gauge-modal__layout {
      grid-template-columns: 1fr !important;
    }
  }
`;
document.head.appendChild(runtimeStyle);

const GAUGE_GUIDES = {
  primus_pfd_1: {
    name: 'Primus PFD 1',
    role: 'Pilot-side Primary Flight Display',
    purpose: 'This is the captain-facing attitude and flight-path reference. It condenses the core “keep the airplane upright and on target” information into one display.',
    focus: ['Attitude horizon', 'IAS tape', 'Altitude tape', 'Course/HSI arc', 'Selected heading and course cues'],
    howToRead: [
      'Start in the center: blue over brown is pitch and bank. If the horizon line tilts, the aircraft is banking. If the nose symbol sits above or below the horizon, the aircraft is climbing or descending.',
      'Read the left tape for airspeed. The current IAS sits at the center pointer; trend marks and colored bands tell you whether you are approaching slow-speed or flap/structural limits.',
      'Read the right tape for altitude. The boxed value is current altitude; nearby bugs or magenta/green cues usually indicate selected targets or approach constraints.',
      'Use the lower compass rose and course needles to confirm heading, localizer capture, and lateral guidance.'
    ],
    usage: [
      'Cross-check this display during takeoff, climb, approach, and any upset recovery.',
      'If autopilot is engaged, use this to verify that commanded pitch and lateral modes are matching actual aircraft behavior.'
    ],
    cautions: [
      'Never read a single cue in isolation. Cross-check speed, attitude, and altitude together.',
      'A steady horizon with a drifting altitude or speed tape usually points to trim, thrust, or mode-management issues.'
    ],
  },
  primus_mfd_1: {
    name: 'Primus MFD 1',
    role: 'Pilot-side Multifunction / Navigation Display',
    purpose: 'This display gives the pilot a wider situational picture: route geometry, nearby navaids, terminal awareness, and map-centered navigation context.',
    focus: ['Route track', 'Waypoint labels', 'Range scale', 'Bearing geometry', 'Navigation mode labels'],
    howToRead: [
      'Center your scan on the aircraft symbol. Everything around it is relative to the current ownship position and heading/track reference.',
      'Use the arc/range markings to judge distance. If the range ring doubles, all lateral spacing needs to be mentally rescaled with it.',
      'Read waypoint labels and magenta/green route lines together: labels tell you what you are navigating to, while line geometry tells you whether you are actually intercepting or diverging.'
    ],
    usage: [
      'Use this for route awareness, STAR/SID awareness, and general lateral planning.',
      'During busy terminal operations, this is your fast “where am I relative to fixes and runway flow” display.'
    ],
    cautions: [
      'Do not use map shape alone for precision control. Fly the PFD for control inputs and use the MFD to support planning.',
      'Map clutter can hide trend mistakes if you stop cross-checking heading and altitude on the PFD.'
    ],
  },
  primus_mfd_3: {
    name: 'Primus MFD 3',
    role: 'Center Systems / EICAS Display',
    purpose: 'This screen is the aircraft systems health board. It surfaces engine condition, electrical status, hydraulics, fuel state, and configuration summaries.',
    focus: ['Engine tapes', 'Oil/ITT/Fan indications', 'Electrical readouts', 'Hydraulic pressure', 'Configuration blocks like flaps and trim'],
    howToRead: [
      'Read the engine instruments top-down. Tapes and numeric values show both trend and current state; green is normal, amber/red usually marks caution or limit crossing.',
      'Use the systems blocks on the right side for subsystem confirmation. Electrical and hydraulic values should be interpreted comparatively: left/right mismatches matter as much as absolute numbers.',
      'Configuration items like flaps, stab trim, or fuel quantities help explain handling changes seen on the PFD.'
    ],
    usage: [
      'Use this after power changes, during abnormal indications, and during before-takeoff / before-landing systems checks.',
      'If the aircraft feels wrong, this is the fastest place to verify whether the cause is engine, electrical, fuel, or hydraulic related.'
    ],
    cautions: [
      'A normal-looking attitude display does not guarantee a healthy airplane. Systems trends often deteriorate here first.',
      'Compare left and right values before you trust any single number.'
    ],
  },
  primus_mfd_2: {
    name: 'Primus MFD 2',
    role: 'Copilot-side Multifunction / Traffic Display',
    purpose: 'This is the right-side navigation context display, commonly used for traffic, map monitoring, and secondary route awareness while the left side stays primary for the flying pilot.',
    focus: ['Traffic symbols', 'Relative bearing', 'Range rings', 'Waypoint/network picture', 'Ownship-centered geometry'],
    howToRead: [
      'Use the aircraft symbol as the reference origin. All traffic and waypoint positions are relative to that symbol.',
      'Traffic symbols should be read with range first, then bearing, then trend. A target straight ahead on a short ring is operationally more urgent than one far off on a long ring.',
      'If traffic is sparse, the same screen still works as a route-awareness display; the ring spacing tells you how quickly the geometry is changing.'
    ],
    usage: [
      'Use this to support see-and-avoid, spacing awareness, and cross-monitoring by the monitoring pilot.',
      'It is especially useful when one pilot is flying the PFD and the other is managing traffic or route monitoring.'
    ],
    cautions: [
      'Treat traffic and map data as awareness tools, not collision-avoidance permission by themselves.',
      'Always cross-check with ATC, TCAS logic, and the PFD before making abrupt control changes.'
    ],
  },
  primus_pfd_2: {
    name: 'Primus PFD 2',
    role: 'Copilot-side Primary Flight Display',
    purpose: 'This is the first-officer mirror of the primary flight display. It gives the monitoring pilot an independent flight reference and supports redundancy and crew cross-checking.',
    focus: ['Attitude', 'Speed tape', 'Altitude tape', 'HSI/course', 'Guidance cues'],
    howToRead: [
      'Interpret it exactly as you would the left PFD: center for attitude, left for speed, right for altitude, lower arc for heading/course and lateral guidance.',
      'Its main value is independent confirmation. If one PFD picture looks inconsistent with the aircraft response, compare both immediately.'
    ],
    usage: [
      'Use it for PM monitoring, callouts, and confirmation of deviations on approach and climb.',
      'In abnormal or degraded operations, this screen becomes critical for crew redundancy.'
    ],
    cautions: [
      'Two matching PFDs increase confidence; disagreement between them is itself a cue that needs immediate attention.',
      'Use verbal callouts when the monitoring pilot sees a deviation here before the flying pilot reacts.'
    ],
  },
};

const gaugeModal = document.createElement('div');
gaugeModal.className = 'gauge-modal';
gaugeModal.setAttribute('aria-hidden', 'true');
gaugeModal.innerHTML = `
  <div class="gauge-modal__backdrop" data-gauge-modal-close></div>
  <div class="gauge-modal__panel" role="dialog" aria-modal="true" aria-labelledby="gauge-modal-title">
    <div class="gauge-modal__header">
      <div>
        <p class="gauge-modal__eyebrow">Interactive Gauge Guide</p>
        <h2 class="gauge-modal__title" id="gauge-modal-title">Gauge Guide</h2>
        <p class="gauge-modal__subtitle" id="gauge-modal-subtitle"></p>
      </div>
      <button class="gauge-modal__close" type="button" aria-label="Close guide" data-gauge-modal-close>&times;</button>
    </div>
    <div class="gauge-modal__layout">
      <div class="gauge-modal__visual">
        <img class="gauge-modal__image" alt="Selected gauge display" />
        <div class="gauge-modal__meta" id="gauge-modal-meta"></div>
      </div>
      <div class="gauge-modal__body">
        <section class="gauge-modal__section">
          <h3>What It Is Used For</h3>
          <div class="gauge-modal__grid" id="gauge-modal-facts"></div>
        </section>
        <section class="gauge-modal__section">
          <h3>Live Readings</h3>
          <p class="gauge-modal__section-note" id="gauge-modal-live-note"></p>
          <div class="gauge-modal__grid" id="gauge-modal-live-facts"></div>
        </section>
        <section class="gauge-modal__section">
          <h3>How To Read It</h3>
          <ul class="gauge-modal__list" id="gauge-modal-read-list"></ul>
        </section>
        <section class="gauge-modal__section">
          <h3>Operational Tips</h3>
          <ul class="gauge-modal__list" id="gauge-modal-usage-list"></ul>
        </section>
        <section class="gauge-modal__section">
          <h3>Cross-Check / Cautions</h3>
          <ul class="gauge-modal__list" id="gauge-modal-caution-list"></ul>
        </section>
      </div>
    </div>
  </div>
`;
document.body.appendChild(gaugeModal);

const gaugeModalTitle = gaugeModal.querySelector('#gauge-modal-title');
const gaugeModalSubtitle = gaugeModal.querySelector('#gauge-modal-subtitle');
const gaugeModalImage = gaugeModal.querySelector('.gauge-modal__image');
const gaugeModalMeta = gaugeModal.querySelector('#gauge-modal-meta');
const gaugeModalFacts = gaugeModal.querySelector('#gauge-modal-facts');
const gaugeModalLiveFacts = gaugeModal.querySelector('#gauge-modal-live-facts');
const gaugeModalLiveNote = gaugeModal.querySelector('#gauge-modal-live-note');
const gaugeModalReadList = gaugeModal.querySelector('#gauge-modal-read-list');
const gaugeModalUsageList = gaugeModal.querySelector('#gauge-modal-usage-list');
const gaugeModalCautionList = gaugeModal.querySelector('#gauge-modal-caution-list');
let activeGuideSlug = null;
let activeGuideGauge = null;

const timestamps = {
  aircraft: document.getElementById('aircraft-ts'),
  weather: document.getElementById('weather-ts'),
  systems: document.getElementById('systems-ts'),
  traffic: document.getElementById('traffic-ts'),
  gauges: document.getElementById('gauges-ts'),
};

const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
let latestAircraftData = null;
let latestWeatherData = null;
let latestSystemsData = null;
let latestTrafficData = null;
let latestHealth = null;
const latestGaugeManifest = new Map();
const imageLoadState = new WeakMap();

const setPanelState = (section, html) => {
  const container = sections[section];
  container.innerHTML = html;
};

const refreshImageElement = (element, url, timestampKey) => {
  if (!element) return;
  const state = imageLoadState.get(element) ?? { loading: false };
  if (state.loading) return;
  state.loading = true;
  imageLoadState.set(element, state);

  const token = String(Date.now());
  element.dataset.renderToken = token;

  const preload = new Image();
  preload.onload = () => {
    if (element.dataset.renderToken !== token) return;
    element.src = preload.src;
    state.loading = false;
    if (timestamps[timestampKey]) {
      timestamps[timestampKey].textContent = formatTime(Date.now());
    }
  };
  preload.onerror = () => {
    if (element.dataset.renderToken !== token) return;
    state.loading = false;
  };
  preload.src = `${url}?t=${Date.now()}`;
};

const formatTime = (ms) => new Date(ms).toLocaleTimeString('en-US', { hour12: false });

const titleizeGauge = (slug) =>
  slug
    .split('_')
    .map((part) => part.toUpperCase())
    .join(' ');

const resolveScopedAssetUrl = (path) => {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/')) {
    return `.${path}`;
  }
  return path;
};

const buildListMarkup = (items = []) =>
  items
    .map((item) => `<li>${item}</li>`)
    .join('');

const formatNullable = (value, suffix = '', digits = 0) => {
  if (!Number.isFinite(value)) return '—';
  return `${Number(value).toFixed(digits)}${suffix}`;
};

const formatFeet = (meters) => formatNullable(Number(meters) * 3.28084, ' ft', 0);
const formatKnots = (value) => formatNullable(value, ' kt', 0);
const formatDegrees = (value) => formatNullable(value, '°', 0);

const currentTrafficCount = () => {
  if (!latestTrafficData) return 0;
  return collectTraffic(latestTrafficData).rows.length;
};

const liveGaugeFacts = (slug) => {
  const ownship = latestAircraftData || {};
  const weather = latestWeatherData || {};
  const systems = latestSystemsData || {};
  const manifestGauge = latestGaugeManifest.get(slug);
  const updatedLabel = manifestGauge?.updated_at
    ? new Date(manifestGauge.updated_at * 1000).toLocaleTimeString('en-US', { hour12: false })
    : '—';

  const factsBySlug = {
    primus_pfd_1: [
      ['Heading', formatDegrees(ownship['sim/flightmodel/position/psi'])],
      ['Indicated airspeed', formatKnots(ownship['sim/flightmodel/position/indicated_airspeed'])],
      ['Altitude', formatFeet(ownship['sim/flightmodel/position/elevation'])],
      ['Vertical speed', formatNullable((ownship['sim/flightmodel/position/local_vz'] ?? NaN) * 196.85, ' fpm', 0)],
    ],
    primus_pfd_2: [
      ['Heading', formatDegrees(ownship['sim/flightmodel/position/psi'])],
      ['True airspeed', formatKnots(ownship['sim/flightmodel/position/true_airspeed'])],
      ['Altitude', formatFeet(ownship['sim/flightmodel/position/elevation'])],
      ['Roll / pitch', `${formatNullable(ownship['sim/flightmodel/position/phi'], '°', 1)} / ${formatNullable(ownship['sim/flightmodel/position/theta'], '°', 1)}`],
    ],
    primus_mfd_1: [
      ['Track', formatDegrees(ownship['sim/flightmodel/position/psi'])],
      ['Groundspeed', formatKnots(ownship['sim/flightmodel/position/groundspeed'])],
      ['Latitude', formatNullable(ownship['sim/flightmodel/position/latitude'], '', 4)],
      ['Longitude', formatNullable(ownship['sim/flightmodel/position/longitude'], '', 4)],
    ],
    primus_mfd_2: [
      ['Visible traffic', `${currentTrafficCount()}`],
      ['Groundspeed', formatKnots(ownship['sim/flightmodel/position/groundspeed'])],
      ['Zulu time', formatZulu(systems['sim/time/zulu_time_sec'] ?? NaN)],
      ['Heading', formatDegrees(ownship['sim/flightmodel/position/psi'])],
    ],
    primus_mfd_3: [
      ['Outside air temp', formatNullable(weather['sim/weather/aircraft/temperature_ambient_deg_c'], ' °C', 1)],
      ['Barometer', formatNullable(weather['sim/weather/barometer_sealevel_inhg'], ' inHg', 2)],
      ['Visibility', formatNullable(weather['sim/weather/visibility_reported_m'], ' m', 0)],
      ['Wind', `${formatNullable(weather['sim/weather/aircraft/wind_now_speed_msc'], ' m/s', 1)} @ ${formatNullable(weather['sim/weather/aircraft/wind_now_direction_degt'], '°', 0)}`],
    ],
  };

  return [...(factsBySlug[slug] || []), ['Last display export', updatedLabel]];
};

const renderActiveGaugeLiveFacts = () => {
  if (!activeGuideSlug) return;
  const feedState =
    latestHealth?.status === 'ok'
      ? 'Live values refresh every 2s from the X-Plane process.'
      : latestHealth?.status === 'degraded'
      ? 'Feed is delayed; values update when new X-Plane packets arrive.'
      : 'Feed is currently unavailable; last known values remain visible until X-Plane resumes.';
  if (gaugeModalLiveNote) {
    gaugeModalLiveNote.textContent = feedState;
  }
  gaugeModalLiveFacts.innerHTML = liveGaugeFacts(activeGuideSlug)
    .map(
      ([label, value]) => `
        <article class="gauge-modal__fact">
          <p class="gauge-modal__fact-label">${label}</p>
          <p class="gauge-modal__fact-value">${value}</p>
        </article>
      `
    )
    .join('');
};

const openGaugeGuide = (gauge) => {
  const guide = GAUGE_GUIDES[gauge.slug];
  if (!guide) return;

  activeGuideSlug = gauge.slug;
  activeGuideGauge = gauge;
  gaugeModalTitle.textContent = guide.name;
  gaugeModalSubtitle.textContent = guide.purpose;
  gaugeModalImage.src = `${resolveScopedAssetUrl(gauge.path)}?t=${Date.now()}`;
  gaugeModalImage.alt = `${guide.name} live display`;
  gaugeModalMeta.innerHTML = [
    `<span class="gauge-modal__pill">${guide.role}</span>`,
    `<span class="gauge-modal__pill">${Math.round(gauge.width || 0)}×${Math.round(gauge.height || 0)}</span>`,
    `<span class="gauge-modal__pill">Live feed</span>`,
  ].join('');
  gaugeModalFacts.innerHTML = [
    ['Display name', guide.name],
    ['Primary role', guide.role],
    ['Main scan focus', guide.focus.join(', ')],
  ]
    .map(
      ([label, value]) => `
        <article class="gauge-modal__fact">
          <p class="gauge-modal__fact-label">${label}</p>
          <p class="gauge-modal__fact-value">${value}</p>
        </article>
      `
    )
    .join('');
  renderActiveGaugeLiveFacts();
  gaugeModalReadList.innerHTML = buildListMarkup(guide.howToRead);
  gaugeModalUsageList.innerHTML = buildListMarkup(guide.usage);
  gaugeModalCautionList.innerHTML = buildListMarkup(guide.cautions);
  gaugeModal.classList.add('is-open');
  gaugeModal.setAttribute('aria-hidden', 'false');
  pageRoot?.classList.add('is-modal-open');
  document.body.style.overflow = 'hidden';
};

const closeGaugeGuide = () => {
  activeGuideSlug = null;
  activeGuideGauge = null;
  gaugeModal.classList.remove('is-open');
  gaugeModal.setAttribute('aria-hidden', 'true');
  pageRoot?.classList.remove('is-modal-open');
  document.body.style.overflow = '';
};

gaugeModal.addEventListener('click', (event) => {
  if (event.target.closest('[data-gauge-modal-close]')) {
    closeGaugeGuide();
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && activeGuideSlug) {
    closeGaugeGuide();
  }
});

const AUTOPILOT_LABELS = {
  0: 'Off',
  1: 'Flight director',
  2: 'Heading hold',
  8: 'Altitude hold',
  16: 'Vertical speed',
  32: 'Airspeed hold',
  64: 'Nav hold',
  128: 'Approach',
  512: 'Wing leveler',
};

const AUTOPILOT_MODE_FLAGS = {
  flightDirector: 1,
  heading: 2,
  nav: 4,
  altitudeHold: 8,
  verticalSpeed: 16,
  airspeedHold: 32,
  glideslope: 64,
  approach: 128,
  wingLeveler: 512,
  altitudeArm: 16384,
  takeoffGoAround: 32768,
  pitchSync: 65536,
  headingHold: 1048576,
  turnRate: 2097152,
  track: 4194304,
  flightPathAngle: 8388608,
};

const formatZulu = (seconds) => {
  const totalSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const hours = String(Math.floor(totalSeconds / 3600) % 24).padStart(2, '0');
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
  const secs = String(totalSeconds % 60).padStart(2, '0');
  return `${hours}:${minutes}:${secs}Z`;
};

const drawTable = (items) => {
  if (!items.length) {
    return '<p class="panel-state">No nearby traffic.</p>';
  }
  const rows = items
    .map((item) => {
      const altitude = Number.isFinite(item.altitude) ? Math.round(Math.abs(item.altitude) < 5 ? 0 : item.altitude) : null;
      const groundspeed = Number.isFinite(item.groundspeed) ? Math.round(Math.abs(item.groundspeed) < 0.5 ? 0 : item.groundspeed) : null;
      const heading = Number.isFinite(item.heading) ? Math.round(normalizeDegrees(item.heading)) % 360 : null;
      return `
        <tr>
          <td>${item.callsign}</td>
          <td>${altitude != null ? altitude : '—'} ft</td>
          <td>${groundspeed != null ? groundspeed : '—'} kt</td>
          <td>${heading != null ? heading : '—'}°</td>
          <td>${item.gearStatus ?? 'Unknown'}</td>
        </tr>
      `;
    })
    .join('');
  return `
    <table class="traffic-table">
      <thead>
        <tr>
          <th>Callsign</th>
          <th>Alt</th>
          <th>GS</th>
          <th>Heading</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
};

const isFeedFresh = () => latestHealth?.status === 'ok';

const handleHealth = async () => {
  try {
    const response = await fetch(`${API_BASE}health`, { cache: 'no-store' });
    if (!response.ok) throw new Error('health fetch failed');
    const payload = await response.json();
    latestHealth = payload;
    statusText.textContent = `${payload.status} · ${Math.round(payload.last_packet_age_sec ?? 0)}s ago`;
    statusDot.className = 'status-dot';
    statusDot.classList.add(
      payload.status === 'ok'
        ? 'status-dot--online'
        : payload.status === 'degraded'
        ? 'status-dot--degraded'
        : 'status-dot--offline'
    );
  } catch (error) {
    latestHealth = { status: 'offline', last_packet_age_sec: null };
    statusText.textContent = 'Health unavailable';
    statusDot.className = 'status-dot status-dot--offline';
    console.error('Health error', error);
  }
};

const toRadians = (degrees) => (degrees * Math.PI) / 180;
const toDegrees = (radians) => (radians * 180) / Math.PI;
const normalizeDegrees = (degrees) => ((degrees % 360) + 360) % 360;

const computeRangeAndBearing = (ownship, plane) => {
  if (!ownship) return { rangeNm: 0, bearing: plane.psi ?? 0 };
  const ownLat = ownship['sim/flightmodel/position/latitude'] ?? 0;
  const ownLon = ownship['sim/flightmodel/position/longitude'] ?? 0;
  const planeLat = plane.lat ?? 0;
  const planeLon = plane.lon ?? 0;
  if (!ownLat && !ownLon && !planeLat && !planeLon) {
    return { rangeNm: 0, bearing: plane.psi ?? 0 };
  }

  const lat1 = toRadians(ownLat);
  const lat2 = toRadians(planeLat);
  const dLat = lat2 - lat1;
  const dLon = toRadians(planeLon - ownLon);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const earthRadiusNm = 3440.065;
  const rangeNm = earthRadiusNm * c;

  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  const bearing = normalizeDegrees(toDegrees(Math.atan2(y, x)));
  return { rangeNm, bearing };
};

const fetchCategory = async (category) => {
  try {
    const response = await fetch(`${API_BASE}data?category=${category}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${category} fetch failed`);
    const payload = await response.json();
    return payload.values || {};
  } catch (error) {
    console.error(error);
    setPanelState(
      category,
      `<p class="panel-state">Unable to load ${category} data.</p>`
    );
    return null;
  }
};

const formatRow = (label, value) => `
  <div class="data-row">
    <div>
      <p class="data-label">${label}</p>
      <p class="data-value">${value}</p>
    </div>
  </div>
`;

const getWeatherValue = (data, keys, fallback = 0) => {
  for (const key of keys) {
    const value = data?.[key];
    if (value != null) return value;
  }
  return fallback;
};

const getAutopilotLabel = (value) => {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return 'Off';
  if (AUTOPILOT_LABELS[numeric]) return AUTOPILOT_LABELS[numeric];
  const exact = Object.entries(AUTOPILOT_LABELS)
    .filter(([mode]) => numeric & Number(mode))
    .map(([, label]) => label);
  return exact[0] || `Mode ${numeric}`;
};

const hasAutopilotFlag = (value, flag) => {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && (numeric & flag) === flag;
};

const getAutopilotModes = (data = {}) => {
  const mode = Number(data['sim/cockpit/autopilot/autopilot_mode'] ?? 0);
  const flightDirectorMode = Number(data['sim/cockpit2/autopilot/flight_director_mode'] ?? 0);
  const navStatus = Number(data['sim/cockpit2/autopilot/nav_status'] ?? 0);
  const altitudeHoldStatus = Number(data['sim/cockpit2/autopilot/altitude_hold_status'] ?? 0);
  const headingStatus = Number(data['sim/cockpit2/autopilot/heading_status'] ?? 0);
  const engagedModes = [];

  const primaryMode = getAutopilotLabel(mode);
  if (primaryMode !== 'Off' && primaryMode !== 'Flight director') {
    engagedModes.push(primaryMode);
  }

  if (headingStatus > 0) engagedModes.push('Heading');
  if (navStatus > 0) engagedModes.push('Nav');
  if (altitudeHoldStatus > 0) engagedModes.push('Altitude hold');

  if (!engagedModes.length && (hasAutopilotFlag(mode, AUTOPILOT_MODE_FLAGS.flightDirector) || flightDirectorMode > 0)) {
    engagedModes.push('Flight director');
  }

  return [...new Set(engagedModes)];
};

const getAutopilotModeDisplay = (data = {}) => {
  const modes = getAutopilotModes(data);
  return modes[0] || 'Off';
};

const formatAutopilotSummary = (data = {}) => {
  const state = Number(data['sim/cockpit/autopilot/autopilot_state'] ?? 0);
  const flightDirectorMode = Number(data['sim/cockpit2/autopilot/flight_director_mode'] ?? 0);
  const modes = getAutopilotModes(data);

  if (!modes.length) return 'Off';

  const summary = modes.slice(0, 3).join(' · ');
  const suffix = [];
  if (modes.length > 3) suffix.push(`+${modes.length - 3} more`);
  if (state > 0) suffix.push(`state ${state}`);
  if (!modes.some((label) => label !== 'Flight director') && flightDirectorMode > 0) suffix.push(`FD ${flightDirectorMode}`);
  return suffix.length ? `${summary} (${suffix.join(', ')})` : summary;
};

const getTrafficStateMessage = (state = {}) => {
  if (!latestHealth) return 'Loading traffic…';
  if (!isFeedFresh()) return 'Traffic feed stale.';
  if (state.hasMetadataOnlyTraffic) return 'Traffic detected, but geometry unavailable.';
  if (state.feedHealthy) return 'Traffic feed healthy. No live targets.';
  return 'No nearby traffic.';
};

const renderAircraft = (data) => {
  if (!data) return;
  latestAircraftData = data;
  const rows = [
    ['Heading', `${(data['sim/flightmodel/position/psi'] ?? 0).toFixed(0)}°`],
    ['Pitch', `${(data['sim/flightmodel/position/theta'] ?? 0).toFixed(1)}°`],
    ['Bank', `${(data['sim/flightmodel/position/phi'] ?? 0).toFixed(1)}°`],
    ['Groundspeed', `${(data['sim/flightmodel/position/groundspeed'] ?? 0).toFixed(0)} kt`],
    ['Indicated airspeed', `${(data['sim/flightmodel/position/indicated_airspeed'] ?? 0).toFixed(0)} kt`],
    ['True airspeed', `${(data['sim/flightmodel/position/true_airspeed'] ?? 0).toFixed(0)} kt`],
    ['Vertical speed', `${((data['sim/flightmodel/position/local_vz'] ?? 0) * 196.85).toFixed(0)} fpm`],
    ['Altitude', `${((data['sim/flightmodel/position/elevation'] ?? 0) * 3.28084).toFixed(0)} ft`],
    ['Latitude / Longitude', `${(data['sim/flightmodel/position/latitude'] ?? 0).toFixed(5)}, ${(data['sim/flightmodel/position/longitude'] ?? 0).toFixed(5)}`],
    ['Roll rate', `${(data['sim/flightmodel/position/R'] ?? 0).toFixed(4)} rad/s`],
    ['Pitch rate', `${(data['sim/flightmodel/position/Q'] ?? 0).toFixed(4)} rad/s`],
  ];
  setPanelState('aircraft', rows.map(([label, value]) => formatRow(label, value)).join(''));
  timestamps.aircraft.textContent = formatTime(Date.now());
};

const renderWeather = (data) => {
  if (!data) return;
  latestWeatherData = data;
  if (!Object.keys(data).length && !isFeedFresh()) {
    setPanelState('weather', '<p class="panel-state">Weather feed stale.</p>');
    if (weatherImage) weatherImage.removeAttribute('src');
    timestamps.weather.textContent = 'stale';
    return;
  }
  const windSpeed = getWeatherValue(data, ['sim/weather/aircraft/wind_now_speed_msc', 'sim/weather/wind_speed_kt']);
  const windDir = getWeatherValue(data, ['sim/weather/aircraft/wind_now_direction_degt', 'sim/weather/wind_direction_degt']);
  const temperature = getWeatherValue(data, ['sim/weather/aircraft/temperature_ambient_deg_c', 'sim/weather/temperature_ambient_c']);
  const pressure = getWeatherValue(data, ['sim/weather/aircraft/qnh_pas', 'sim/weather/aircraft/barometer_current_pas', 'sim/weather/barometer_sealevel_inhg']);
  const visibility = getWeatherValue(data, ['sim/weather/aircraft/visibility_reported_sm', 'sim/weather/visibility_reported_m']);
  const precipitation = getWeatherValue(data, ['sim/weather/aircraft/precipitation_on_aircraft_ratio', 'sim/weather/precipitation_on_aircraft_ratio']);
  const cloudCoverage = getWeatherValue(data, ['sim/weather/aircraft/cloud_coverage_percent[0]', 'sim/weather/cloud_coverage[0]']);
  const cloudBase = getWeatherValue(data, ['sim/weather/aircraft/cloud_base_msl_m[0]', 'sim/weather/cloud_base_msl_m[0]']);
  const cloudTop = getWeatherValue(data, ['sim/weather/aircraft/cloud_tops_msl_m[0]', 'sim/weather/cloud_tops_msl_m[0]']);
  const rows = [
    ['Wind', `${Number(windSpeed).toFixed(1)} ${data['sim/weather/wind_speed_kt'] != null ? 'kt' : 'm/s'} @ ${Number(windDir).toFixed(0)}°`],
    ['Temperature', `${Number(temperature).toFixed(1)} °C`],
    ['Pressure', `${Number(pressure).toFixed(0)}${data['sim/weather/barometer_sealevel_inhg'] != null ? ' inHg' : ' Pa'}`],
    ['Visibility', `${Number(visibility).toFixed(1)} ${data['sim/weather/visibility_reported_m'] != null ? 'm' : 'sm'}`],
    ['Precipitation', `${(Number(precipitation) * 100).toFixed(1)} %`],
    ['Cloud coverage', `${Number(cloudCoverage).toFixed(0)} %`],
    ['Cloud base/top', `${Number(cloudBase).toFixed(0)} m / ${Number(cloudTop).toFixed(0)} m`],
  ];
  setPanelState('weather', rows.map(([label, value]) => formatRow(label, value)).join(''));
  refreshImageElement(weatherImage, WEATHER_IMAGE_URL, 'weather');
};

const renderSystems = (data) => {
  if (!data) return;
  latestSystemsData = data;
  if (!Object.keys(data).length && !isFeedFresh()) {
    setPanelState('systems', '<p class="panel-state">Systems feed stale.</p>');
    timestamps.systems.textContent = 'stale';
    return;
  }
  const autopilotState = Number(data['sim/cockpit/autopilot/autopilot_state'] ?? 0);
  const flightDirectorMode = Number(data['sim/cockpit2/autopilot/flight_director_mode'] ?? 0);
  const headingStatus = Number(data['sim/cockpit2/autopilot/heading_status'] ?? 0);
  const navStatus = Number(data['sim/cockpit2/autopilot/nav_status'] ?? 0);
  const altitudeHoldStatus = Number(data['sim/cockpit2/autopilot/altitude_hold_status'] ?? 0);
  const warning = data['sim/cockpit2/annunciators/master_warning'] ?? 0;
  const caution = data['sim/cockpit2/annunciators/master_caution'] ?? 0;
  const chips = [];
  if (warning > 0) chips.push('<span class="chip chip--critical">Warning</span>');
  if (caution > 0) chips.push('<span class="chip chip--warning">Caution</span>');
  if (!chips.length) chips.push('<span class="chip chip--success">Nominal</span>');

  const rows = [
    ['Autopilot', formatAutopilotSummary(data)],
    ['AP mode', getAutopilotModeDisplay(data)],
    ['AP state', autopilotState > 0 ? `${autopilotState}` : 'Off'],
    ['Flight director', flightDirectorMode > 0 ? `Mode ${flightDirectorMode}` : 'Off'],
    ['Heading target', `${Number(data['sim/cockpit2/autopilot/heading_dial_deg_mag_pilot'] ?? data['sim/cockpit/autopilot/heading_mag'] ?? 0).toFixed(0)}° mag${headingStatus > 0 ? ` · status ${headingStatus}` : ''}`],
    ['Altitude target', `${Number(data['sim/cockpit2/autopilot/altitude_dial_ft'] ?? data['sim/cockpit/autopilot/altitude'] ?? 0).toFixed(0)} ft${altitudeHoldStatus > 0 ? ` · status ${altitudeHoldStatus}` : ''}`],
    ['VS target', `${Number(data['sim/cockpit2/autopilot/vvi_dial_fpm'] ?? data['sim/cockpit/autopilot/vertical_velocity'] ?? 0).toFixed(0)} fpm`],
    ['Airspeed target', `${Number(data['sim/cockpit2/autopilot/airspeed_dial_kts'] ?? data['sim/cockpit/autopilot/airspeed'] ?? 0).toFixed(0)} kt`],
    ['Nav status', navStatus > 0 ? `Tracking (${navStatus})` : 'Standby'],
    ['Zulu Time', formatZulu(data['sim/time/zulu_time_sec'] ?? 0)],
    ['Flight Time', `${(data['sim/time/total_running_time_sec'] ?? 0).toFixed(0)} s`],
  ];
  setPanelState('systems', `${chips.join(' ')}${rows.map(([label, value]) => formatRow(label, value)).join('')}`);
  timestamps.systems.textContent = formatTime(Date.now());
};

const collectTraffic = (data) => {
  const planes = new Map();
  const tcasTargets = new Map();
  Object.entries(data || {}).forEach(([key, value]) => {
    const match = key.match(/plane(\d+)_(\w+)(?:\[(\d+)\])?/);
    if (match) {
      const [, index, field] = match;
      const plane = planes.get(index) ?? { callsign: `AC-${index}`, idx: Number(index) };
      plane[field.replace(/\[\d+\]$/, '')] = value;
      planes.set(index, plane);
      return;
    }

    const tcasMatch = key.match(/sim\/cockpit2\/tcas\/targets\/(modeS_id|relative_distance_m|relative_bearing_degt|altitude_ft|position\/lat|position\/lon|position\/ele|position\/vx|position\/vy|position\/vz|position\/psi|position\/gear_deploy)\[(\d+)\]/);
    if (!tcasMatch) return;
    const [, field, index] = tcasMatch;
    const target = tcasTargets.get(index) ?? { idx: Number(index) };
    target[field.replace('position/', 'position_')] = value;
    tcasTargets.set(index, target);
  });

  const multiplayerRows = [...planes.values()]
    .filter((plane) => {
      const hasPosition = Math.abs(plane.lat ?? 0) > 0.0001 || Math.abs(plane.lon ?? 0) > 0.0001;
      const hasAltitude = Math.abs(plane.el ?? 0) > 1;
      const hasMotion = Math.abs(plane.v_x ?? 0) > 0.1 || Math.abs(plane.v_y ?? 0) > 0.1 || Math.abs(plane.v_z ?? 0) > 0.1;
      const hasHeading = Math.abs(plane.psi ?? 0) > 0.1;
      return hasPosition || hasAltitude || hasMotion || hasHeading;
    })
    .sort((a, b) => (b.el ?? 0) - (a.el ?? 0))
    .slice(0, 5)
    .map((plane) => {
      const { rangeNm, bearing } = computeRangeAndBearing(latestAircraftData, plane);
      return {
        callsign: plane.callsign,
        altitude: (plane.el ?? 0) * 3.28084,
        groundspeed: Math.hypot(plane.v_x ?? 0, plane.v_y ?? 0, plane.v_z ?? 0) * 1.94384,
        heading: plane.psi ?? 0,
        radarBearing: bearing,
        rangeNm,
        gearStatus: (plane.gear_deploy ?? 0) > 0.5 ? 'Gear' : 'Clean',
      };
    });

  if (multiplayerRows.length) {
    return { rows: multiplayerRows, hasMetadataOnlyTraffic: false, feedHealthy: isFeedFresh() };
  }

  const tcasRows = [...tcasTargets.values()]
    .filter((target) => Math.abs(target.modeS_id ?? 0) > 0.5)
    .slice(0, 5)
    .map((target) => {
      const hasPositionGeometry =
        Math.abs(target.position_lat ?? 0) > 0.0001 ||
        Math.abs(target.position_lon ?? 0) > 0.0001 ||
        Math.abs(target.position_ele ?? 0) > 1;
      const hasRelativeGeometry = Math.abs(target.relative_distance_m ?? 0) > 1 || Math.abs(target.relative_bearing_degt ?? 0) > 0.1;

      if (hasPositionGeometry) {
        const plane = {
          lat: target.position_lat,
          lon: target.position_lon,
          el: target.position_ele,
          psi: target.position_psi,
        };
        const { rangeNm, bearing } = computeRangeAndBearing(latestAircraftData, plane);
        return {
          callsign: Number.isFinite(target.modeS_id) && target.modeS_id > 0 ? `TCAS-${Math.round(target.modeS_id).toString(16).toUpperCase()}` : `TCAS-${target.idx}`,
          altitude: Number.isFinite(target.position_ele) ? target.position_ele * 3.28084 : NaN,
          groundspeed: Math.hypot(target.position_vx ?? 0, target.position_vy ?? 0, target.position_vz ?? 0) * 1.94384,
          heading: Number.isFinite(target.position_psi) ? target.position_psi : NaN,
          radarBearing: bearing,
          rangeNm,
          gearStatus: (target.position_gear_deploy ?? 0) > 0.5 ? 'Gear' : 'Tracked',
        };
      }

      return {
        callsign: Number.isFinite(target.modeS_id) && target.modeS_id > 0 ? `TCAS-${Math.round(target.modeS_id).toString(16).toUpperCase()}` : `TCAS-${target.idx}`,
        altitude: Math.abs(target.altitude_ft ?? 0) > 1 ? target.altitude_ft : NaN,
        groundspeed: NaN,
        heading: Number.isFinite(target.relative_bearing_degt) ? normalizeDegrees(target.relative_bearing_degt) : NaN,
        radarBearing: hasRelativeGeometry ? normalizeDegrees((latestAircraftData?.['sim/flightmodel/position/psi'] ?? 0) + (target.relative_bearing_degt ?? 0)) : NaN,
        rangeNm: hasRelativeGeometry ? (target.relative_distance_m ?? 0) / 1852 : NaN,
        gearStatus: hasRelativeGeometry ? 'Tracked' : 'Metadata only',
      };
    });

  return {
    rows: tcasRows.filter((row) => Number.isFinite(row.radarBearing) && Number.isFinite(row.rangeNm)),
    hasMetadataOnlyTraffic: tcasRows.length > 0 && !tcasRows.some((row) => Number.isFinite(row.radarBearing) && Number.isFinite(row.rangeNm)),
    feedHealthy: isFeedFresh(),
  };
};

const renderTraffic = (data) => {
  if (!data) return;
  latestTrafficData = data;
  if (!Object.keys(data).length && !isFeedFresh()) {
    setPanelState('traffic', '<p class="panel-state">Traffic feed stale.</p>');
    if (trafficImage) trafficImage.removeAttribute('src');
    timestamps.traffic.textContent = 'stale';
    return;
  }
  const traffic = collectTraffic(data);
  setPanelState(
    'traffic',
    traffic.rows.length ? drawTable(traffic.rows) : `<p class="panel-state">${getTrafficStateMessage(traffic)}</p>`
  );
  refreshImageElement(trafficImage, TRAFFIC_IMAGE_URL, 'traffic');
};

const renderGaugeDeck = async () => {
  if (!gaugeGrid) return;
  try {
    const response = await fetch(`${GAUGES_MANIFEST_URL}?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const gauges = payload.gauges || [];
    latestGaugeManifest.clear();
    gauges.forEach((gauge) => latestGaugeManifest.set(gauge.slug, gauge));
    if (!gauges.length) {
      gaugeGrid.innerHTML = '<p class="panel-state">Original avionics callbacks are active, but no gauge exports are available yet.</p>';
      return;
    }
    gaugeGrid.innerHTML = gauges
      .map(
        (gauge) => `
          <article class="gauge-card">
            <button
              class="gauge-card__trigger"
              type="button"
              data-gauge-slug="${gauge.slug}"
              data-gauge-path="${gauge.path}"
              data-gauge-width="${Math.round(gauge.width || 0)}"
              data-gauge-height="${Math.round(gauge.height || 0)}"
              data-gauge-updated-at="${gauge.updated_at || ''}"
              aria-label="Open guide for ${titleizeGauge(gauge.slug)}"
            >
              <div class="gauge-card__header">
                <h3>${titleizeGauge(gauge.slug)}</h3>
                <span>${Math.round(gauge.width || 0)}×${Math.round(gauge.height || 0)}</span>
              </div>
              <img
                class="gauge-card__image"
                src="${resolveScopedAssetUrl(gauge.path)}?t=${Date.now()}"
                alt="${titleizeGauge(gauge.slug)} original X-Plane display"
              />
              <span class="gauge-card__cta">
                Open Guide
                <span aria-hidden="true">+</span>
              </span>
            </button>
          </article>
        `
      )
      .join('');
    if (activeGuideSlug && activeGuideGauge && latestGaugeManifest.has(activeGuideSlug)) {
      activeGuideGauge = latestGaugeManifest.get(activeGuideSlug);
      gaugeModalImage.src = `${resolveScopedAssetUrl(activeGuideGauge.path)}?t=${Date.now()}`;
      renderActiveGaugeLiveFacts();
    }
  } catch (error) {
    gaugeGrid.innerHTML = `<p class="panel-state">Gauge deck unavailable: ${error}</p>`;
  }
};

gaugeGrid?.addEventListener('click', (event) => {
  const trigger = event.target.closest('.gauge-card__trigger');
  if (!trigger) return;
  const gauge = {
    slug: trigger.dataset.gaugeSlug,
    path: trigger.dataset.gaugePath,
    width: Number(trigger.dataset.gaugeWidth || 0),
    height: Number(trigger.dataset.gaugeHeight || 0),
    updated_at: Number(trigger.dataset.gaugeUpdatedAt || 0),
  };
  openGaugeGuide(gauge);
});

const renderGauges = async () => {
  refreshImageElement(gaugesImage, GAUGES_IMAGE_URL, 'gauges');
  await renderGaugeDeck();
};

const poll = async () => {
  await handleHealth();
  const categories = ['aircraft', 'weather', 'systems', 'traffic'];
  const promises = categories.map((category) => fetchCategory(category));
  const results = await Promise.all(promises);
  renderAircraft(results[0]);
  renderWeather(results[1]);
  renderSystems(results[2]);
  renderTraffic(results[3]);
  await renderGauges();
};

poll();
setInterval(poll, REFRESH_MS);
