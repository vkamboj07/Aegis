/* AEGIS browser control centre.
 *
 * The server owns the simulation and does the geometry: every position in a
 * state payload is already projected into the 800x720 map space that
 * aegis/core/geo.py defines, which is the same space the Pygame build draws
 * in. This file therefore does no simulation and no projection. It polls,
 * draws, and sends commands.
 *
 * Two clocks:
 *   - a poll every POLL_MS, which is what makes simulated time pass at all
 *     (the server advances a session when it is asked for state);
 *   - requestAnimationFrame for drawing, which extrapolates between the last
 *     two polls so vehicles glide instead of stepping ten times a second.
 */
'use strict';

const POLL_MS = 100;            // how often state is fetched
const TOAST_MS = 4500;
const MAX_LOG = 120;
const MAX_EXTRAPOLATE = 2.0;    // poll intervals of dead reckoning before giving up
const STORE_KEY = 'aegis.session';

/* Events worth interrupting someone over, and how loud each one is. */
const TOAST_LEVEL = {
  resolved: 'good', repaired: 'good', breakdown: 'bad', random_event: 'bad',
  replan: 'info', rule: 'warn', escalation: 'warn', requeued: 'warn',
};

/* Map ink. The palette matches aegis/desktop/map_view.py. */
const C = {
  landDot: '#e2dbca', grid: '#dfd8c7',
  water: '#9ac6e2', waterEdge: '#70a4cc', hills: 'rgba(214,198,160,.55)',
  state: '#bcb199', roadCase: '#b09254', roadFill: '#f6d476',
  closedCase: '#821414', closedFill: '#d63a3a',
  ink: '#282832', inkSoft: '#706a5e', white: '#ffffff', select: '#0096d2',
  base: '#285aaa', ghostTrail: '#78787f',
};

const el = (id) => document.getElementById(id);
const api = {
  map: null, meta: null, id: null,
};

/* ---- state held between frames --------------------------------------- */
let cur = null;             // latest state payload
let prev = null;            // the one before, for extrapolation
let curAt = 0, prevAt = 0;  // performance.now() when each arrived
let cursor = -1;            // records already seen
let logLines = [];
let toasts = [];
let selected = { city: null, vehicle: null, road: null };
let hover = null;
let pointer = null;
let polling = false;
let stopped = false;

/* ====================================================================== *
 * Session lifecycle
 * ====================================================================== */

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 404 && api.id && path.includes(api.id)) {
    // The run expired or the instance restarted. Start a fresh one rather
    // than leaving a dead page on screen.
    throw Object.assign(new Error('session expired'), { expired: true });
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw Object.assign(new Error(detail), { status: res.status });
  }
  return res.status === 204 ? null : res.json();
}

async function newSession() {
  const data = await request('/api/sessions', { method: 'POST' });
  api.id = data.state.session;
  api.map = data.map;
  sessionStorage.setItem(STORE_KEY, api.id);
  cursor = -1;
  logLines = [];
  prev = null;
  accept(data.state);
  return data;
}

async function resumeOrCreate() {
  const saved = sessionStorage.getItem(STORE_KEY);
  if (saved) {
    try {
      api.map = await request(`/api/sessions/${saved}/map`);
      api.id = saved;
      accept(await request(`/api/sessions/${saved}/state?since=-1`));
      return;
    } catch (e) {
      if (!e.expired) throw e;
    }
  }
  await newSession();
}

function boot(message, isError = false) {
  const curtain = el('boot');
  const msg = el('boot-msg');
  if (message === null) {
    curtain.hidden = true;
    el('app').hidden = false;
    return;
  }
  curtain.hidden = false;
  el('app').hidden = true;
  msg.textContent = message;
  msg.classList.toggle('error', isError);
  el('boot-retry').hidden = !isError;
}

async function start() {
  try {
    api.meta = await request('/api/meta');
    await resumeOrCreate();
    buildControls();
    boot(null);
    initBase();
    resize();
    requestAnimationFrame(frame);
    poll();
  } catch (e) {
    boot(`Could not reach the AEGIS service: ${e.message}`, true);
  }
}

/* ---- polling --------------------------------------------------------- */
function accept(state) {
  // Keep the previous sample only if it is from the same run; a reset rewinds
  // the clock and extrapolating across that would fling vehicles backwards.
  prev = cur && cur.t <= state.t ? cur : null;
  prevAt = curAt;
  cur = state;
  curAt = performance.now();
  if (state.records && state.records.length) {
    ingestRecords(state.records);
  }
  cursor = state.cursor;
  renderPanel(state);
}

async function poll() {
  if (polling || stopped) return;
  polling = true;
  try {
    accept(await request(`/api/sessions/${api.id}/state?since=${cursor}`));
  } catch (e) {
    if (e.expired) {
      try { await newSession(); } catch { /* retried on the next tick */ }
    }
  } finally {
    polling = false;
    if (!stopped) setTimeout(poll, POLL_MS);
  }
}

/* A command returns the state it produced, so the page updates at once
 * instead of waiting for the next poll. */
async function command(path, body, method = 'POST') {
  try {
    const data = await request(`/api/sessions/${api.id}${path}`, {
      method, body: body === undefined ? undefined : JSON.stringify(body),
    });
    accept(data && data.state ? data.state : data);
    return data;
  } catch (e) {
    if (e.expired) { await newSession(); return null; }
    pushToast(e.message, 'bad');
    return null;
  }
}

/* ====================================================================== *
 * Panel
 * ====================================================================== */

function option(value, label) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = label === undefined ? value : label;
  return o;
}

function buildControls() {
  const kind = el('kind');
  api.meta.incident_types.forEach((t) => kind.append(option(t)));

  const loc = el('location');
  api.map.cities.forEach((c) => loc.append(option(c.name)));
  loc.value = api.map.cities.some((c) => c.name === 'Jaipur') ? 'Jaipur' : api.map.cities[0].name;
  selected.city = loc.value;

  const road = el('road');
  api.map.roads.forEach((r) => road.append(option(`${r.a}|${r.b}`, roadLabel(r, false))));

  const vehicle = el('vehicle');
  cur.vehicles.forEach((v) => vehicle.append(option(v.name)));

  el('legend-algos').innerHTML = api.map.algorithms
    .map((a) => `<i class="race algo-chip" style="background:${api.map.algorithm_colors[a]}"></i>${a}`)
    .join(' ');

  wireControls();
}

function roadLabel(r, closed) {
  return `${r.a} – ${r.b} (${r.distance} km)${closed ? '  CLOSED' : ''}`;
}

function selectedRoad() {
  const [a, b] = el('road').value.split('|');
  return { a, b };
}

function form() {
  return {
    kind: el('kind').value,
    location: el('location').value,
    severity: Number(el('severity').value),
    people: Number(el('people').value),
  };
}

let batch = [];

function wireControls() {
  el('severity').addEventListener('input', (e) => { el('sev-out').textContent = e.target.value; });
  el('people').addEventListener('input', (e) => { el('ppl-out').textContent = e.target.value; });
  el('location').addEventListener('change', (e) => { selected.city = e.target.value; });
  el('road').addEventListener('change', () => { selected.road = selectedRoad(); });
  el('vehicle').addEventListener('change', (e) => { selected.vehicle = e.target.value; renderPanel(cur); });

  el('report').addEventListener('click', () => command('/incidents', form()));
  el('stage').addEventListener('click', () => {
    batch.push(form());
    syncBatch();
  });
  el('dispatch').addEventListener('click', async () => {
    if (!batch.length) return;
    const items = batch;
    batch = [];
    syncBatch();
    await command('/incidents/batch', { items });
  });
  el('clear-batch').addEventListener('click', () => { batch = []; syncBatch(); });

  el('toggle-road').addEventListener('click', () => command('/roads', selectedRoad()));
  el('breakdown').addEventListener('click', () => {
    const name = el('vehicle').value;
    command(`/vehicles/${encodeURIComponent(name)}/breakdown`, undefined);
  });
  el('random').addEventListener('click', () => command('/control', { random_events: !cur.random_events }));

  el('pause').addEventListener('click', () => command('/control', { paused: !cur.paused }));
  el('slower').addEventListener('click', () => changeSpeed(-1));
  el('faster').addEventListener('click', () => changeSpeed(1));
  el('reset').addEventListener('click', async () => {
    batch = [];
    logLines = [];
    cursor = -1;
    await command('/reset', undefined);
  });
  el('demo').addEventListener('click', () => command('/demo', { name: 'showcase', reset: true }));

  el('scenario-form').addEventListener('submit', (e) => {
    e.preventDefault();
    runScenario(true);
  });
  el('scenario-preview').addEventListener('click', () => runScenario(false));
  document.querySelectorAll('.chip[data-example]').forEach((chip) =>
    chip.addEventListener('click', () => {
      el('scenario').value = chip.dataset.example;
      runScenario(false);
    }));
  wireTopics();

  el('boot-retry').addEventListener('click', () => { stopped = false; start(); });
  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', resize);
}

function changeSpeed(d) {
  const speeds = api.meta.speeds;
  const i = speeds.indexOf(cur.speed);
  const next = speeds[Math.max(0, Math.min(speeds.length - 1, (i < 0 ? 2 : i) + d))];
  if (next !== cur.speed) command('/control', { speed: next });
}

function syncBatch() {
  const line = batch.length
    ? `Batch: ${batch.map((b) => `${b.kind} ${b.location} S${b.severity}`).join(', ')}`
    : 'Batch empty — incidents added here are reported together, so the CSP ranks them against each other.';
  el('batch-line').textContent = line;
  el('dispatch').textContent = `Dispatch batch (${batch.length})`;
  el('dispatch').disabled = !batch.length;
  el('clear-batch').disabled = !batch.length;
}

function onKey(e) {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (el('topics').open) return;          // keys belong to the topics dialog while it is open
  const keys = {
    ' ': () => command('/control', { paused: !cur.paused }),
    '+': () => changeSpeed(1), '=': () => changeSpeed(1),
    '-': () => changeSpeed(-1), '_': () => changeSpeed(-1),
    Enter: () => command('/incidents', form()),
    r: () => el('reset').click(),
    d: () => el('demo').click(),
    c: () => el('toggle-road').click(),
    b: () => el('breakdown').click(),
    Tab: () => cycleVehicle(),
  };
  const fn = keys[e.key] || keys[e.key.toLowerCase()];
  if (fn) { e.preventDefault(); fn(); }
}

function cycleVehicle() {
  const sel = el('vehicle');
  sel.selectedIndex = (sel.selectedIndex + 1) % sel.options.length;
  selected.vehicle = sel.value;
  renderPanel(cur);
}

/* ---- log and notifications ------------------------------------------- */
function ingestRecords(records) {
  for (const rec of records) {
    if (rec.detail) logLines.push({ text: rec.detail, kind: rec.event });
    const level = TOAST_LEVEL[rec.event];
    if (level && rec.detail) pushToast(rec.detail, level);
  }
  if (logLines.length > MAX_LOG) logLines = logLines.slice(-MAX_LOG);
}

function pushToast(text, level = 'info') {
  toasts.push({ text, level, until: performance.now() + TOAST_MS });
  toasts = toasts.slice(-4);
  renderToasts();
}

function renderToasts() {
  const now = performance.now();
  toasts = toasts.filter((t) => t.until > now);
  const box = el('toasts');
  box.innerHTML = '';
  for (const t of toasts) {
    const div = document.createElement('div');
    div.className = `toast ${t.level}`;
    div.textContent = t.text.length > 110 ? `${t.text.slice(0, 107)}…` : t.text;
    box.append(div);
  }
}

/* ---- panel rendering -------------------------------------------------- */
function renderPanel(s) {
  if (!s) return;

  el('clock').textContent = `t = ${s.t.toFixed(1)} h   ${s.paused ? 'PAUSED' : `${s.speed}x`}`;
  el('clock').classList.toggle('paused', s.paused);
  el('pause').textContent = s.paused ? 'Resume' : 'Pause';
  el('speed-out').textContent = `${s.speed}x`;
  el('random').textContent = `Random disruptions: ${s.random_events ? 'ON' : 'OFF'}`;
  el('random').classList.toggle('danger', s.random_events);

  // Road picker: keep the labels honest about what is closed.
  const closed = new Set(s.closed_roads.map((p) => p.join('|')));
  const roadSel = el('road');
  for (const opt of roadSel.options) {
    const [a, b] = opt.value.split('|');
    const r = api.map.roads.find((x) => x.a === a && x.b === b);
    const isClosed = closed.has([a, b].sort().join('|'));
    opt.textContent = roadLabel(r, isClosed);
  }
  const pick = selectedRoad();
  const pickClosed = closed.has([pick.a, pick.b].sort().join('|'));
  el('toggle-road').textContent = pickClosed ? 'Reopen road' : 'Close road';
  el('toggle-road').classList.toggle('ok', pickClosed);
  el('toggle-road').classList.toggle('danger', !pickClosed);

  const chosen = s.vehicles.find((v) => v.name === el('vehicle').value);
  el('breakdown').disabled = !chosen || !['dispatched', 'returning'].includes(chosen.status);
  el('base-note').textContent = `base: ${s.depot} · ${s.ready}/${s.vehicles.length} ready`;

  renderQueue(s);
  renderFleet(s);
  renderLog();
  renderRace(s);

  if (s.allocation) {
    const a = s.allocation;
    el('csp-note').textContent =
      `CSP: ${Object.keys(a.assignment).length} assigned · ${a.nodes} nodes · ${a.pruned} pruned`;
  }
}

function renderQueue(s) {
  const open = s.ranked
    .map((id) => s.incidents.find((i) => i.id === id))
    .filter(Boolean);
  const list = el('queue');
  list.innerHTML = '';
  if (!open.length) {
    list.innerHTML = '<li class="empty">No open incidents.</li>';
    return;
  }
  open.slice(0, 6).forEach((inc, i) => {
    const li = document.createElement('li');
    li.innerHTML = `<i class="dot level-${inc.level}"></i>`
      + `<span><span class="rank">${i + 1}.</span> ${escape(inc.summary)}</span>`;
    list.append(li);
  });
  if (open.length > 6) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = `+${open.length - 6} more`;
    list.append(li);
  }
}

function renderFleet(s) {
  const list = el('fleet');
  list.innerHTML = '';
  for (const v of s.vehicles) {
    const li = document.createElement('li');
    const mark = v.name === el('vehicle').value ? ' ◂' : '';
    li.innerHTML = `<i class="dot level-${v.level}"></i>`
      + `<span><span class="vname">${escape(v.name)}</span>${mark} — `
      + `<span class="vstate level-${v.level}">${escape(v.status_text)}</span></span>`;
    list.append(li);
  }
}

function renderLog() {
  const list = el('log');
  const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 24;
  list.innerHTML = '';
  for (const line of logLines.slice(-40)) {
    const li = document.createElement('li');
    li.className = `kind-${line.kind}`;
    li.textContent = line.text;
    list.append(li);
  }
  if (atBottom) list.scrollTop = list.scrollHeight;
}

function renderRace(s) {
  // The focused vehicle's race if it has one, else the newest running race.
  const focus = el('vehicle').value;
  const mine = s.races.filter((r) => r.vehicle === focus);
  const running = s.races.filter((r) => r.running);
  const race = mine.length ? mine[mine.length - 1]
    : (running.length ? running[running.length - 1] : s.races[s.races.length - 1]);
  const card = el('race-card');
  if (!race) { card.hidden = true; return; }
  card.hidden = false;
  el('race-title').textContent = `Route race: ${race.vehicle} → ${race.destination}`;
  const rows = el('race-rows');
  rows.innerHTML = '';
  const best = Math.min(...race.rows.filter((r) => r.reachable).map((r) => r.distance_km));
  for (const r of race.rows) {
    const tr = document.createElement('tr');
    if (r.chosen) tr.className = 'chosen';
    const colour = api.map.algorithm_colors[r.algorithm];
    const result = r.arrived_h !== null ? `arrived ${r.arrived_h.toFixed(1)} h`
      : r.progress !== null ? `${Math.round(r.progress * 100)}%`
        : r.reachable ? (r.chosen ? 'driving' : 'racing') : 'no route';
    tr.innerHTML =
      `<td><i class="algo-chip" style="background:${colour}"></i>${r.algorithm}</td>`
      + `<td>${r.reachable ? `${r.distance_km} km` : '—'}</td>`
      + `<td>${r.reachable ? r.hops : '—'}</td>`
      + `<td>${r.nodes_expanded}</td>`
      + `<td class="${r.reachable && r.distance_km === best ? 'won' : ''}">${result}</td>`;
    rows.append(tr);
  }
}

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ====================================================================== *
 * Map
 * ====================================================================== */

const canvas = el('map');
const ctx = canvas.getContext('2d');
const view = { scale: 1, dx: 0, dy: 0 };

/* ---- real map tiles ---------------------------------------------------- */
/* The server places cities in Web Mercator with one scale for both axes
 * (api.map.projection). Leaflet draws the same Mercator, so every point on the
 * canvas can be given its tile position exactly: a plain scale and shift. That
 * shift becomes `view`, so all the drawing code below stays as it was. */
let base = null;          // the Leaflet map under the canvas, once it has loaded
let baseZoom = null;      // the zoom that frames the whole network

function mercatorY(latDeg) {
  const phi = latDeg * Math.PI / 180;
  return Math.log(Math.tan(Math.PI / 4 + phi / 2));
}

function mapToLatLng(x, y) {
  const p = api.map.projection;
  const lon = p.lon0 * Math.PI / 180 + (x - p.x0) / p.k;
  const m = mercatorY(p.lat0) - (y - p.y0) / p.k;
  const lat = 2 * Math.atan(Math.exp(m)) - Math.PI / 2;
  return L.latLng(lat * 180 / Math.PI, lon * 180 / Math.PI);
}

function syncView() {
  // Leaflet rounds each screen point to a whole pixel, so the scale is measured
  // over a long baseline: a 1 px rounding error then costs well under 0.1 %.
  const origin = base.latLngToContainerPoint(mapToLatLng(0, 0));
  const far = base.latLngToContainerPoint(mapToLatLng(4000, 4000));
  view.scale = (far.x - origin.x) / 4000;
  view.dx = origin.x;
  view.dy = origin.y;
}

function fitNetwork() {
  base.fitBounds(L.latLngBounds(api.map.cities.map((c) => [c.lat, c.lon])), { padding: [36, 36], animate: false });
  baseZoom = base.getZoom();
  base.setMinZoom(baseZoom - 1);
  base.setMaxZoom(baseZoom + 2);
}

function initBase() {
  // Offline, or if the CDN is blocked, there is no Leaflet: keep the schematic backdrop.
  if (!window.L || !api.map || !api.map.projection) return;
  base = L.map('tiles', { zoomSnap: 0.25, worldCopyJump: false, attributionControl: true });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    minZoom: 4, maxZoom: 13,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(base);
  el('map').parentElement.classList.add('has-tiles');
}

function resize() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  view.dpr = dpr;
  if (!api.map) return;
  if (base) {
    base.invalidateSize();
    if (baseZoom === null) fitNetwork();
    syncView();
    return;
  }
  // Fit the fixed 800x720 map space into whatever the pane is, centred.
  view.scale = Math.min(rect.width / api.map.width, rect.height / api.map.height);
  view.dx = (rect.width - api.map.width * view.scale) / 2;
  view.dy = (rect.height - api.map.height * view.scale) / 2;
  view.dpr = dpr;
}

function applyTransform() {
  ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  ctx.translate(view.dx, view.dy);
  ctx.scale(view.scale, view.scale);
}

function toMap(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (clientX - rect.left - view.dx) / view.scale,
    y: (clientY - rect.top - view.dy) / view.scale,
  };
}

/* ---- interpolation ---------------------------------------------------- */
/* Positions arrive 10 times a second; drawing happens 60. Each moving thing
 * is carried forward along the velocity implied by the last two samples, so
 * motion looks continuous without the client simulating anything. */
function alpha() {
  if (!prev || !cur || curAt === prevAt) return 0;
  const interval = curAt - prevAt;
  return Math.min(MAX_EXTRAPOLATE, (performance.now() - curAt) / interval);
}

function glide(now, before, a) {
  if (!before || a <= 0) return { x: now.x, y: now.y, heading: now.heading };
  const dx = now.x - before.x;
  const dy = now.y - before.y;
  // A jump means a replan, a reset or a teleport to base, not movement.
  if (Math.hypot(dx, dy) > 120) return { x: now.x, y: now.y, heading: now.heading };
  return { x: now.x + dx * a, y: now.y + dy * a, heading: now.heading };
}

function glidedVehicles() {
  const a = alpha();
  const was = new Map((prev ? prev.vehicles : []).map((v) => [v.name, v]));
  return cur.vehicles.map((v) => ({ ...v, ...glide(v, was.get(v.name), a) }));
}

function glidedGhosts(race) {
  const a = alpha();
  const prevRace = prev && prev.races.find(
    (r) => r.vehicle === race.vehicle && r.started_h === race.started_h);
  const was = new Map((prevRace ? prevRace.ghosts : []).map((g) => [g.algorithm, g]));
  return race.ghosts.map((g) => ({ ...g, ...glide(g, was.get(g.algorithm), a) }));
}

/* ---- drawing helpers -------------------------------------------------- */
function line(points, width, colour, dash) {
  if (points.length < 2) return;
  ctx.save();
  ctx.setLineDash(dash || []);
  ctx.strokeStyle = colour;
  ctx.lineWidth = width;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const p of points.slice(1)) ctx.lineTo(p.x, p.y);
  ctx.stroke();
  ctx.restore();
}

function disc(x, y, r, fill, stroke, width = 2) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke(); }
}

function label(text, x, y, { font = '600 11px "Segoe UI", sans-serif', fill = C.ink,
  align = 'center', baseline = 'middle', pad = 0, box = null } = {}) {
  ctx.font = font;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  if (box) {
    const w = ctx.measureText(text).width + pad * 2;
    const h = 14;
    const bx = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    roundRect(bx, y - h / 2, w, h, 4);
    ctx.fillStyle = box;
    ctx.fill();
  }
  ctx.fillStyle = fill;
  ctx.fillText(text, x, y);
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
  else ctx.rect(x, y, w, h);
}

/* ---- static background ------------------------------------------------ */
let backdrop = null;

function drawBackdrop() {
  // Rebuilt only when the scale changes; it is the same every frame otherwise.
  const key = `${view.scale}|${canvas.width}|${canvas.height}`;
  if (backdrop && backdrop.key === key) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(backdrop.canvas, 0, 0);
    applyTransform();
    return;
  }
  const off = document.createElement('canvas');
  off.width = canvas.width;
  off.height = canvas.height;
  const octx = off.getContext('2d');
  const saved = ctx.canvas;
  const realCtx = ctx;
  paintBackdrop(octx);
  backdrop = { key, canvas: off };
  realCtx.setTransform(1, 0, 0, 1, 0, 0);
  realCtx.drawImage(off, 0, 0);
  applyTransform();
  void saved;
}

function paintBackdrop(g) {
  const m = api.map;
  g.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  g.translate(view.dx, view.dy);
  g.scale(view.scale, view.scale);

  g.fillStyle = '#ece7d9';
  g.fillRect(-2000, -2000, 6000, 6000);

  // graticule
  g.strokeStyle = C.grid;
  g.lineWidth = 1;
  g.font = '10px "Segoe UI", sans-serif';
  g.fillStyle = C.state;
  for (const row of m.scenery.graticule.lat) {
    g.beginPath(); g.moveTo(0, row.y); g.lineTo(m.width, row.y); g.stroke();
    g.textAlign = 'left'; g.textBaseline = 'bottom';
    g.fillText(row.label, 4, row.y - 2);
  }
  for (const col of m.scenery.graticule.lon) {
    g.beginPath(); g.moveTo(col.x, 0); g.lineTo(col.x, m.height); g.stroke();
    g.textAlign = 'left'; g.textBaseline = 'bottom';
    g.fillText(col.label, col.x + 3, m.height - 4);
  }

  // hills, then rivers
  const hills = m.scenery.hills.points;
  g.save();
  g.strokeStyle = C.hills;
  g.lineJoin = 'round'; g.lineCap = 'round';
  for (const w of [58, 34]) {
    g.lineWidth = w;
    g.beginPath();
    g.moveTo(hills[0].x, hills[0].y);
    for (const p of hills.slice(1)) g.lineTo(p.x, p.y);
    g.stroke();
  }
  g.restore();

  for (const river of m.scenery.rivers) {
    for (const [w, colour] of [[6, C.waterEdge], [4, C.water]]) {
      g.save();
      g.strokeStyle = colour; g.lineWidth = w;
      g.lineJoin = 'round'; g.lineCap = 'round';
      g.beginPath();
      g.moveTo(river.points[0].x, river.points[0].y);
      for (const p of river.points.slice(1)) g.lineTo(p.x, p.y);
      g.stroke();
      g.restore();
    }
  }

  // state and feature names
  g.fillStyle = C.state;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.font = '700 14px "Segoe UI", sans-serif';
  for (const s of m.scenery.states) {
    g.fillText(s.name.split('').join(' '), s.x, s.y);
  }
  g.font = 'italic 11px "Segoe UI", sans-serif';
  g.fillStyle = C.inkSoft;
  const mid = hills[Math.floor(hills.length / 2)];
  g.fillText('Aravalli Range', mid.x - 26, mid.y - 24);
  for (const river of m.scenery.rivers) {
    const p = river.points[Math.floor(river.points.length / 3)];
    g.fillStyle = C.waterEdge;
    g.fillText(river.name, p.x + 22, p.y);
  }
}

/* ---- per-frame layers -------------------------------------------------- */
function drawRoads(s) {
  const closed = new Set(s.closed_roads.map((p) => p.join('|')));
  const sel = selected.road;

  if (sel) {
    const r = api.map.roads.find((x) => x.a === sel.a && x.b === sel.b);
    if (r) line([r.from, r.to], 16, C.select);
  }
  for (const r of api.map.roads) {
    const isClosed = closed.has([r.a, r.b].sort().join('|'));
    line([r.from, r.to], 9, isClosed ? C.closedCase : C.roadCase);
    line([r.from, r.to], 6, isClosed ? C.closedFill : C.roadFill);
    if (isClosed) line([r.from, r.to], 2, C.white, [7, 7]);
  }
  for (const r of api.map.roads) {
    const isClosed = closed.has([r.a, r.b].sort().join('|'));
    const mx = (r.from.x + r.to.x) / 2;
    const my = (r.from.y + r.to.y) / 2;
    if (isClosed) {
      disc(mx, my, 10, C.closedFill, C.white, 2);
      ctx.strokeStyle = C.white;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(mx - 4, my - 4); ctx.lineTo(mx + 4, my + 4);
      ctx.moveTo(mx - 4, my + 4); ctx.lineTo(mx + 4, my - 4);
      ctx.stroke();
    } else {
      label(String(r.distance), mx, my, {
        font: '10px "Segoe UI", sans-serif', fill: C.inkSoft, pad: 4, box: C.white,
      });
    }
  }
}

function drawRoutes(s, vehicles) {
  for (const race of s.races) {
    if (!race.running) continue;
    for (const row of race.rows) {
      if (row.chosen || !row.reachable || row.arrived_h !== null) continue;
      line(row.path, 2, api.map.algorithm_colors[row.algorithm], [6, 6]);
    }
  }
  for (const v of vehicles) {
    if (!v.moving || v.route.length < 2) continue;
    const pts = [{ x: v.x, y: v.y }, ...v.route.slice(1)];
    if (v.status === 'dispatched') {
      line(pts, 8, C.white);
      line(pts, 4, api.map.algorithm_colors[v.algorithm] || C.ink);
    } else {
      line(pts, 2, C.ghostTrail, [4, 5]);
    }
    if (v.pending_route.length > 1) {
      line(v.pending_route, 4, api.map.algorithm_colors[v.algorithm] || C.ink, [10, 6]);
    }
  }
}

const TAG_BADGE = {
  hospital: ['#ffffff', '#c82828', '+'],
  fuel_depot: ['#e87814', '#ffffff', '⛽'],
  tourist_hub: ['#7850be', '#ffffff', '★'],
};

function drawCities(s) {
  for (const c of api.map.cities) {
    if (c.name === selected.city) disc(c.x, c.y, c.radius + 9, null, C.select, 3);
    disc(c.x, c.y, c.radius, C.white, C.ink, 2);
    disc(c.x, c.y, 2, C.ink);

    c.tags.forEach((tag, k) => {
      const badge = TAG_BADGE[tag];
      if (!badge) return;
      const bx = c.x + c.radius + 4 + k * 15;
      const by = c.y - c.radius - 3;
      disc(bx, by, 7, badge[0], badge[1] === '#ffffff' ? badge[0] : badge[1], 2);
      label(badge[2], bx, by + 0.5, { font: '700 9px "Segoe UI", sans-serif', fill: badge[1] });
    });

    const r = c.radius;
    const side = c.label;
    const anchors = {
      left: [c.x - r - 5, c.y, 'right', 'middle'],
      right: [c.x + r + 5, c.tags.length ? c.y + 9 : c.y, 'left', 'middle'],
      top: [c.x, c.y - r - 9, 'center', 'middle'],
      bottom: [c.x, c.y + r + 9, 'center', 'middle'],
    };
    const [lx, ly, align, baseline] = anchors[side] || anchors.bottom;
    label(c.name, lx, ly, { font: '700 12px "Segoe UI", sans-serif', fill: C.ink, align, baseline });
  }
}

function drawBase(s) {
  const b = api.map.base;
  ctx.save();
  roundRect(b.x + 2, b.y + 3, b.w, b.h, 8);
  ctx.fillStyle = 'rgba(0,0,0,.12)';
  ctx.fill();
  roundRect(b.x, b.y, b.w, b.h, 8);
  ctx.fillStyle = C.white;
  ctx.fill();
  ctx.strokeStyle = C.base;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.save();
  roundRect(b.x, b.y, b.w, 17, 8);
  ctx.clip();
  ctx.fillStyle = C.base;
  ctx.fillRect(b.x, b.y, b.w, 17);
  ctx.restore();
  label(`AEGIS BASE · ${s.ready}/${s.vehicles.length} ready`, b.x + b.w / 2, b.y + 9,
    { font: '700 10px "Segoe UI", sans-serif', fill: C.white });
  ctx.restore();

  const depot = api.map.cities.find((c) => c.name === s.depot);
  if (depot) line([{ x: b.x + b.w, y: b.y + b.h / 2 }, { x: depot.x - 10, y: depot.y - 6 }],
    2, C.base, [5, 4]);
}

const INCIDENT_GLYPH = { Fire: '🔥', Medical: '✚', Accident: '!' };

function drawIncidents(s, pulse) {
  for (const inc of s.incidents) {
    if (inc.status === 'resolved') continue;
    marker(inc.x, inc.y, inc.type, api.map.status_colors[inc.status],
      `${inc.type.toUpperCase()} #${inc.id}  S${inc.severity}`, pulse);
  }
  for (const h of s.handled) {
    marker(h.x, h.y, 'Medical', api.map.status_colors.resolved, `HANDLED #${h.incident}`, 0);
  }
}

function marker(x, y, kind, colour, tag, pulse) {
  ctx.save();
  ctx.globalAlpha = 0.28;
  disc(x, y, 24 + pulse, colour);
  ctx.globalAlpha = 0.9;
  disc(x, y, 24 + pulse, null, colour, 3);
  ctx.restore();
  disc(x, y, 13, C.white, colour, 3);
  label(INCIDENT_GLYPH[kind] || '!', x, y + 1,
    { font: '700 13px "Segoe UI Emoji", "Segoe UI", sans-serif', fill: colour });
  label(tag, x, y - 32, { font: '700 10px "Segoe UI", sans-serif', fill: C.white, pad: 5, box: colour });
}

function truck(x, y, heading, colour, { ghost = null, selectedRing = false } = {}) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate((heading * Math.PI) / 180);
  if (ghost) ctx.globalAlpha = 0.45;
  roundRect(-15, -8, 28, 13, 3);
  ctx.fillStyle = colour;
  ctx.fill();
  ctx.fillStyle = 'rgba(0,0,0,.18)';
  roundRect(6, -7, 7, 11, 2);
  ctx.fill();
  ctx.fillStyle = '#b9d7eb';
  ctx.fillRect(9, -6, 3, 8);
  roundRect(-15, -8, 28, 13, 3);
  ctx.strokeStyle = ghost ? ghost : '#191922';
  ctx.lineWidth = ghost ? 2 : 1;
  ctx.stroke();
  ctx.restore();
  if (selectedRing) disc(x, y, 18, null, C.select, 3);
}

function drawGhosts(s) {
  for (const race of s.races) {
    if (!race.running) continue;
    const kind = (cur.vehicles.find((v) => v.name === race.vehicle) || {}).kind;
    const colour = kind ? api.map.vehicle_kinds[kind].color : '#888';
    for (const g of glidedGhosts(race)) {
      const edge = api.map.algorithm_colors[g.algorithm];
      truck(g.x, g.y, g.heading, colour, { ghost: edge });
      label(g.algorithm, g.x, g.y - 15,
        { font: '700 9px "Segoe UI", sans-serif', fill: C.white, pad: 4, box: edge });
    }
  }
}

function drawVehicles(s, vehicles) {
  for (const v of vehicles) {
    const colour = api.map.vehicle_kinds[v.kind].color;
    truck(v.x, v.y, v.heading, colour, { selectedRing: v.name === selected.vehicle });
    if (v.status === 'dispatched' && v.moving && v.algorithm) {
      label(v.algorithm, v.x, v.y - 15, {
        font: '700 9px "Segoe UI", sans-serif', fill: C.white, pad: 4,
        box: api.map.algorithm_colors[v.algorithm] || C.ink,
      });
    }
    if (v.status === 'broken') {
      disc(v.x, v.y - 17, 8, '#cd2323', C.white, 2);
      label('!', v.x, v.y - 17, { font: '700 11px "Segoe UI", sans-serif', fill: C.white });
      label(`repair ${v.repair_left_h.toFixed(1)} h`, v.x, v.y + 16,
        { font: '700 10px "Segoe UI", sans-serif', fill: '#aa1414' });
    }
  }
}

/* ---- frame ------------------------------------------------------------- */
function frame() {
  if (cur && api.map) {
    const pulse = 3 * Math.sin(performance.now() / 160);
    if (base) {
      syncView();                               // follow any pan or zoom of the tiles
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      applyTransform();
    } else {
      drawBackdrop();
    }
    const vehicles = glidedVehicles();
    drawRoads(cur);
    drawRoutes(cur, vehicles);
    drawCities(cur);
    drawBase(cur);
    drawIncidents(cur, pulse);
    drawGhosts(cur);
    drawVehicles(cur, vehicles);
    renderToasts();
    updateTooltip(vehicles);
  }
  requestAnimationFrame(frame);
}

/* ---- pointer ----------------------------------------------------------- */
function nearestRoad(p, radius = 9) {
  let best = null;
  let bestD = radius;
  for (const r of api.map.roads) {
    const d = distToSegment(p, r.from, r.to);
    if (d <= bestD) { best = r; bestD = d; }
  }
  return best;
}

function distToSegment(p, a, b) {
  const vx = b.x - a.x, vy = b.y - a.y;
  const len = vx * vx + vy * vy;
  const t = len ? Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.y - a.y) * vy) / len)) : 0;
  return Math.hypot(p.x - (a.x + vx * t), p.y - (a.y + vy * t));
}

function hitTest(p, vehicles) {
  for (const v of vehicles) {
    if (Math.abs(p.x - v.x) < 16 && Math.abs(p.y - v.y) < 12) return { kind: 'vehicle', v };
  }
  let city = null, cityD = 17;
  for (const c of api.map.cities) {
    const d = Math.hypot(p.x - c.x, p.y - c.y);
    if (d <= cityD) { city = c; cityD = d; }
  }
  if (city) return { kind: 'city', city };
  const road = nearestRoad(p);
  return road ? { kind: 'road', road } : null;
}

/* The canvas ignores the pointer (so the tiles can be dragged and zoomed), and the
 * tile container passes the same events on to the logic below. */
const pointerArea = el('tiles');
pointerArea.addEventListener('pointermove', (e) => { pointer = { client: e, map: toMap(e.clientX, e.clientY) }; });
pointerArea.addEventListener('pointerleave', () => { pointer = null; hover = null; el('tooltip').hidden = true; });

pointerArea.addEventListener('click', (e) => {
  if (!cur) return;
  const p = toMap(e.clientX, e.clientY);
  const hit = hitTest(p, glidedVehicles());
  if (!hit) return;
  if (hit.kind === 'vehicle') {
    el('vehicle').value = hit.v.name;
    selected.vehicle = hit.v.name;
    renderPanel(cur);
  } else if (hit.kind === 'city') {
    el('location').value = hit.city.name;
    selected.city = hit.city.name;
  } else {
    el('road').value = `${hit.road.a}|${hit.road.b}`;
    selected.road = { a: hit.road.a, b: hit.road.b };
    renderPanel(cur);
  }
});

pointerArea.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  if (!cur) return;
  const road = nearestRoad(toMap(e.clientX, e.clientY));
  if (!road) return;
  el('road').value = `${road.a}|${road.b}`;
  selected.road = { a: road.a, b: road.b };
  command('/roads', { a: road.a, b: road.b });
});

function updateTooltip(vehicles) {
  const tip = el('tooltip');
  if (!pointer) { tip.hidden = true; return; }
  const hit = hitTest(pointer.map, vehicles);
  if (!hit) { tip.hidden = true; return; }
  let html = '';
  if (hit.kind === 'vehicle') {
    const v = hit.v;
    html = `<b>${escape(v.name)}</b><span>${escape(v.status_text)}</span>`
      + `<span>${v.algorithm ? `algorithm: ${v.algorithm}` : 'no route yet'}</span>`
      + (v.incident ? `<span>incident #${v.incident}</span>` : '');
  } else if (hit.kind === 'city') {
    const c = hit.city;
    const here = cur.incidents.filter((i) => i.location === c.name && i.status !== 'resolved');
    html = `<b>${escape(c.name)}${c.name === cur.depot ? ' (base)' : ''}</b>`
      + `<span>facilities: ${c.tags.map((t) => t.replace('_', ' ')).join(', ') || 'none'}</span>`
      + (here.length
        ? here.slice(0, 3).map((i) =>
          `<span>${i.type} #${i.id}: S${i.severity}, ${i.people} ppl, ${i.status}</span>`).join('')
        : '<span>no open incidents</span>');
  } else {
    const r = hit.road;
    const isClosed = cur.closed_roads.some((pair) => pair.join('|') === [r.a, r.b].sort().join('|'));
    html = `<b>${escape(r.a)} – ${escape(r.b)}</b>`
      + `<span>${r.distance} km, ${isClosed ? 'CLOSED' : 'open'}</span>`
      + '<span>click to select · right-click to close or reopen</span>';
  }
  tip.innerHTML = html;
  tip.hidden = false;
  const rect = canvas.getBoundingClientRect();
  const box = tip.getBoundingClientRect();
  const x = Math.min(pointer.client.clientX - rect.left + 14, rect.width - box.width - 8);
  const y = Math.min(pointer.client.clientY - rect.top + 14, rect.height - box.height - 8);
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}

/* Stop polling while the tab is hidden: a background tab cannot be watched,
 * and a paused clock is better than a backlog of simulated hours. */
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopped = true;
  } else if (stopped && api.id) {
    stopped = false;
    poll();
  }
});

/* ====================================================================== *
 * Typed emergencies: preview what the prompt engine understood, then run it
 * ====================================================================== */

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

async function runScenario(run) {
  const input = el('scenario');
  const text = input.value.trim();
  const out = el('scenario-preview-out');
  if (!text) {
    pushToast('Type an emergency first, or pick one of the examples.', 'warn');
    return;
  }
  const data = await command('/scenario', { text, run });
  if (!data || !data.scenario) return;
  const sc = data.scenario;
  out.hidden = false;
  if (!sc.events.length) {
    out.replaceChildren(h('p', { class: 'warn', text:
      'The prompt engine could not find an event in that. Name a city from the map, an incident type ' +
      '(fire, accident or medical) and, if you like, a number of people and a time such as "at 2 hours".' }));
    return;
  }
  const head = run ? 'Simulated: these events were queued at the current time'
                   : 'Understood as (press Simulate to run it):';
  const items = sc.described.map((line) => h('li', { text: line }));
  const notes = sc.warnings.map((w) => h('li', { class: 'warn', text: 'Note: ' + w }));
  out.replaceChildren(h('p', { class: 'preview-head', text: head }), h('ul', {}, ...items, ...notes));
  if (run) input.value = '';
}

/* ====================================================================== *
 * Course topics: the handout, mapped to what the simulation shows
 * ====================================================================== */

const STATUS_LABEL = { built: 'Built', partial: 'Partly built', planned: 'Not built yet' };

const TOPICS = [
  { title: 'Search and problem solving', status: 'built', demo: 'compare',
    text: 'State-space search with BFS, DFS, uniform-cost search and A*, written from scratch. ' +
          'Every trip races the four searches and the vehicle drives the shortest route. A* uses ' +
          'straight-line distance as its heuristic, checked to be admissible for every road.' },
  { title: 'Heuristics and prioritisation', status: 'built',
    text: 'Urgency = severity × people affected ÷ hours waiting. Open incidents are ranked by it; ' +
          'the ranking is shown live in Priority order.' },
  { title: 'Planning and constraint satisfaction', status: 'built',
    text: 'Allocation is a constraint problem: backtracking, forward checking and branch-and-bound ' +
          'assign compatible vehicles. Planning raises the severity of an incident left unresolved ' +
          'for 2 hours and re-allocates it. Each allocation appears in the Decision log.' },
  { title: 'Knowledge representation and rules', status: 'built', demo: 'explain',
    text: 'Forward-chained rules over incident and city facts (hospitals, fuel depots, tourist hubs). ' +
          'Each rule fires once per incident.' },
  { title: 'Logic and resolution', status: 'built', demo: 'logic',
    text: 'The rules are also written as propositional Horn clauses. Resolution refutation and backward ' +
          'chaining agree with the Python rules on every combination of inputs (tests/test_logic.py).' },
  { title: 'Intelligent agents and PEAS', status: 'built', demo: 'peas',
    text: 'Each vehicle runs perceive, decide, act every tick and reacts to closures and breakdowns. ' +
          'The PEAS description covers the vehicle agents, the allocator, the rule engine and the planner.' },
  { title: 'Responsible AI', status: 'built', demo: 'fairness',
    text: 'Checks whether a city’s location alone changes the service it gets. Finding: response time is ' +
          'fully explained by distance from base, so remote cities wait much longer. Privacy: no personal ' +
          'data; the optional language model sees only the scenario text.' },
  { title: 'Expert systems and explanations', status: 'partial', demo: 'explain',
    text: 'Backward chaining explains why a rule fired, as a chain of facts. There is no general expert-system ' +
          'shell; explanations cover the knowledge rules only.' },
  { title: 'Approximate reasoning under uncertainty', status: 'planned',
    text: 'Not built. Urgency is an exact formula. A fuzzy or probabilistic severity estimate from noisy reports is planned.' },
  { title: 'Generative models: autoencoders, VAEs, GANs', status: 'planned',
    text: 'Not built yet. Planned: an autoencoder that flags unusual vehicle or road behaviour from its reconstruction error.' },
  { title: 'Transformers and large language models', status: 'partial',
    text: 'The scenario reader is keyword-based. An optional LLM fallback exists, but it calls a cloud API and is off ' +
          'by default. No transformer is built or trained here.' },
  { title: 'Prompt engineering, LangChain and local LLMs', status: 'partial',
    text: 'Prompt engineering appears as the validated system prompt of the LLM fallback. No LangChain pipeline and ' +
          'no locally hosted model yet.' },
];

const LOGIC_LINES = [
  'fire_at_fuel_depot  ⇐  Fire ∧ FuelDepot',
  'medical_at_hospital  ⇐  Medical ∧ Hospital',
  'mass_casualty  ⇐  People100',
  'crowded_tourist_hub  ⇐  Accident ∧ TouristHub ∧ ¬People60',
];

const PEAS_ROWS = [
  ['Vehicle agent', 'Reach and resolve incidents quickly; avoid closed roads', 'Drive, switch route, stop on scene, return to base', 'Own status, route roads, assigned incident'],
  ['Allocator (CSP)', 'Serve the most urgent first, with least travel', 'Assign a vehicle or leave the incident waiting', 'Urgency scores, vehicle status'],
  ['Rule engine', 'Apply domain facts once per incident', 'Raise severity or people affected', 'Incident fields, city facility tags'],
  ['Planner', 'Keep long-waiting incidents from being forgotten', 'Raise severity by 1 (cap 5), request re-allocation', 'Time reported, current time'],
];

function wireTopics() {
  const dialog = el('topics');
  el('topics-open').addEventListener('click', () => {
    renderTopics();
    dialog.showModal();
  });
  el('topics-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
}

function renderTopics() {
  const body = el('topics-body');
  const counts = TOPICS.reduce((n, t) => ({ ...n, [t.status]: (n[t.status] || 0) + 1 }), {});
  body.replaceChildren(
    h('p', { class: 'topics-count',
      text: `${counts.built || 0} built · ${counts.partial || 0} partly built · ${counts.planned || 0} not built yet` }),
    ...TOPICS.map(topicCard));
}

function topicCard(topic) {
  const live = h('div', { class: 'live' });
  const children = [
    h('div', { class: 'topic-head' },
      h('h3', { text: topic.title }),
      h('span', { class: `status ${topic.status}`, text: STATUS_LABEL[topic.status] })),
    h('p', { text: topic.text }),
  ];
  if (topic.demo) {
    children.push(h('button', { class: 'btn small', type: 'button', text: 'Show live',
      onclick: () => showDemo(topic.demo, live) }), live);
  }
  return h('article', { class: 'topic' }, ...children);
}

async function showDemo(kind, box) {
  box.replaceChildren(h('p', { class: 'hint', text: 'Loading…' }));
  try {
    if (kind === 'compare') return box.replaceChildren(await compareDemo());
    if (kind === 'explain') return box.replaceChildren(explainDemo());
    if (kind === 'fairness') return box.replaceChildren(await fairnessDemo());
    if (kind === 'logic') return box.replaceChildren(...LOGIC_LINES.map((t) => h('code', { text: t })));
    if (kind === 'peas') return box.replaceChildren(peasTable());
  } catch (e) {
    box.replaceChildren(h('p', { class: 'warn', text: `Could not load: ${e.message}` }));
  }
}

async function compareDemo() {
  const data = await request(`/api/sessions/${api.id}/compare?start=Delhi&goal=Kota`);
  const best = Math.min(...data.rows.filter((r) => r.reachable).map((r) => r.distance_km));
  const rows = data.rows.map((r) => h('tr', { class: r.distance_km === best ? 'best' : '' },
    h('td', { text: r.algorithm }), h('td', { text: `${r.distance_km} km` }),
    h('td', { text: `${r.hours} h` }), h('td', { text: String(r.nodes_expanded) })));
  return h('div', {},
    h('p', { class: 'hint', text: `${data.start} → ${data.goal}. Shortest route in green; fewer nodes searched means less work.` }),
    h('table', { class: 'live-table' },
      h('thead', {}, h('tr', {}, h('th', { text: 'Algorithm' }), h('th', { text: 'Distance' }),
        h('th', { text: 'Time' }), h('th', { text: 'Nodes searched' }))),
      h('tbody', {}, ...rows)));
}

function explainDemo() {
  const kind = h('select', {}, ...['Fire', 'Accident', 'Medical'].map((k) => h('option', { value: k, text: k })));
  const city = h('select', {}, ...api.map.cities.map((c) => h('option', { value: c.name, text: c.name })));
  city.value = 'Panipat';
  const people = h('input', { type: 'number', min: '1', value: '150', class: 'narrow' });
  const out = h('div', { class: 'explain-out' });
  const run = async () => {
    out.replaceChildren(h('p', { class: 'hint', text: 'Loading…' }));
    const q = new URLSearchParams({ kind: kind.value, city: city.value, people: people.value });
    const data = await request(`/api/sessions/${api.id}/explain?${q}`);
    out.replaceChildren(h('p', { class: 'hint', text: `Facts: ${data.facts.join(', ') || 'none'}` }),
      ...data.rules.map((r) => h('div', { class: r.fires ? 'rule fires' : 'rule' },
        h('strong', { text: `${r.fires ? '✔' : '✖'} ${r.name}` }),
        ...r.proof.map((line) => h('div', { class: 'proof', text: line })))));
  };
  run();                                  // show the default case straight away
  return h('div', {},
    h('div', { class: 'row' }, kind, city, people, h('button', { class: 'btn small primary', type: 'button', text: 'Explain', onclick: run })),
    out);
}

async function fairnessDemo() {
  const data = await request('/api/fairness');
  const rows = data.rows.map((r) => h('tr', { class: r.flagged ? 'flag' : '' },
    h('td', { text: r.city }), h('td', { text: String(r.distance_km) }),
    h('td', { text: r.response_h === null ? '—' : `${r.response_h.toFixed(1)} h` }),
    h('td', {}, h('span', { class: 'bar', style: `width:${Math.min(100, (r.ratio_to_median || 0) * 30)}px` })),
    h('td', { text: r.flagged ? 'slow' : '' })));
  return h('div', {},
    h('p', { class: 'hint', text: `Median ${data.summary.median_h} h. Response time follows distance from base ` +
      `(correlation ${data.summary.distance_response_correlation}). Flagged: ${data.summary.flagged.join(', ') || 'none'}.` }),
    h('table', { class: 'live-table' },
      h('thead', {}, h('tr', {}, h('th', { text: 'City' }), h('th', { text: 'km' }),
        h('th', { text: 'Response' }), h('th', { text: '× median' }), h('th', {}))),
      h('tbody', {}, ...rows)));
}

function peasTable() {
  return h('table', { class: 'live-table peas' },
    h('thead', {}, h('tr', {}, h('th', { text: 'Agent' }), h('th', { text: 'Performance' }),
      h('th', { text: 'Actuators' }), h('th', { text: 'Sensors' }))),
    h('tbody', {}, ...PEAS_ROWS.map((row) => h('tr', {}, ...row.map((c) => h('td', { text: c }))))));
}

start();
