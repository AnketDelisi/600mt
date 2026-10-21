/* 600mt — "make your own prediction" map painter.
 * Paint House districts, Senate seats and governorships; tally updates live.
 * Data: data/us/geo.json (pre-projected 2026 boundaries), forecast.json,
 *       races.json (current composition).
 */
const S = {
  geo: null,
  forecast: null,
  comp: null,
  chamber: "house",
  brush: "1",
  paint: { house: {}, senate: {}, governor: {} },
  hist: { house: [], senate: [], governor: [] },
  red: { house: [], senate: [], governor: [] },
  raceByKey: { house: {}, senate: {}, governor: {} },
  order: { house: [], senate: [], governor: [] },
  zoom: null,
  drag: false,
  last: { D: "1", R: "4", I: "7" },
  centroids: {},
};

const FILL = {
  "1": "#A3BEDB", "2": "#5D8FBF", "3": "#2E6EA8",
  "4": "#E2A9A9", "5": "#D27474", "6": "#C83737",
  "7": "#B6ABC8", "8": "#9284AB", "9": "#6C5F86",
  t: "#D9C27A",
};
const UNPAINT = "#E9E4D8";
const NORACE = "#DAD5C8";
const LABEL = {
  "1": "Lean Democratic", "2": "Likely Democratic", "3": "Solid Democratic",
  "4": "Lean Republican", "5": "Likely Republican", "6": "Solid Republican",
  "7": "Lean Independent", "8": "Likely Independent", "9": "Solid Independent",
  t: "Tossup", ".": "Not called",
};
const PARTY_OF = (code) => (code === "t" || code === "." ? null : code <= "3" ? "D" : code <= "6" ? "R" : "I");
const BASE_OF = { D: 1, R: 4, I: 7 };
const UP = {
  house: { total: 435, floor: 0, majority: 218, label: "House" },
  senate: { total: 100, floor: 65, majority: 51, label: "Senate" },
  governor: { total: 50, floor: 14, majority: 26, label: "Governors" },
};

const $ = (id) => document.getElementById(id);
const fmt = (x) => (x % 1 === 0 ? String(x) : x.toFixed(1));

const ABBR = {
  Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA",
  Colorado: "CO", Connecticut: "CT", Delaware: "DE", Florida: "FL", Georgia: "GA",
  Hawaii: "HI", Idaho: "ID", Illinois: "IL", Indiana: "IN", Iowa: "IA",
  Kansas: "KS", Kentucky: "KY", Louisiana: "LA", Maine: "ME", Maryland: "MD",
  Massachusetts: "MA", Michigan: "MI", Minnesota: "MN", Mississippi: "MS",
  Missouri: "MO", Montana: "MT", Nebraska: "NE", Nevada: "NV", "New Hampshire": "NH",
  "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
  "North Dakota": "ND", Ohio: "OH", Oklahoma: "OK", Oregon: "OR", Pennsylvania: "PA",
  "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", Tennessee: "TN",
  Texas: "TX", Utah: "UT", Vermont: "VT", Virginia: "VA", Washington: "WA",
  "West Virginia": "WV", Wisconsin: "WI", Wyoming: "WY",
};

/* ---------- data prep ---------- */
function districtKey(d) { return d.s + ":" + d.cd; }

function centroidOf(d) {
  // largest subpath's bounding-box centre (stable for multi-part states)
  let best = null;
  for (const part of d.split("M").slice(1)) {
    const nums = part.match(/-?\d+(?:\.\d+)?/g);
    if (!nums || nums.length < 4) continue;
    let n = 0, x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i + 1 < nums.length; i += 2) {
      const x = +nums[i], y = +nums[i + 1];
      n++;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
    if (!n) continue;
    const cand = { n, x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
    if (!best || cand.n > best.n) best = cand;
  }
  return best ? [best.x, best.y] : null;
}

function prepare() {
  const geo = S.geo, fc = S.forecast;
  // House: district key -> race + a stable paint order
  const houseRaces = {};
  for (const r of fc.house.races) {
    houseRaces[r.state + "|" + String(r.district || "")] = r;
  }
  S.order.house = geo.districts.map((d) => {
    const key = districtKey(d);
    const st = geo.states[d.s];
    S.raceByKey.house[key] = houseRaces[st.name + "|" + d.cd] || null;
    return key;
  });
  for (const ch of ["senate", "governor"]) {
    const races = fc[ch].races.slice().sort((a, b) => a.state.localeCompare(b.state));
    S.order[ch] = races.map((r) => r.state);
    for (const r of races) S.raceByKey[ch][r.state] = r;
  }
  for (const st of geo.states) {
    const c = centroidOf(st.d);
    if (c) S.centroids[st.name] = c;
  }
}

/* ---------- base (not-up) seats ---------- */
function baseSeats() {
  const ch = S.chamber;
  if (ch === "house") return { d: 0, r: 0, i: 0, note: "" };
  if (ch === "senate") {
    const comp = (S.comp && S.comp.senate) || { d: 45, r: 53, i: 2 };
    const up = { d: 0, r: 0, i: 0 };
    for (const r of S.forecast.senate.races) {
      const p = (r.party || "").toLowerCase()[0];
      if (p === "d" || p === "r" || p === "i") up[p]++;
    }
    return {
      d: comp.d - up.d, r: comp.r - up.r, i: (comp.i || 0) - up.i,
      note: `${comp.d - up.d + comp.r - up.r + (comp.i || 0) - up.i} seats are not up: ${comp.d - up.d} D &middot; ${comp.r - up.r} R${comp.i ? ` &middot; ${comp.i} I` : ""}.`,
    };
  }
  return { d: 0, r: 0, i: 0, note: `${UP.governor.total - S.order.governor.length} governorships are not up.` };
}

/* ---------- rendering ---------- */
function fillFor(key, paintable) {
  const code = S.paint[S.chamber][key];
  if (code && FILL[code]) return FILL[code];
  return paintable ? UNPAINT : NORACE;
}

function svgOpen() {
  const g = S.geo;
  return `<svg viewBox="0 0 ${g.w} ${g.h}" role="img" aria-label="Map">`;
}

function buildSnapshotMap() {
  const geo = S.geo;
  let body = `<g class="land"><path d="${geo.nation}"/></g>`;
  for (const st of geo.states) {
    const paintable = !!S.raceByKey[S.chamber][st.name];
    const code = S.paint[S.chamber][st.name];
    const fill = fillFor(st.name, paintable);
    body += `<path class="region${paintable ? "" : " nopaint"}" data-key="${st.name}" data-name="${st.name}" d="${st.d}" style="fill:${fill}"/>`;
    const c = S.centroids[st.name];
    if (paintable && c) {
      body += `<text class="state-label" x="${c[0]}" y="${c[1]}" text-anchor="middle">${ABBR[st.name] || ""}</text>`;
    }
  }
  return body;
}

function buildHouseMap() {
  const geo = S.geo;
  if (S.zoom !== null) {
    const si = S.zoom, st = geo.states[si];
    const [x0, y0, x1, y1] = st.box;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const pad = 0.84;
    const sc = Math.min((geo.w * pad) / (x1 - x0 || 1), (geo.h * pad) / (y1 - y0 || 1));
    const t = `translate(${geo.w / 2},${geo.h / 2}) scale(${sc}) translate(${-cx},${-cy})`;
    const dists = geo.districts.filter((d) => d.s === si);
    const paths = dists.map((d) => {
      const key = districtKey(d);
      return `<path class="dist" data-key="${key}" data-name="${st.name} ${d.cd === "at-large" ? "At Large" : d.cd}" d="${d.d}" style="fill:${fillFor(key, true)}"/>`;
    });
    return `<g transform="${t}">${paths.join("")}</g>`;
  }
  const paths = geo.districts.map((d) => {
    const st = geo.states[d.s];
    const key = districtKey(d);
    return `<path class="dist" data-key="${key}" data-name="${st.name} ${d.cd === "at-large" ? "At Large" : d.cd}" d="${d.d}" style="fill:${fillFor(key, true)}"/>`;
  });
  return paths.join("") + `<g class="sub">${geo.states.map((s) => `<path d="${s.d}"/>`).join("")}</g>`;
}

function render() {
  const ch = S.chamber;
  const frame = $("frame");
  const isHouse = ch === "house";
  const body = isHouse ? buildHouseMap() : buildSnapshotMap();
  $("stage").innerHTML = svgOpen() + body + "</svg>";
  const names = { house: "House", senate: "Senate", governor: "Governors" };
  const zoombar = $("zoombar");
  if (isHouse && S.zoom !== null) {
    zoombar.hidden = false;
    $("zoomName").textContent = S.geo.states[S.zoom].name;
  } else {
    zoombar.hidden = true;
  }
  $("status").innerHTML = ch === "house"
    ? `House &middot; all 435 districts on the ballot`
    : ch === "senate"
      ? `Senate &middot; 35 of 100 seats up &middot; 65 not up`
      : `Governors &middot; 36 of 50 governorships on the ballot`;
  $("legendLine").innerHTML = ch === "house"
    ? "Click a state to zoom in, then click districts to paint. The tally counts every district you call."
    : ch === "senate"
      ? "Only the 35 seats on the 2026 ballot can be painted; the other 65 are fixed at their current party."
      : "Only the 36 governorships on the 2026 ballot can be painted.";
  // track pointer for the tooltip
  frame.querySelectorAll("path.region, path.dist").forEach((el) => {
    el.addEventListener("pointerenter", () => {});
  });
  tally();
}

/* ---------- painting ---------- */
function paintableFromEvent(target) {
  const el = target.closest && target.closest("path.region, path.dist");
  if (!el) return null;
  if (el.classList.contains("nopaint")) return null;
  if (S.chamber !== "house" && !S.raceByKey[S.chamber][el.dataset.key]) return null;
  return el;
}

function setFill(key) {
  const el = document.querySelector(`path[data-key="${CSS.escape(key)}"]`);
  if (el) el.style.fill = fillFor(key, true);
}

function pushUndo() {
  const ch = S.chamber;
  S.hist[ch].push({ ...S.paint[ch] });
  if (S.hist[ch].length > 120) S.hist[ch].shift();
  S.red[ch] = [];
  syncButtons();
}

function applyAll() {
  document.querySelectorAll("path[data-key]").forEach((el) => {
    el.style.fill = fillFor(el.dataset.key, true);
  });
}

function assign(key, code) {
  const ch = S.chamber;
  if (code === ".") delete S.paint[ch][key];
  else S.paint[ch][key] = code;
  setFill(key);
}

function startStroke(e) {
  const el = paintableFromEvent(e.target);
  if (!el) return;
  e.preventDefault();
  pushUndo();
  S.drag = true;
  assign(el.dataset.key, S.brush);
  tally();
  persistSoon();
}

function strokeOver(e) {
  if (!S.drag) return;
  const el = paintableFromEvent(e.target);
  if (!el) return;
  if (S.paint[S.chamber][el.dataset.key] !== S.brush || S.brush === ".") {
    assign(el.dataset.key, S.brush);
    tally();
    persistSoon();
  }
}

function endStroke() {
  if (!S.drag) return;
  S.drag = false;
}

function eraseAt(e) {
  const el = paintableFromEvent(e.target);
  if (!el) return;
  e.preventDefault();
  pushUndo();
  assign(el.dataset.key, ".");
  tally();
  persistSoon();
}

function zoomTo(e) {
  if (S.chamber !== "house" || S.zoom !== null) return;
  const el = e.target.closest && e.target.closest("path.dist");
  if (!el) return;
  const key = el.dataset.key;
  const d = S.geo.districts.find((x) => districtKey(x) === key);
  if (d && S.geo.states[d.s]) { S.zoom = d.s; render(); }
}

function fillState() {
  if (S.chamber !== "house" || S.zoom === null) return;
  pushUndo();
  const si = S.zoom;
  for (const d of S.geo.districts.filter((x) => x.s === si)) {
    const key = districtKey(d);
    if (S.brush === ".") delete S.paint.house[key];
    else S.paint.house[key] = S.brush;
  }
  applyAll();
  tally();
  persistSoon();
}

/* ---------- tally ---------- */
function tally() {
  const ch = S.chamber;
  const paint = S.paint[ch];
  const counts = { D: 0, R: 0, I: 0, T: 0 };
  for (const code of Object.values(paint)) {
    const p = PARTY_OF(code);
    if (p) counts[p]++; else if (code === "t") counts.T++;
  }
  const base = baseSeats();
  const dTot = counts.D + base.d, rTot = counts.R + base.r, iTot = counts.I + base.i;
  $("tD").textContent = dTot;
  $("tR").textContent = rTot;
  $("tI").textContent = iTot;
  const up = UP[ch];
  const called = counts.D + counts.R + counts.I;
  const scaleFor = ch === "governor" ? S.order.governor.length : up.total;
  $("majBar").style.display = "flex";
  $("mD").style.width = (dTot / scaleFor) * 100 + "%";
  $("mI").style.width = (iTot / scaleFor) * 100 + "%";
  $("mR").style.width = (rTot / scaleFor) * 100 + "%";
  const tick = $("mTick");
  if (ch === "governor") tick.style.display = "none";
  else {
    tick.style.display = "block";
    tick.style.left = (up.majority / up.total) * 100 + "%";
  }
  const total = ch === "governor" ? S.order.governor.length : up.total;
  const totalUp = ch === "house" ? up.total : ch === "senate" ? S.order.senate.length : S.order.governor.length;
  $("tCalled").textContent = `Called ${called} of ${totalUp} on the ballot`;
  $("tLeft").textContent = ch === "senate"
    ? `${base.d + base.r + base.i} seats not up`
    : `Not called ${Math.max(0, totalUp - called)}`;
  let line;
  if (ch === "house") {
    line = `<b>218</b> seats for a majority. ${counts.T ? `${counts.T} tossup${counts.T === 1 ? "" : "s"} counted as not called.` : "Every district is on the ballot."}`;
  } else if (ch === "senate") {
    line = `${base.note} <b>51</b> for a Democratic majority &mdash; a 50&ndash;50 split keeps Republican control via the Vice President.`;
  } else {
    line = `${base.note} <b>26</b> of 50 governorships for a majority.`;
  }
  $("chamberLine").innerHTML = line;
  syncButtons();
}

function syncButtons() {
  $("undoBtn").disabled = !S.hist[S.chamber].length;
  $("redoBtn").disabled = !S.red[S.chamber].length;
}

/* ---------- undo / redo / clear / load ---------- */
function undo() {
  const ch = S.chamber;
  if (!S.hist[ch].length) return;
  S.red[ch].push({ ...S.paint[ch] });
  S.paint[ch] = S.hist[ch].pop();
  applyAll();
  tally();
  persistSoon();
}

function redo() {
  const ch = S.chamber;
  if (!S.red[ch].length) return;
  S.hist[ch].push({ ...S.paint[ch] });
  S.paint[ch] = S.red[ch].pop();
  applyAll();
  tally();
  persistSoon();
}

function clearMap() {
  pushUndo();
  S.paint[S.chamber] = {};
  applyAll();
  tally();
  persistSoon();
}

function codeForRace(race) {
  if (!race) return null;
  const lean = ((race.lean || race.rating || "") + "").toLowerCase();
  if (/tossup/.test(lean)) return "t";
  const party = race.leader || (race.margin >= 0 ? "D" : "R");
  if (!BASE_OF[party]) return null;
  let level = 1;
  if (/solid|safe/.test(lean)) level = 3;
  else if (/likely/.test(lean)) level = 2;
  else if (/lean|tilt/.test(lean)) level = 1;
  return String(BASE_OF[party] + level - 1);
}

function loadForecast() {
  pushUndo();
  const ch = S.chamber;
  const next = {};
  let tossups = 0;
  if (ch === "house") {
    for (const d of S.geo.districts) {
      const race = S.raceByKey.house[districtKey(d)];
      const code = codeForRace(race);
      if (code) next[districtKey(d)] = code;
      if (code === "t") tossups++;
    }
  } else {
    for (const name of S.order[ch]) {
      const code = codeForRace(S.raceByKey[ch][name]);
      if (code) next[name] = code;
      if (code === "t") tossups++;
    }
  }
  S.paint[ch] = next;
  applyAll();
  tally();
  persistSoon();
  toast(tossups ? `Forecast loaded — ${tossups} tossups left open` : "Forecast loaded");
}

/* ---------- persistence & share ---------- */
function encode(ch) {
  return S.order[ch].map((k) => S.paint[ch][k] || ".").join("");
}

function decode(ch, s) {
  const out = {};
  S.order[ch].forEach((k, i) => {
    const c = s[i] || ".";
    if (c !== "." && (FILL[c] || c === "t")) out[k] = c;
  });
  return out;
}

let persistTimer = null;
function persistSoon() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(persist, 250);
}
function persist() {
  try {
    localStorage.setItem("600mt-paint", JSON.stringify(S.paint));
  } catch (e) { }
}
function restore() {
  // URL hash first (#house/1131...), then localStorage
  if (location.hash.length > 3) {
    const raw = location.hash.slice(1).split("/");
    const ch = raw[0];
    if (["house", "senate", "governor"].includes(ch) && raw[1]) {
      S.chamber = ch;
      S.paint[ch] = decode(ch, raw[1]);
      return true;
    }
  }
  try {
    const saved = JSON.parse(localStorage.getItem("600mt-paint") || "{}");
    for (const ch of ["house", "senate", "governor"]) {
      if (saved[ch] && typeof saved[ch] === "object") S.paint[ch] = saved[ch];
    }
  } catch (e) { }
  return false;
}

function share() {
  const codes = encode(S.chamber);
  const url = `${location.origin}${location.pathname}#${S.chamber}/${codes}`;
  const done = () => toast("Link copied");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(done).catch(() => fallbackCopy(url, done));
  } else fallbackCopy(url, done);
}
function fallbackCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast("Copy failed"); }
  ta.remove();
}

let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 1800);
}

/* ---------- export ---------- */
function exportPNG() {
  const svg = $("stage").querySelector("svg");
  if (!svg) return;
  const W = S.geo.w, H = S.geo.h, scale = 2;
  const c = document.createElement("canvas");
  c.width = W * scale; c.height = H * scale;
  const ctx = c.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#F2F0EC";
  ctx.fillRect(0, 0, W, H);
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", W);
  clone.setAttribute("height", H);
  const css = document.createElementNS("http://www.w3.org/2000/svg", "style");
  css.textContent =
    ".region{stroke:#fff;stroke-width:0.5}.nopaint{opacity:0.4}" +
    ".dist{stroke:#fff;stroke-width:0.45}.sub{stroke:#151515;stroke-width:1;fill:none;opacity:0.4}" +
    ".land{fill:#E9E7E2;stroke:#fff;stroke-width:0.6}" +
    ".state-label{font-family:'Source Code Pro',monospace;font-size:10px;font-weight:600;fill:#6C665B}";
  clone.insertBefore(css, clone.firstChild);
  const data = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0, W, H);
    c.toBlob((b) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = `600mt-${S.chamber}-map.png`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(data);
}

/* ---------- tooltip ---------- */
let tipEl = null;
function labelFor(key) {
  const code = S.paint[S.chamber][key];
  return code ? LABEL[code] || "Painted" : "Not called";
}
function showTip(e, el) {
  if (!tipEl) return;
  const key = el.dataset.key;
  const race = S.raceByKey[S.chamber][key];
  const frameEl = $("frame");
  const rect = frameEl.getBoundingClientRect();
  const name = el.dataset.name || key;
  const ch = S.chamber;
  let html = `<div class="t">${name}</div>`;
  html += `<div class="m">Your call: ${labelFor(key)}</div>`;
  if (race) {
    const lead = race.leader || (race.margin >= 0 ? "D" : "R");
    html += `<div class="m">Forecast: ${lead}+${fmt(Math.abs(race.margin))} · ${race.lean || race.rating || "—"}</div>`;
    if (ch !== "house") html += `<div class="m">${fmt(race.dem_pct)}% D · ${fmt(race.rep_pct)}% R</div>`;
  } else {
    html += `<div class="m">Not on the 2026 ballot</div>`;
  }
  tipEl.innerHTML = html;
  tipEl.style.display = "block";
  tipEl.style.left = Math.min(rect.width - 250, e.clientX - rect.left + 14) + "px";
  tipEl.style.top = Math.max(4, e.clientY - rect.top - 10) + "px";
}
function hideTip() { if (tipEl) tipEl.style.display = "none"; }

/* ---------- wiring ---------- */
function setBrush(code) {
  S.brush = code;
  const party = PARTY_OF(code);
  if (party) S.last[party] = code;
  document.querySelectorAll("#palette .swatch").forEach((b) => {
    b.setAttribute("aria-pressed", b.dataset.code === code ? "true" : "false");
  });
}

function setChamber(ch) {
  if (S.chamber === ch) return;
  S.chamber = ch;
  S.zoom = null;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.chamber === ch));
  render();
}

function wire() {
  tipEl = $("tip");
  $("frame").addEventListener("pointerdown", (e) => {
    if (S.chamber === "house" && S.zoom === null) return;
    startStroke(e);
  });
  $("frame").addEventListener("pointerover", (e) => {
    const el = paintableFromEvent(e.target);
    if (el) showTip(e, el);
    else hideTip();
    strokeOver(e);
  });
  $("frame").addEventListener("pointerleave", hideTip);
  $("frame").addEventListener("pointerup", endStroke);
  window.addEventListener("pointerup", endStroke);
  $("frame").addEventListener("contextmenu", eraseAt);
  $("frame").addEventListener("click", (e) => {
    if (S.chamber === "house" && S.zoom === null) zoomTo(e);
  });

  document.querySelectorAll("#palette .swatch").forEach((b) => {
    b.addEventListener("click", () => setBrush(b.dataset.code));
  });
  document.querySelectorAll(".tab").forEach((t) => {
    t.addEventListener("click", () => setChamber(t.dataset.chamber));
  });
  $("loadFc").addEventListener("click", loadForecast);
  $("clearBtn").addEventListener("click", clearMap);
  $("undoBtn").addEventListener("click", undo);
  $("redoBtn").addEventListener("click", redo);
  $("shareBtn").addEventListener("click", share);
  $("pngBtn").addEventListener("click", exportPNG);
  $("backBtn").addEventListener("click", () => { S.zoom = null; render(); });
  $("fillStateBtn").addEventListener("click", fillState);

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "d" || k === "r" || k === "i") { setBrush(S.last[k.toUpperCase()]); return; }
    if (k === "t") { setBrush("t"); return; }
    if (k === "u") { undo(); return; }
    if (k === "y") { redo(); return; }
    if (k === "escape") { if (S.zoom !== null) { S.zoom = null; render(); } return; }
    if (k === "backspace") { setBrush("."); return; }
    if (k >= "1" && k <= "3") {
      const party = PARTY_OF(S.brush) || "D";
      setBrush(String(BASE_OF[party] + (+k - 1)));
    }
  });
}

/* ---------- boot ---------- */
Promise.all([
  fetch("data/us/geo.json", { cache: "no-store" }).then((r) => r.json()),
  fetch("data/us/forecast.json", { cache: "no-store" }).then((r) => r.json()),
  fetch("data/us/races.json", { cache: "no-store" }).then((r) => r.json()).catch(() => null),
])
  .then(([geo, fc, races]) => {
    S.geo = geo;
    S.forecast = fc;
    S.comp = (races && races.composition) || null;
    prepare();
    restore();
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.chamber === S.chamber));
    wire();
    setBrush("1");
    render();
  })
  .catch((err) => {
    $("stage").innerHTML = '<div class="load">Could not load the map data.</div>';
    console.error(err);
  });
