/* 600mt — 2026 U.S. midterms forecast renderer.
 * Data: data/us/forecast.json (scraper/us_scrape_model.py), data/us/geo.json,
 *       data/us/polling.json.
 */
window.__errs = [];
window.addEventListener("error", (e) => window.__errs.push(String(e)));
window.addEventListener("unhandledrejection", (e) => window.__errs.push(String(e.reason || e)));

const US_DATA = "data/us/forecast.json";
const US_GEO = "data/us/geo.json";
const US_POLLS = "data/us/polling.json";
const US_LABELS = { senate: "Senate", house: "House", governor: "Governors" };

const state = { forecast: null, geo: null, polls: null, chamber: "senate", sort: "close", zoom: null };

const fmt = (x) => (Math.abs(x) >= 100 ? Math.round(x) : x % 1 === 0 ? String(Math.round(x)) : x.toFixed(1));

/* diverging blue/red by win probability, on the editorial palette */
const C_NEUT = "#ECE8DD", C_D = "#2E6EA8", C_R = "#C83737", C_GRAY = "#DFD9CB",
  C_TOSSUP = "#D9C27A", C_I = "#6C5F86";
function mixColor(a, b, t) {
  const r1 = (a >> 16) & 255, g1 = (a >> 8) & 255, b1 = a & 255;
  const r2 = (b >> 16) & 255, g2 = (b >> 8) & 255, b2 = b & 255;
  const r = Math.round(r1 + (r2 - r1) * t), g = Math.round(g1 + (g2 - g1) * t), bl = Math.round(b1 + (b2 - b1) * t);
  return `rgb(${r},${g},${bl})`;
}
function raceColor(dem, rating, ind, leader, rep) {
  const i = ind || 0;
  const lead = leader || (dem >= 50 ? "D" : "R");
  const p = lead === "D" ? dem : lead === "R" ? (rep != null ? rep : 100 - dem) : i;
  if (rating && /tossup/i.test(rating)) return C_TOSSUP;
  if (lead === "I" && p > 50) return C_I;
  const t = Math.max(0, Math.min(1, (p - 50) / 50));
  const base = lead === "R" ? C_R : C_D;
  return mixColor(parseInt(C_NEUT.slice(1), 16), parseInt(base.slice(1), 16), t);
}

function ratingClass(rating) {
  if (!rating) return "none";
  const w = rating.toLowerCase();
  if (w.includes("tossup")) return "t";
  // "Solid R" contains a "d" inside "solid"; read the party token, not any d.
  const party = w.trim().split(/\s+/).pop();
  if (party === "d" || party.startsWith("dem")) return "d";
  if (party === "r" || party.startsWith("rep")) return "r";
  return "none";
}

function partyBadge(party) {
  if (party === "D") return `<span class="party-badge D"><img src="img/D.svg" alt="D"></span>`;
  if (party === "R") return `<span class="party-badge R"><img src="img/R.svg" alt="R"></span>`;
  if (party === "I") return '<span class="party-badge I">IND</span>';
  return '<span class="party-badge open">OPEN</span>';
}

function raceKey(race) {
  return `${race.state}|${race.district || ""}|${race.incumbent || ""}`;
}

function raceRow(race) {
  const name = race.district ? `${race.state} ${race.district}` : race.state;
  const d = race.dem_pct, r = race.rep_pct, iv = race.ind_pct || 0;
  const p = race.polls;
  const bits = [];
  if (p && p.dem != null) bits.push(`D <b class="n" title="${race.dem_name || ""}">${fmt(p.dem)}</b>`);
  if (p && p.rep != null) bits.push(`R <b class="u" title="${race.rep_name || ""}">${fmt(p.rep)}</b>`);
  if (p && p.ind != null) bits.push(`I <b class="i" title="${race.ind_name || ""}">${fmt(p.ind)}</b>`);
  const polls = bits.length
    ? `<span class="polling">${bits.join(" &middot; ")}</span>`
    : '<span class="polling"><span class="none">&mdash;</span></span>';
  const inc = race.incumbent && race.incumbent !== "None (new seat)" ? `(${race.incumbent})` : "Open seat";
  const chance = iv > 0.5
    ? `<div class="chance">
        <div class="d" style="width:${d}%"></div>
        <div class="i" style="width:${iv}%"></div>
        <div class="r" style="width:${r}%"></div>
        <div class="tick"></div>
        <span class="lbl pleft">D ${fmt(d)}</span>
        <span class="lbl pind">I ${fmt(iv)}</span>
        <span class="lbl pright">R ${fmt(r)}</span>
      </div>`
    : `<div class="chance">
        <div class="d" style="width:${d}%"></div>
        <div class="r" style="width:${r}%"></div>
        <div class="tick"></div>
        <span class="lbl pleft">${fmt(d)}</span>
        <span class="lbl pright">${fmt(r)}</span>
      </div>`;
  const rr = race.ratings || {};
  const rtitle = [["Cook", rr.cook], ["IE", rr.ie], ["Sabato", rr.sabato]]
    .filter((x) => x[1]).map((x) => `${x[0]}: ${x[1]}`).join(" · ");
  const lead = race.leader || (race.margin >= 0 ? "D" : "R");
  const iBit = iv > 0.5 ? ` / ${fmt(iv)}% I` : "";
  const modelTip = `600 model: ${race.lean} (${lead}+${fmt(Math.abs(race.margin))}) — ${fmt(race.dem_pct)}% D / ${fmt(race.rep_pct)}% R${iBit}`;
  const title = rtitle ? `${modelTip} · rating inputs — ${rtitle}` : modelTip;
  return `<tr data-key="${raceKey(race)}">
    <td class="race-name">${partyBadge(race.party)}<b>${name}</b><span class="inc">${inc}</span></td>
    <td><span class="rating ${ratingClass(race.lean || race.rating)}" title="${title}">${race.lean || race.rating || "No rating"}</span></td>
    <td>${polls}</td>
    <td>${chance}</td>
  </tr>`;
}

function distributionSVG(chamberData, total, marker) {
  const buckets = chamberData.distribution_buckets || [];
  if (!buckets.length) return "";
  const W = 1080, H = 170, padB = 20;
  const maxPct = Math.max(...buckets.map((b) => b.pct));
  const x = (seats) => (seats / total) * W;
  let bars = "";
  for (const b of buckets) {
    const h = (b.pct / maxPct) * (H - padB - 6);
    const demControl = marker ? b.seats >= marker : true;
    bars += `<rect x="${x(b.seats - 1)}" y="${H - padB - h}" width="${Math.max(2, x(b.seats + 1) - x(b.seats - 1) - 1)}" height="${h}" fill="${demControl ? "var(--d)" : "var(--r)"}"/>`;
  }
  let ticks = "";
  const step = Math.max(1, Math.round(total / 8));
  for (let s = 0; s <= total; s += step) {
    ticks += `<text class="axis" x="${x(s)}" y="${H - 5}" text-anchor="middle">${s}</text>`;
  }
  const markerLine = marker
    ? `<line x1="${x(marker)}" y1="2" x2="${x(marker)}" y2="${H - padB}" stroke="#151515" stroke-width="2" stroke-dasharray="4 3"/>`
    : "";
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bars}${markerLine}${ticks}</svg>`;
}

function controlCard(chamberData) {
  const maj = chamberData.majority || {};
  const d = maj.dem_pct ?? null;
  if (d === null) return "";
  const r = maj.rep_pct;
  const iSeats = chamberData.expected_i_seats || 0;
  const label = US_LABELS[state.chamber];
  return `<div class="ctl">
    <div class="cell d"><div class="big">${fmt(d)}<span class="pct">%</span></div>
      <div class="lbl">Democrats win the ${label}</div></div>
    <div class="cell r"><div class="big">${fmt(r)}<span class="pct">%</span></div>
      <div class="lbl">Republicans win the ${label}</div></div>
    <div class="line">Expected seats — Democrats <b>${fmt(chamberData.expected_d_seats)}</b>${iSeats > 0.05 ? ` (incl. independents <b style="color:${C_I}">${fmt(iSeats)}</b>)` : ""}, Republicans <b>${fmt(chamberData.expected_r_seats)}</b>.
    ${state.chamber === "senate" ? "51 seats are needed for a Democratic majority — a 50–50 split leaves control in Republican hands via the Vice President's tie-breaking vote." : "218 seats are needed for a majority."}${iSeats > 0.05 ? " Independent wins are counted with the Democratic caucus, as the Senate independents caucus with them." : ""}</div>
  </div>`;
}

function governorCard(chamberData) {
  const dTot = chamberData.total_d_governors ?? chamberData.expected_d_seats;
  const rTot = chamberData.total_r_governors ?? chamberData.expected_r_seats;
  return `<div class="ctl">
    <div class="cell d"><div class="big">${fmt(dTot)}</div><div class="lbl">Expected Democratic governors</div></div>
    <div class="cell r"><div class="big">${fmt(rTot)}</div><div class="lbl">Expected Republican governors</div></div>
    <div class="line">Totals across all 50 governorships — ${chamberData.races.length} are contested in 2026, the other 14 are already settled.</div>
  </div>`;
}

/* ---- map ---- */
function raceByKey(data, key) { return data.races.find((r) => raceKey(r) === key) || null; }
function stateRace(races, stateName) { return races.find((r) => r.state === stateName) || null; }

function legendGradient() {
  const g = [];
  for (let i = 0; i <= 40; i++) g.push(`<i style="width:2.5%;background:${raceColor(i * 2.5)}"></i>`);
  return `<div class="map-leg">
    <b>Democratic win chance</b>
    <div class="bar">${g.join("")}</div>
    <span>0%</span><b style="border-left:1px solid var(--ink);padding-left:5px">50%</b><span>100%</span>
    <span style="margin-left:auto"><span style="display:inline-block;width:12px;height:10px;border:1px solid var(--ink);background:${C_TOSSUP};margin-right:5px;vertical-align:0"></span>tossup</span>
    <span style="margin-left:10px"><span style="display:inline-block;width:12px;height:10px;border:1px solid var(--line-strong);background:${C_GRAY};margin-right:5px;vertical-align:0"></span>no race</span>
  </div>`;
}

function mapCard(chamberData) {
  const isHouse = state.chamber === "house";
  const zoomed = isHouse && state.zoom !== null;
  const zoomName = state.zoom !== null ? state.geo.states[state.zoom].name : "";
  const ctrls = `<div class="map-ctrls">
    <span class="map-title">${isHouse ? (zoomed ? `${zoomName} · click a district for details` : "All 435 districts · click a state to zoom in") : "Click a state for details"}</span>
    ${zoomed ? `<button class="btn sm" onclick="mapReset()">&larr; Back to all states</button>` : ""}
    <button class="shot-btn" onclick="captureMap()" title="Download this map as a PNG">
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-2h6l2 2h3v11H4z"/><circle cx="12" cy="13" r="3.2"/></svg>
    </button>
  </div>`;
  return `<div class="card">
    <div class="card-head"><span class="bar"></span><div class="t">${US_LABELS[state.chamber]} map</div></div>
    <p class="note">${isHouse
      ? "Every congressional district filled by the party the model makes the favourite — the shade is the win chance."
      : `Every state contesting ${US_LABELS[state.chamber].toLowerCase()} seats in 2026, filled by the favoured party.`}</p>
    ${ctrls}
    <div class="mapwrap"><div class="map-stage"></div><div class="map-tip"></div></div>
    ${legendGradient()}
  </div>`;
}

function buildMapHTML(chamberData) {
  const geo = state.geo;
  const isHouse = state.chamber === "house";
  const W = geo.w, H = geo.h;
  const races = chamberData.races;

  const stateD = [];
  for (const st of geo.states) {
    const race = stateRace(races, st.name);
    const fill = race ? raceColor(race.dem_pct, race.lean, race.ind_pct, race.leader, race.rep_pct) : C_GRAY;
    stateD.push(`<path class="st" data-name="${st.name}" data-idx="${geo.states.indexOf(st)}" d="${st.d}" style="fill:${fill}"${race ? ` data-race="${raceKey(race)}"` : ""}/>`);
  }

  let body;
  if (isHouse && state.zoom !== null) {
    const si = state.zoom;
    const st = geo.states[si];
    const [x0, y0, x1, y1] = st.box;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const pad = 0.82;
    const s = Math.min((W * pad) / (x1 - x0 || 1), (H * pad) / (y1 - y0 || 1));
    const t = `translate(${W / 2},${H / 2}) scale(${s}) translate(${-cx},${-cy})`;
    const dists = geo.districts.filter((d) => d.s === si);
    const dPaths = dists.map((d) => {
      const race = races.find((r) => r.state === st.name && String(r.district || "") === d.cd);
      const fill = race ? raceColor(race.dem_pct, race.lean, race.ind_pct, race.leader, race.rep_pct) : C_GRAY;
      return `<path class="dist" data-name="${st.name} ${d.cd}" d="${d.d}" style="fill:${fill}"${race ? ` data-race="${raceKey(race)}"` : ""}/>`;
    });
    body = `<g transform="${t}">${dPaths.join("")}</g>`;
  } else if (isHouse) {
    const dPaths = geo.districts.map((d) => {
      const st = geo.states[d.s];
      const race = races.find((r) => r.state === st.name && String(r.district || "") === d.cd);
      const fill = race ? raceColor(race.dem_pct, race.lean, race.ind_pct, race.leader, race.rep_pct) : C_GRAY;
      return `<path class="dist" data-name="${st.name} ${d.cd === "at-large" ? "At Large" : d.cd}" data-idx="${d.s}" d="${d.d}" style="fill:${fill}"${race ? ` data-race="${raceKey(race)}"` : ""}/>`;
    });
    body = `${dPaths.join("")}<g class="sub">${geo.states.map((s) => `<path d="${s.d}"/>`).join("")}</g>`;
  } else {
    body = `<g class="land"><path d="${geo.nation}"/></g>${stateD.join("")}`;
  }
  return `<svg class="map-svg" viewBox="0 0 ${W} ${H}">${body}</svg>`;
}

function attachMap(pane, chamberData) {
  const svg = pane.querySelector(".map-svg");
  if (!svg) return;
  const tip = pane.querySelector(".map-tip");
  const isHouse = state.chamber === "house";
  const zoomed = isHouse && state.zoom !== null;
  svg.querySelectorAll(".st, .dist").forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      const rect = svg.parentElement.getBoundingClientRect();
      const name = el.getAttribute("data-name");
      const key = el.getAttribute("data-race");
      const race = key ? raceByKey(chamberData, key) : null;
      tip.style.display = "block";
      tip.style.left = Math.min(rect.width - 190, e.clientX - rect.left + 14) + "px";
      tip.style.top = Math.max(4, e.clientY - rect.top - 8) + "px";
      if (race) {
        const rn = state.chamber === "house" ? name : race.state;
        const iBit = (race.ind_pct || 0) > 0.5 ? ` · <span style="color:#C7B3DC">I ${fmt(race.ind_pct)}%</span>` : "";
        const lead = race.leader || (race.margin >= 0 ? "D" : "R");
        tip.innerHTML = `<div class="t">${rn}</div>
          <div class="r"><span class="d">D ${fmt(race.dem_pct)}%</span> · <span class="u">R ${fmt(race.rep_pct)}%</span>${iBit}</div>
          <div class="m">Margin ${lead}+${fmt(Math.abs(race.margin))}${race.lean ? " · " + race.lean : ""}</div>`;
      } else {
        tip.innerHTML = `<div class="t">${name}</div><div class="m">No 2026 race</div>`;
      }
    });
    el.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    el.addEventListener("click", () => {
      const key = el.getAttribute("data-race");
      if (isHouse && !zoomed && key) {
        const idx = parseInt(el.getAttribute("data-idx"), 10);
        if (idx !== null && !isNaN(idx) && state.geo.states[idx]) { state.zoom = idx; render(); return; }
      }
      if (key) selectRace(pane, key);
    });
  });
  svg.querySelectorAll(".st").forEach((el) => {
    el.addEventListener("mouseenter", () => { svg.querySelectorAll(".st,.dist").forEach((p) => p.classList.remove("focus")); el.classList.add("focus"); });
  });
}

function selectRace(pane, key) {
  pane.querySelectorAll("tr").forEach((tr) => tr.classList.remove("selected"));
  const tr = pane.querySelector(`tr[data-key="${CSS.escape(key)}"]`);
  if (tr && tr.scrollIntoView) { tr.classList.add("selected"); tr.scrollIntoView({ behavior: "smooth", block: "center" }); }
}

/* ---- race detail: poll table + trend ---- */
function racePollEntry(race) {
  if (state.chamber === "house") return null;
  const pool = state.polls ? state.polls[state.chamber] : null;
  if (!pool) return null;
  return pool[race.state] || null;
}

function parsePollDate(str) {
  if (!str) return null;
  const year = +(str.match(/(\d{4})$/) || [])[1];
  if (!year) return null;
  const monMap = { january: 0, february: 1, march: 2, april: 3, may: 4, june: 5, july: 6, august: 7, september: 8, october: 9, november: 10, december: 11 };
  const lastMonthMatch = str.match(/([A-Za-z]+)\s+\d{1,2}(?:\s*[–-]\s*\d{1,2})?,\s*(\d{4})$/);
  if (!lastMonthMatch) return null;
  const mon = monMap[lastMonthMatch[1].toLowerCase()];
  if (mon === undefined) return null;
  return new Date(year, mon, 1);
}

function pollTrendSVG(polls) {
  const W = 640, H = 150, padL = 44, padR = 14, padT = 18, padB = 24;
  const pts = [];
  let hasI = false;
  for (const p of polls) {
    if (!p.dates) continue;
    const dt = parsePollDate(p.dates);
    if (!dt) continue;
    if (p.ind != null) hasI = true;
    pts.push({ t: dt.getTime(), d: p.dem, r: p.rep, i: p.ind, dates: p.dates });
  }
  if (pts.length < 2) return `<div style="font-size:11px;color:var(--muted);padding:8px 0">Not enough dated polls to plot.</div>`;
  const tMin = pts[0].t, tMax = pts[pts.length - 1].t;
  let vMin = 20, vMax = 70;
  for (const p of pts) for (const v of [p.d, p.r, p.i]) { if (v == null) continue; if (v < vMin) vMin = v; if (v > vMax) vMax = v; }
  vMin = Math.floor((vMin - 4) / 5) * 5;
  vMax = Math.ceil((vMax + 4) / 5) * 5;
  if (vMax - vMin < 10) { const c = (vMax + vMin) / 2; vMin = c - 5; vMax = c + 5; }
  const X = (t) => padL + ((t - tMin) / (tMax - tMin || 1)) * (W - padL - padR);
  const Y = (v) => padT + ((vMax - v) / (vMax - vMin)) * (H - padT - padB);
  const line = (get, col) => {
    const pp = pts.filter((p) => get(p) != null);
    if (!pp.length) return "";
    let d = "";
    pp.forEach((p, i) => { d += `${i === 0 ? "M" : "L"}${X(p.t).toFixed(1)},${Y(get(p)).toFixed(1)} `; });
    return `<path d="${d}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
  };
  const dots = (get, col) => pts.filter((p) => get(p) != null).map((p) => `<circle cx="${X(p.t).toFixed(1)}" cy="${Y(get(p)).toFixed(1)}" r="3" fill="${col}"/>`).join("");
  let grid = "";
  for (let v = vMin; v <= vMax; v += 5) {
    grid += `<line x1="${padL}" y1="${Y(v)}" x2="${W - padR}" y2="${Y(v)}" stroke="var(--line)" stroke-width="1"/>`;
    grid += `<text x="${padL - 6}" y="${Y(v) + 3}" font-size="9" font-weight="600" fill="var(--muted)" text-anchor="end" font-family="Source Code Pro,monospace">${v}</text>`;
  }
  const last = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:150px;display:block">
    ${grid}
    ${line((p) => p.d, "var(--d)")}${line((p) => p.r, "var(--r)")}${hasI ? line((p) => p.i, C_I) : ""}
    ${dots((p) => p.d, "var(--d)")}${dots((p) => p.r, "var(--r)")}${hasI ? dots((p) => p.i, C_I) : ""}
    <text x="${padL}" y="${padT - 6}" font-size="9" font-weight="700" fill="var(--d)" font-family="Source Code Pro,monospace">D</text>
    <text x="${padL + 16}" y="${padT - 6}" font-size="9" font-weight="700" fill="var(--r)" font-family="Source Code Pro,monospace">R</text>
    ${hasI ? `<text x="${padL + 32}" y="${padT - 6}" font-size="9" font-weight="700" fill="${C_I}" font-family="Source Code Pro,monospace">I</text>` : ""}
    <text x="${padL}" y="${H - 6}" font-size="9" font-weight="600" fill="var(--muted)" font-family="Source Code Pro,monospace">${last.dates}</text>
  </svg>`;
}

function raceDetailHTML(race) {
  const entry = racePollEntry(race);
  if (!entry || !Array.isArray(entry.polls) || !entry.polls.length) {
    return `<div class="race-detail empty">No individual polls available for ${race.state}${race.district ? " " + race.district : ""}.</div>`;
  }
  const hasI = entry.polls.some((p) => p.ind != null);
  const pv = (v) => (v != null ? fmt(v) + "%" : "—");
  const rows = entry.polls.map((p) => {
    const sides = [["D", p.dem], ["R", p.rep]];
    if (p.ind != null) sides.push(["I", p.ind]);
    const present = sides.filter((s) => s[1] != null).sort((a, b) => b[1] - a[1]);
    const lead = present[0] || ["?", 0], second = present[1] || ["?", 0];
    const margin = (lead[1] - second[1]).toFixed(1);
    const col = lead[0] === "D" ? "d" : lead[0] === "R" ? "r" : "";
    const style = lead[0] === "I" ? ` style="color:${C_I}"` : "";
    const spon = p.partisan ? ` <span style="color:#8A6A17;font-weight:700" title="Partisan-sponsored poll (${p.partisan})">(${p.partisan})</span>` : "";
    return `<tr>
      <td>${p.pollster || "—"}${spon}</td>
      <td class="num">${p.dates || "—"}</td>
      <td class="num d">${pv(p.dem)}</td>
      <td class="num r">${pv(p.rep)}</td>
      ${hasI ? `<td class="num" style="color:${C_I}">${pv(p.ind)}</td>` : ""}
      <td class="num ${col}"${style}>${lead[0]}+${margin}</td>
    </tr>`;
  }).join("");
  return `<div class="race-detail">
    <div class="rd-head"><span class="rd-title">Polling — ${race.state}${race.district ? " " + race.district : ""}</span>
      <span class="rd-note">${entry.source}${entry.n_polls ? " · " + entry.n_polls + " polls" : ""}${entry.n_sponsored ? " · incl. " + entry.n_sponsored + " partisan" : ""}</span></div>
    <div class="rd-graph">${pollTrendSVG(entry.polls)}</div>
    <table class="rd-table">
      <thead><tr><th>Pollster</th><th>Dates</th><th>D</th><th>R</th>${hasI ? "<th>I</th>" : ""}<th>Margin</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function captureMap() {
  const svg = document.querySelector(".map-svg");
  if (!svg) return;
  const geo = state.geo;
  const W = geo.w, H = geo.h, scale = 2;
  const c = document.createElement("canvas");
  c.width = W * scale; c.height = H * scale;
  const ctx = c.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#F4F1E9";
  ctx.fillRect(0, 0, W, H);
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", W); clone.setAttribute("height", H);
  const css = document.createElementNS("http://www.w3.org/2000/svg", "style");
  css.textContent = ".st{stroke:#fff;stroke-width:0.6}.dist{stroke:#fff;stroke-width:0.4}.sub{stroke:#151515;stroke-width:1;fill:none;opacity:0.45}.land{fill:#ECE8DD;stroke:#fff;stroke-width:0.6}";
  clone.insertBefore(css, clone.firstChild);
  const data = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0, W, H);
    c.toBlob((b) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = `600mt-${state.chamber}-forecast.png`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(data);
}

function mapReset() { state.zoom = null; render(); }

function render() {
  const f = state.forecast;
  if (!f) return;
  const data = f[state.chamber];
  const pane = document.getElementById("pane-" + state.chamber);
  const headerCard = state.chamber === "governor" ? governorCard(data) : controlCard(data);

  let races = data.races.slice();
  if (state.sort === "close") races.sort((a, b) => Math.abs(a.margin) - Math.abs(b.margin));
  else if (state.sort === "rd") races.sort((a, b) => b.dem_pct - a.dem_pct);
  else if (state.sort === "rr") races.sort((a, b) => a.dem_pct - b.dem_pct);

  const sortSel = `<select class="select" onchange="setSort(this.value)" title="Sort races">
      <option value="close" ${state.sort === "close" ? "selected" : ""}>Closest races first</option>
      <option value="rd" ${state.sort === "rd" ? "selected" : ""}>Democrats favoured first</option>
      <option value="rr" ${state.sort === "rr" ? "selected" : ""}>Republicans favoured first</option>
    </select>`;

  const mapHtml = state.geo ? mapCard(data) : "";

  const table = `<div class="card">
    <div class="card-head"><span class="bar"></span><div class="t">Every ${US_LABELS[state.chamber].toLowerCase()} race</div></div>
    <p class="note">${data.races.length} races &middot; sorted ${state.sort === "close" ? "by closeness" : state.sort === "rd" ? "by Democratic probability" : "by Republican probability"} &middot; click a row to see it on the map, click again to open the polling.</p>
    <div class="toggle-flow">${sortSel}</div>
    <table>
      <thead><tr><th>Race</th><th>600 rating</th><th>Polling average</th><th>Win probability</th></tr></thead>
      <tbody>${races.map(raceRow).join("")}</tbody>
    </table>
    <div class="legend">
      <span><span class="sw d"></span>Democrats</span>
      <span><span class="sw r"></span>Republicans</span>
      <span>Bars are the model's win chance; the tick marks 50%.</span>
    </div>
  </div>`;

  const env = f.environment ? `generic ballot ${fmt(f.environment.generic_ballot_generic_margin)} D` : "";
  const maj = data.majority || {};
  const govD = data.total_d_governors, govR = data.total_r_governors;
  const hasMajPct = maj.dem_pct != null;
  const dVal = state.chamber === "governor" ? govD : (hasMajPct ? maj.dem_pct : data.expected_d_seats);
  const rVal = state.chamber === "governor" ? govR : (hasMajPct ? maj.rep_pct : data.expected_r_seats);
  const pct = state.chamber === "governor" ? "" : '<span class="pct">%</span>';
  const statusBar = `<div class="statusbar">
    <div class="sb-seg d"><span class="v">${fmt(dVal)}${pct}</span><span class="k">Democrats</span></div>
    <div class="sb-seg r"><span class="v">${fmt(rVal)}${pct}</span><span class="k">Republicans</span></div>
    <div class="sb-seats">${state.chamber === "governor"
      ? `Expected governors: <b class="d">${fmt(govD)}</b> &ndash; <b class="r">${fmt(govR)}</b> (of 50)`
      : `Expected: <b class="d">${fmt(data.expected_d_seats)}</b> &ndash; <b class="r">${fmt(data.expected_r_seats)}</b>${(data.expected_i_seats || 0) > 0.05 ? ` seats (incl. <span style="color:${C_I};font-weight:700">${fmt(data.expected_i_seats)}</span> I)` : " seats"}`}</div>
    <div class="sb-maj">${state.chamber === "house" ? "218 for majority" : state.chamber === "senate" ? "51 for D majority" : "36 of 50 governorships up"}</div>
  </div>`;

  const total = state.chamber === "house" ? 435 : state.chamber === "senate" ? 100 : 50;
  const marker = state.chamber === "house" ? 218 : state.chamber === "senate" ? 51 : null;
  const dist = (data.distribution_buckets || []).length
    ? `<div class="card">
        <div class="card-head"><span class="bar"></span><div class="t">Seat distribution</div></div>
        <p class="note">Share of simulated election nights producing each number of Democratic ${state.chamber === "governor" ? "governors" : "seats"} (2-seat buckets).</p>
        <div class="chart">${distributionSVG(data, total, marker)}</div>
      </div>`
    : "";

  pane.innerHTML = `
    ${statusBar}
    <div class="layout-2col">
      <div class="col-a">
        <div class="card">
          <div class="card-head"><span class="bar"></span><div class="t">Race for the ${state.chamber === "house" ? "U.S. House" : state.chamber === "senate" ? "U.S. Senate" : "governors' mansions"}</div></div>
          <p class="note">The chance shown is the share of 20,000 simulated election nights in which each party wins the chamber — accounting for the ${env} environment.</p>
          ${headerCard}
        </div>
      </div>
      <div class="col-b">${mapHtml}</div>
    </div>
    ${dist}
    ${table}
    <p class="foot">
      Method: Senate races start from the state's lean in the last presidential
      election, adjusted for the national environment (scaled by the state's
      historical elasticity), incumbency and trend. House races start from the
      district's last presidential margin (The Downballot, 2026 lines), the last
      House result and the rating band. Governor races start from the state's
      last presidential lean, the rating band and incumbency. Polls are rebuilt from the individual
      surveys with recency and partisan weighting and an outlier guard, then
      blended. The simulation runs
      (${fmt(f.environment ? f.environment.n_sims : 20000)} nights, national swing &sigma; = ${fmt(f.environment ? f.environment.national_swing_sigma : 2.5)} pts${f.environment && f.environment.poll_bias_sigma ? `, poll-bias &sigma; = ${fmt(f.environment.poll_bias_sigma)} pts` : ""}${f.environment && f.environment.state_swing_sigma ? `, plus a correlated per-state deviation &sigma; = ${fmt(f.environment.state_swing_sigma)} pts` : ""}).
      Races without public polling are shown as &ldquo;&mdash;&rdquo;; their probability comes from the fundamentals alone.
      Sources: Wikipedia (2026 Senate, House and gubernatorial election articles and ratings), The Downballot's district presidential results, and the generic-ballot aggregates.
      Model generated: ${f.generated ? new Date(f.generated).toUTCString() : "—"}.
      Want to disagree? <a href="map.html"><b>Paint the map yourself &rarr;</b></a>
    </p>`;

  if (state.geo) {
    const stage = pane.querySelector(".map-stage");
    stage.innerHTML = buildMapHTML(data);
    attachMap(pane, data);
  }
  attachRows(pane, data);
}

function attachRows(pane, data) {
  pane.querySelectorAll("tr[data-key]").forEach((tr) => {
    tr.addEventListener("mouseenter", () => {
      const el = pane.querySelector(`.map-svg [data-race="${CSS.escape(tr.getAttribute("data-key"))}"]`);
      if (el) el.classList.add("focus");
    });
    tr.addEventListener("mouseleave", () => { pane.querySelectorAll(".map-svg .focus").forEach((p) => p.classList.remove("focus")); });
    tr.addEventListener("click", () => {
      const key = tr.getAttribute("data-key");
      if (state.chamber === "house" && state.zoom === null) {
        const race = raceByKey(data, key);
        if (race) { state.zoom = state.geo.states.findIndex((s) => s.name === race.state); render(); return; }
      }
      selectRace(pane, key);
      toggleRaceDetail(tr, raceByKey(data, key));
    });
  });
}

function toggleRaceDetail(tr, race) {
  if (!race) return;
  const pane = tr.closest(".pane");
  pane.querySelectorAll(".detail-row").forEach((r) => { if (r !== tr.nextElementSibling) r.remove(); });
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains("detail-row")) { existing.remove(); return; }
  const detail = document.createElement("tr");
  detail.className = "detail-row";
  detail.innerHTML = `<td colspan="6">${raceDetailHTML(race)}</td>`;
  tr.after(detail);
  tr.scrollIntoView({ behavior: "smooth", block: "center" });
}

function setSort(v) { state.sort = v; render(); }

function selectChamber(ch) {
  state.chamber = ch;
  state.zoom = null;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.chamber === ch));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + ch));
  render();
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => selectChamber(t.dataset.chamber)));

Promise.all([
  fetch(US_DATA, { cache: "no-store" }),
  fetch(US_GEO, { cache: "no-store" }),
  fetch(US_POLLS, { cache: "no-store" }),
])
  .then(([rf, rg, rp]) => Promise.all([rf.json(), rg.json(), rp.json()]))
  .then(([f, g, p]) => {
    state.forecast = f;
    state.geo = g;
    state.polls = p;
    const up = document.getElementById("updated");
    if (up) up.innerHTML = `Model generated <b>${new Date(f.generated).toUTCString()}</b>`;
    const gen = document.getElementById("generic");
    if (gen && f.environment) gen.textContent = fmt(f.environment.generic_ballot_generic_margin);
    render();
  })
  .catch((err) => {
    document.getElementById("pane-senate").innerHTML = '<div class="load">Could not load the forecast data.</div>';
    console.error(err);
  });
