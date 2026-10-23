/* Race detail page: ?chamber=senate|house|governor&state=...&district=... */
(function () {
  const params = new URLSearchParams(location.search);
  const chamber = ["senate", "house", "governor"].includes(params.get("chamber"))
    ? params.get("chamber") : "senate";
  const stateName = params.get("state") || "";
  const district = params.get("district") || "";
  const root = document.getElementById("race");

  const money = (v) => {
    if (v == null) return "—";
    if (v >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
    if (v >= 1e3) return "$" + (v / 1e3).toFixed(0) + "K";
    return "$" + v.toFixed(0);
  };

  Promise.all([
    fetch("data/us/forecast.json", { cache: "no-store" }).then((r) => r.json()),
    fetch("data/us/polling.json", { cache: "no-store" }).then((r) => r.json()),
    fetch(chamber === "house" ? "data/us/house_fundraising.json"
      : "data/us/senate_fundraising.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([fc, polls, fec]) => {
    const races = (fc[chamber] && fc[chamber].races) || [];
    const race = races.find((r) => r.state === stateName
      && String(r.district || "") === district);
    if (!race) {
      document.getElementById("rtitle").textContent = "Race not found";
      document.getElementById("rlede").textContent = "Check the chamber, state and district.";
      return;
    }
    state.forecast = fc;
    state.polls = polls;
    state.chamber = chamber;

    const name = race.district ? `${race.state} ${race.district}` : race.state;
    document.getElementById("rkicker").textContent =
      `2026 ${chamber === "house" ? "U.S. House" : chamber === "senate" ? "U.S. Senate" : "governor"}`;
    document.getElementById("rtitle").innerHTML = name;
    const lead = race.leader || (race.margin >= 0 ? "D" : "R");
    document.getElementById("rlede").textContent =
      `${race.lean || race.rating || "No rating"} · ${lead}+${fmt(Math.abs(race.margin))} model margin`
      + (race.incumbent ? ` · ${race.incumbent}` : "");

    const ratings = race.ratings || {};
    const ratingBits = [["Cook", ratings.cook], ["IE", ratings.ie], ["Sabato", ratings.sabato]]
      .filter((x) => x[1]).map((x) => `${x[0]}: ${x[1]}`).join(" · ") || "No published rating";
    const calNote = race.calibration
      ? `<p class="note cal-note"><b>Calibration:</b> ${race.calibration.reason || "manual input adjustment"}</p>`
      : "";

    let fecHtml = "";
    if (fec && fec.cycles && fec.cycles["2026"]) {
      const c = fec.cycles["2026"];
      let entry;
      if (chamber === "house") {
        let cd = district === "at-large" ? "00" : String(district || "").padStart(2, "0");
        entry = (c[stateName] || {})[cd];
      } else {
        entry = c[stateName];
      }
      if (entry && (entry.DEM || entry.REP)) {
        fecHtml = `<div class="card">
          <div class="card-head"><span class="bar"></span><div class="t">Candidate fundraising</div></div>
          <p class="note">FEC receipts, highest-raising Democrat and Republican in this race.</p>
          <table><thead><tr><th>Party</th><th>Candidate</th><th>Receipts</th></tr></thead><tbody>
            <tr><td>Democrat</td><td>${(entry.DEM || {}).name || "—"}</td><td class="num">${money((entry.DEM || {}).receipts)}</td></tr>
            <tr><td>Republican</td><td>${(entry.REP || {}).name || "—"}</td><td class="num">${money((entry.REP || {}).receipts)}</td></tr>
          </tbody></table></div>`;
      }
    }

    const iBit = (race.ind_pct || 0) > 0.5
      ? `<div class="cell"><div class="big">${fmt(race.ind_pct)}%</div><div class="lbl">Independent</div></div>` : "";

    root.innerHTML = `
      <div class="card">
        <div class="card-head"><span class="bar"></span><div class="t">Model</div></div>
        <div class="ctl">
          <div class="cell d"><div class="big">${fmt(race.dem_pct)}<span class="pct">%</span></div><div class="lbl">Democrats win</div></div>
          <div class="cell r"><div class="big">${fmt(race.rep_pct)}<span class="pct">%</span></div><div class="lbl">Republicans win</div></div>
          ${iBit}
          <div class="line">Margin <b>${lead}+${fmt(Math.abs(race.margin))}</b> · ${race.lean || race.rating || "No rating"}. Ratings — ${ratingBits}.</div>
          ${calNote}
        </div>
      </div>
      ${fecHtml}
      ${raceDetailHTML(race)}`;
  }).catch((err) => {
    root.innerHTML = '<div class="load">Could not load this race.</div>';
    console.error(err);
  });
})();
