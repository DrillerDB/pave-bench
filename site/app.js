/* PaveBench site: renders the leaderboard, frontier chart and case table from the
   results bundle the build step embeds (results/leaderboard.json + site/content.json). */
(function () {
  "use strict";
  const BUNDLE = JSON.parse(document.getElementById("pb-data").textContent);
  const DATA = BUNDLE.results;
  const CONTENT = BUNDLE.content;
  const META = DATA.meta || {};
  const VENDOR_COLOR = { OpenAI: "var(--openai)", Google: "var(--google)", Anthropic: "var(--anthropic)", Meta: "var(--meta)" };
  const color = (p) => VENDOR_COLOR[p] || "var(--other)";
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (v, d = 0) => (v == null ? "–" : (v * 100).toFixed(d) + "%");
  const secs = (ms) => (ms == null ? "–" : ms < 10000 ? (ms / 1000).toFixed(1) + " s" : Math.round(ms / 1000) + " s");
  const usd = (v) => (v == null ? "–" : "$" + (v < 0.01 ? v.toFixed(4) : v < 1 ? v.toFixed(3) : v.toFixed(2)));
  const tip = document.getElementById("tip");

  // ---- Rows per task -------------------------------------------------------
  const judged = (DATA.judged || [])[0] || null;
  const ROWS = {
    area: DATA.tasks.area.map((r) => ({ ...r, cost: r.cost, time: r.p50 })),
    stall: DATA.tasks.stall.map((r) => ({ ...r, time: r.p50 })),
    stripe: judged
      ? judged.systems.filter((s) => s.meanUsability != null).map((s) => ({
          system: s.system, provider: s.provider || "Other", notes: s.note || "", excluded: false,
          accuracy: s.meanUsability / 10, usability: s.meanUsability, win: s.winRateVsReference,
          hatch: s.faults?.hatchingOutlineOrMissingRate, rowsMissed: s.faults?.rowsMissedMean,
          cost: s.meanCostUsd, time: s.p50LatencyMs, comparisons: s.comparisons,
        }))
      : [],
  };

  function shortName(name) {
    return name
      .replace("Gemini 4 Argon", "Argon").replace(/^Claude /, "")
      .replace(", image at 1568 px", " (1568 px)").replace("geometry hint + 1 retry", "hint + retry")
      .replace("high thinking", "high think").replace("0-1000 grid", "grid");
  }

  function pareto(rows, key) {
    const pts = rows.filter((r) => !r.excluded && r[key] != null && r[key] > 0).sort((a, b) => a[key] - b[key] || b.accuracy - a.accuracy);
    const out = []; let best = -Infinity;
    for (const r of pts) if (r.accuracy > best) { out.push(r); best = r.accuracy; }
    return out;
  }

  const TASKS = {
    area: {
      blurb: "Trace the paved area around a tapped point with islands cut out. Ranked by mean overlap (IoU) with the hand trace over every try.",
      acc: "Mean IoU",
      cols: [
        ["Mean IoU", (r) => r.accuracy, (r) => `<span class="bar" style="width:${Math.round(r.accuracy * 60)}px"></span>${r.accuracy.toFixed(3)}`],
        ["Pass", (r) => r.passRate, (r) => pct(r.passRate)],
        ["Usable", (r) => r.valid, (r) => pct(r.valid), (r) => r.valid < 0.9],
        ["Islands found", (r) => r.cutoutRecovery, (r) => pct(r.cutoutRecovery)],
        ["Area error", (r) => -(r.medianAreaDelta ?? 9), (r) => pct(r.medianAreaDelta, 1)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost / lot", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
      note: "Pass: IoU of at least 0.86, area within 8%, islands within two, and the tapped point inside. Usable: the polygon is a simple outline with islands inside it. Time is the median per try; cost is the mean per try at list price.",
    },
    stall: {
      blurb: "Count the marked stalls inside a lot. Ranked by count accuracy (1 minus the mean count error against the hand count) over every try.",
      acc: "Count accuracy",
      cols: [
        ["Accuracy", (r) => r.accuracy, (r) => `<span class="bar" style="width:${Math.round(r.accuracy * 60)}px"></span>${pct(r.accuracy, 1)}`],
        ["Mean error", (r) => -r.meanErr, (r) => pct(r.meanErr, 1)],
        ["Within 10%", (r) => r.passRate, (r) => pct(r.passRate)],
        ["p90 error", (r) => -r.p90Err, (r) => pct(r.p90Err)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost / lot", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
      note: "These lots have hand counts but no per-stall markers yet, so a count in the right total with stalls in the wrong places is not caught by the score. Systems known to misplace stalls are held off the frontier.",
    },
    stripe: {
      blurb: judged ? `No hand-traced stripe answers exist yet. ${judged.judge === "claude-opus-5-5" ? "Claude Opus 5.5" : judged.judge} compares each drawing with ${judged.reference}'s on the same lot, blind and in both orders. Ranked by mean usability for a restripe quote (0 to 10).` : "",
      acc: "Judged usability",
      cols: [
        ["Usability", (r) => r.usability, (r) => `<span class="bar" style="width:${Math.round(r.usability * 6)}px"></span>${r.usability.toFixed(1)}`],
        ["Preferred over ref.", (r) => r.win ?? 0.5, (r) => (r.win == null ? "reference" : pct(r.win))],
        ["Hatch as outline only", (r) => -(r.hatch ?? 0), (r) => pct(r.hatch)],
        ["Rows missed", (r) => -(r.rowsMissed ?? 0), (r) => (r.rowsMissed ?? 0).toFixed(1)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost / lot", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
      note: judged ? `Calibration: ${judged.reference} against its own second try was preferred ${pct(judged.calibration?.referenceSelfWinRate)} of the time (a fair judge is near 50%), and the judge gave the same verdict in both orders on ${pct(judged.calibration?.orderAgreement)} of ${judged.calibration?.pairs} pairs. A try that returned no drawing counts as a loss with usability 0.` : "",
    },
  };

  // ---- Title block and findings -------------------------------------------
  const tb = document.getElementById("titleblock");
  const byTask = META.casesByTask || {};
  const facts = [
    ["Edition", CONTENT.edition],
    ["Systems", `${META.systems} from ${(META.providers || []).length} vendors`],
    ["Test lots", `${META.cases} private, 1 public`],
    ["Imagery", META.gsdRangeCm ? `${META.gsdRangeCm[0]}–${META.gsdRangeCm[1]} cm per pixel` : "–"],
  ];
  tb.innerHTML = facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");
  document.getElementById("findings").innerHTML = (CONTENT.findings || []).map((f) => `<li><span class="big">${esc(f.big)}</span><p>${esc(f.text)}</p></li>`).join("");
  document.getElementById("board-sub").textContent = `${META.setName || "Results"}, updated ${META.updated}. ${META.setDescription || ""} These are unofficial results: the imagery cannot be redistributed.`;

  // ---- Leaderboard ----------------------------------------------------------
  const vendors = [...new Set(Object.values(ROWS).flat().map((r) => r.provider))].sort();
  const shown = new Set(vendors);
  let task = "area";
  let sortCol = 0, sortDir = -1;
  const filters = document.getElementById("filters");
  filters.innerHTML = vendors.map((v) => `<button class="chip" type="button" data-v="${esc(v)}" aria-pressed="true"><i style="background:${color(v)}"></i>${esc(v)}</button>`).join("");
  filters.addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    const v = b.dataset.v;
    if (shown.has(v) && shown.size > 1) shown.delete(v); else shown.add(v);
    filters.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(shown.has(c.dataset.v))));
    renderTable(); renderChart();
  });

  function renderTable() {
    const cfg = TASKS[task];
    const all = ROWS[task];
    const front = new Set(pareto(all, "cost").map((r) => r.system));
    const rows = all.filter((r) => shown.has(r.provider)).sort((a, b) => sortDir * (cfg.cols[sortCol][1](b) - cfg.cols[sortCol][1](a)) * -1 || b.accuracy - a.accuracy);
    const ranked = [...all].sort((a, b) => b.accuracy - a.accuracy);
    const head = `<thead><tr><th scope="col">#</th><th scope="col">System</th>${cfg.cols.map((c, i) => `<th scope="col"><button type="button" data-col="${i}"${i === sortCol ? ` data-dir="${sortDir < 0 ? "↓" : "↑"}"` : ""}>${esc(c[0])}</button></th>`).join("")}</tr></thead>`;
    const body = rows.map((r) => {
      const rank = ranked.indexOf(r) + 1;
      const badge = front.has(r.system) ? '<span class="badge">frontier</span>' : r.excluded ? '<span class="badge off">held off frontier</span>' : "";
      const note = [r.notes, r.excluded ? "Held off the frontier: " + r.frontierNote : ""].filter(Boolean).join(" ");
      return `<tr class="${rank === 1 ? "top" : ""}"><td class="rank">${rank}</td><td class="sys"><span class="vdot" style="background:${color(r.provider)}"></span><span class="sysname">${esc(r.system)}</span><span class="vendor">${esc(r.provider)}</span>${badge}${note ? `<span class="note" title="${esc(note)}">${esc(note)}</span>` : ""}</td>${cfg.cols.map((c) => `<td class="${c[3] && c[3](r) ? "bad" : ""}">${c[2](r)}</td>`).join("")}</tr>`;
    }).join("");
    const t = document.getElementById("lb");
    t.innerHTML = head + `<tbody>${body}</tbody>`;
    t.querySelectorAll("th button").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.col);
      if (i === sortCol) sortDir = -sortDir; else { sortCol = i; sortDir = -1; }
      renderTable();
    }));
    document.getElementById("task-blurb").textContent = cfg.blurb;
    document.getElementById("table-note").textContent = cfg.note;
  }

  document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => setTask(b.dataset.task)));
  function setTask(t) {
    task = t; sortCol = 0; sortDir = -1;
    document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.task === t)));
    document.getElementById("panel").setAttribute("aria-labelledby", "tab-" + t);
    document.querySelectorAll("#seg-task button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.task === t)));
    renderTable(); renderChart();
  }

  // ---- Frontier chart -------------------------------------------------------
  let axis = "cost";
  const svg = document.getElementById("chart");
  document.querySelectorAll("#seg-task button").forEach((b) => b.addEventListener("click", () => setTask(b.dataset.task)));
  document.querySelectorAll("#seg-axis button").forEach((b) => b.addEventListener("click", () => {
    axis = b.dataset.axis;
    document.querySelectorAll("#seg-axis button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.axis === axis)));
    renderChart();
  }));

  function renderChart() {
    const key = axis === "cost" ? "cost" : "time";
    const rows = ROWS[task].filter((r) => shown.has(r.provider) && r[key] > 0);
    const W = 1100, H = 520, L = 64, R = 24, T = 20, B = 56, pw = W - L - R, ph = H - T - B;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const xs = rows.map((r) => r[key]);
    if (!xs.length) { svg.innerHTML = ""; return; }
    const lo = Math.min(...xs) / 1.8, hi = Math.max(...xs) * 1.8;
    const yMin = Math.max(0, Math.floor((Math.min(...rows.map((r) => r.accuracy)) - 0.05) * 10) / 10);
    const sx = (v) => L + ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * pw;
    const sy = (v) => T + (1 - (v - yMin) / (1 - yMin)) * ph;
    let g = `<title id="chart-title">${esc(TASKS[task].acc)} against ${axis === "cost" ? "cost" : "time"} per lot</title>`;
    g += `<rect class="good" x="${L}" y="${T}" width="${pw * 0.38}" height="${ph * 0.38}"/>`;
    for (let e = Math.floor(Math.log10(lo)); 10 ** e <= hi; e++) for (const m of [1, 2, 5]) {
      const v = m * 10 ** e; if (v < lo || v > hi) continue;
      const label = axis === "cost" ? usd(v).replace(/0+$/, "").replace(/\.$/, "") : (key === "time" ? (v / 1000) + " s" : v);
      g += `<line class="gl" x1="${sx(v)}" x2="${sx(v)}" y1="${T}" y2="${T + ph}"/><text class="ax" x="${sx(v)}" y="${T + ph + 18}" text-anchor="middle">${label}</text>`;
    }
    for (let v = yMin; v <= 1.0001; v += 0.1) g += `<line class="gl" x1="${L}" x2="${L + pw}" y1="${sy(v)}" y2="${sy(v)}"/><text class="ax" x="${L - 8}" y="${sy(v) + 4}" text-anchor="end">${task === "stripe" ? (v * 10).toFixed(0) : v.toFixed(1)}</text>`;
    g += `<rect class="frame" x="${L}" y="${T}" width="${pw}" height="${ph}"/>`;
    const front = pareto(rows, key);
    const on = new Set(front.map((r) => r.system));
    if (front.length > 1) {
      let d = "";
      front.forEach((r, i) => { d += (i ? ` L${sx(r[key])},${sy(front[i - 1].accuracy)} L` : "M") + `${sx(r[key])},${sy(r.accuracy)}`; });
      d += ` L${L + pw},${sy(front[front.length - 1].accuracy)}`;
      g += `<path class="front" d="${d}"/>`;
    }
    const ordered = [...rows].sort((a, b) => (on.has(a.system) ? 1 : 0) - (on.has(b.system) ? 1 : 0));
    ordered.forEach((r) => {
      g += `<circle class="pt${on.has(r.system) ? " on" : ""}" data-s="${esc(r.system)}" cx="${sx(r[key])}" cy="${sy(Math.max(yMin, r.accuracy))}" r="${on.has(r.system) ? 8 : 6.5}" fill="${color(r.provider)}"/>`;
    });
    // Label frontier points directly, with short names and a greedy nudge so labels
    // never overlap each other or run off the plot.
    const placed = [];
    front.forEach((r) => {
      const x = sx(r[key]), y = sy(Math.max(yMin, r.accuracy));
      const text = shortName(r.system);
      const w = text.length * 6.9, h = 15;
      const anchor = x + 12 + w > L + pw ? "end" : "start";
      const left = anchor === "end" ? x - 12 - w : x + 12;
      let ty = y - 10;
      for (let k = 0; k < 12 && placed.some((p) => left < p.r && left + w > p.l && ty - h < p.b && ty > p.t); k++) ty += h + 2;
      placed.push({ l: left, r: left + w, t: ty - h, b: ty });
      g += `<text class="lab" x="${anchor === "end" ? x - 12 : x + 12}" y="${ty}" text-anchor="${anchor}">${esc(text)}</text>`;
    });
    g += `<text class="axl" x="${L + pw / 2}" y="${H - 10}" text-anchor="middle">${axis === "cost" ? "Mean cost per lot (log scale, left is better)" : "Median time per lot (log scale, left is better)"}</text>`;
    g += `<text class="axl" transform="translate(16 ${T + ph / 2}) rotate(-90)" text-anchor="middle">${esc(TASKS[task].acc)}${task === "stripe" ? " (0–10)" : ""}, up is better</text>`;
    svg.innerHTML = g;
    svg.querySelectorAll(".pt").forEach((p) => {
      const r = rows.find((x) => x.system === p.dataset.s);
      const show = (e) => {
        tip.hidden = false;
        tip.innerHTML = `<b>${esc(r.system)}</b> · ${esc(r.provider)}<br>${esc(TASKS[task].acc)}: ${task === "stripe" ? r.usability.toFixed(1) : task === "stall" ? pct(r.accuracy, 1) : r.accuracy.toFixed(3)}<br>${usd(r.cost)} per lot · ${secs(r.time)} median`;
        tip.style.left = Math.min(e.clientX + 14, innerWidth - 310) + "px";
        tip.style.top = e.clientY + 14 + "px";
      };
      p.addEventListener("mousemove", show);
      p.addEventListener("mouseleave", () => (tip.hidden = true));
    });
    const noCost = ROWS[task].filter((r) => shown.has(r.provider) && !(r.cost > 0)).map((r) => r.system);
    document.getElementById("chart-note").textContent = axis === "cost" && noCost.length ? `Not on the cost chart (no per-call price): ${noCost.join(", ")}.` : "";
  }

  // ---- Cases table, citation -------------------------------------------------
  const spec = [
    ["Private test split v0", `${META.cases} lots, ${byTask.click_connected_polygon || 0} with hand-traced outlines and ${byTask.stall_count || 0} with hand counts; ${byTask.stripe_lines || 0} lots judged for striping`],
    ["Imagery (test split)", `Mapbox Satellite, ${META.gsdRangeCm ? META.gsdRangeCm.join("–") : "–"} cm per pixel; not redistributed`],
    ["Public development split", "Justice, Illinois (Cook County 2025 orthophoto, public domain, 15 cm) and a synthetic demo case"],
    ["Tries per lot", "3 for outlines and stall counts, 2 for striping"],
    ["Systems in this edition", `${META.systems}: ${(META.providers || []).join(", ")}`],
  ];
  document.getElementById("spec").innerHTML = spec.map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  document.getElementById("copy-bib").addEventListener("click", (e) => {
    const text = document.getElementById("bib").textContent;
    const done = () => { e.target.textContent = "Copied"; setTimeout(() => (e.target.textContent = "Copy citation"), 1600); };
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(done, () => {
      const range = document.createRange(); range.selectNodeContents(document.getElementById("bib"));
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    });
  });

  renderTable();
  renderChart();
})();
