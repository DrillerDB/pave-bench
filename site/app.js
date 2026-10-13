/* PaveBench site: renders the leaderboard bars, the score-vs-cost chart and the
   all-setups table from the results bundle the build step embeds
   (results/leaderboard.json + site/content.json). Charts show each model's best
   setup; the table lists every setup. */
(function () {
  "use strict";
  const BUNDLE = JSON.parse(document.getElementById("pb-data").textContent);
  const DATA = BUNDLE.results;
  const META = DATA.meta || {};
  const VENDOR_COLOR = { OpenAI: "var(--openai)", Google: "var(--google)", Anthropic: "var(--anthropic)", Meta: "var(--meta)" };
  const color = (p) => VENDOR_COLOR[p] || "var(--other)";
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (v, d = 0) => (v == null ? "–" : (v * 100).toFixed(d) + "%");
  const secs = (ms) => (ms == null ? "–" : ms < 10000 ? (ms / 1000).toFixed(1) + " s" : Math.round(ms / 1000) + " s");
  const usd = (v) => (v == null ? "flat fee" : "$" + (v < 0.01 ? v.toFixed(4).replace(/0+$/, "") : v < 0.1 ? v.toFixed(3) : v.toFixed(2)));
  const modelOf = (s) => s.split(",")[0].trim();
  const setupOf = (s) => (s.includes(",") ? s.slice(s.indexOf(",") + 1).trim() : "");
  const providerOf = (s) => (/^GPT/.test(s) ? "OpenAI" : /^Gemini/.test(s) ? "Google" : /^Claude/.test(s) ? "Anthropic" : /^Muse/.test(s) ? "Meta" : "Other");
  const tip = document.getElementById("tip");
  const date = (iso) => new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

  // ---- Rows per task -------------------------------------------------------
  const judged = (DATA.judged || [])[0] || null;
  const ROWS = {
    composite: (DATA.tasks.composite || []).map((r) => ({ ...r, time: r.p50 })),
    area: DATA.tasks.area.map((r) => ({ ...r, time: r.p50 })),
    stall: DATA.tasks.stall.map((r) => ({ ...r, time: r.p50 })),
    stripe: judged
      ? judged.systems.filter((s) => s.meanUsability != null).map((s) => ({
          system: s.system, provider: providerOf(s.system), excluded: false,
          accuracy: s.meanUsability / 10, usability: s.meanUsability, win: s.winRateVsReference,
          hatch: s.faults?.hatchingOutlineOrMissingRate, rowsMissed: s.faults?.rowsMissedMean,
          cost: s.meanCostUsd, time: s.p50LatencyMs,
        }))
      : [],
  };

  function bestPerModel(rows) {
    const best = new Map();
    for (const r of rows) {
      if (r.excluded) continue;
      const m = modelOf(r.system);
      if (!best.has(m) || r.accuracy > best.get(m).accuracy) best.set(m, r);
    }
    return [...best.values()];
  }

  function pareto(rows, key) {
    const pts = rows.filter((r) => r[key] > 0).sort((a, b) => a[key] - b[key] || b.accuracy - a.accuracy);
    const out = []; let best = -Infinity;
    for (const r of pts) if (r.accuracy > best) { out.push(r); best = r.accuracy; }
    return out;
  }

  const bar = (v, w) => `<span class="bar" style="width:${Math.round(v * w)}px"></span>`;
  const TASKS = {
    composite: {
      head: "outline + stalls + striping, 1 is perfect", y: "score",
      value: (r) => r.accuracy, fmt: (r) => r.accuracy.toFixed(2), max: () => 1,
      score: (r) => r.accuracy.toFixed(3),
      cols: [
        ["Score", (r) => r.accuracy, (r) => bar(r.accuracy, 60) + r.accuracy.toFixed(3)],
        ["Outline", (r) => r.components.area, (r) => r.components.area.toFixed(3)],
        ["Stalls", (r) => r.components.stall, (r) => pct(r.components.stall, 1)],
        ["Striping", (r) => r.components.stripe, (r) => (r.components.stripe * 10).toFixed(1)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
    },
    area: {
      head: "IoU with the hand trace, 1 is perfect", y: "IoU",
      value: (r) => r.accuracy, fmt: (r) => r.accuracy.toFixed(3), max: () => 1,
      score: (r) => r.accuracy.toFixed(3),
      cols: [
        ["IoU", (r) => r.accuracy, (r) => bar(r.accuracy, 60) + r.accuracy.toFixed(3)],
        ["Pass", (r) => r.passRate, (r) => pct(r.passRate)],
        ["Valid", (r) => r.valid, (r) => pct(r.valid), (r) => r.valid < 0.9],
        ["Islands", (r) => r.cutoutRecovery, (r) => pct(r.cutoutRecovery)],
        ["Area error", (r) => -(r.medianAreaDelta ?? 9), (r) => pct(r.medianAreaDelta, 1)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
    },
    stall: {
      head: "mean miss vs. a hand count, lower is better", y: "count accuracy", asc: true,
      value: (r) => r.meanErr, fmt: (r) => pct(r.meanErr, 1), max: (rows) => Math.max(...rows.map((r) => r.meanErr)),
      score: (r) => pct(r.meanErr, 1) + " error",
      cols: [
        ["Error", (r) => -r.meanErr, (r) => bar(r.meanErr, 60) + pct(r.meanErr, 1)],
        ["Within 10%", (r) => r.passRate, (r) => pct(r.passRate)],
        ["p90 error", (r) => -r.p90Err, (r) => pct(r.p90Err)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
    },
    stripe: {
      head: "judged usability for a restripe quote, 0 to 10", y: "usability / 10",
      value: (r) => r.usability, fmt: (r) => r.usability.toFixed(1), max: () => 10,
      score: (r) => r.usability.toFixed(1) + " / 10",
      cols: [
        ["Usability", (r) => r.usability, (r) => bar(r.usability / 10, 60) + r.usability.toFixed(1)],
        ["Preferred", (r) => r.win ?? 0.5, (r) => (r.win == null ? "ref." : pct(r.win))],
        ["Hatch missed", (r) => -(r.hatch ?? 0), (r) => pct(r.hatch)],
        ["Rows missed", (r) => -(r.rowsMissed ?? 0), (r) => (r.rowsMissed ?? 0).toFixed(1)],
        ["Time", (r) => -(r.time ?? 1e12), (r) => secs(r.time)],
        ["Cost", (r) => -(r.cost ?? 1e9), (r) => usd(r.cost)],
      ],
    },
  };

  // ---- Static text from the data -------------------------------------------
  const byTask = META.casesByTask || {};
  document.getElementById("lede").textContent = `${META.systems} AI setups. Lot outline, stall count, striping.`;
  document.getElementById("board-sub").textContent = `Unofficial. ${META.cases} private lots, updated ${date(META.updated)}.`;
  const judgeName = judged && judged.judge === "claude-opus-5-5" ? "Claude Opus 5.5" : judged ? judged.judge : "";
  document.getElementById("judge-text").textContent = judged
    ? `No hand-traced stripes yet. ${judgeName} compares each drawing with ${judged.reference}'s, blind, in both orders.`
    : "";
  const facts = [
    ["Full takeoff", "Mean of the three job scores, each 0 to 1."],
    ["Cost", "API list price per lot. Flat fee: a subscription tool."],
    ["Test set", `${byTask.click_connected_polygon || 0} outline, ${byTask.stall_count || 0} stall and ${byTask.stripe_lines || 0} striping lots on Mapbox imagery (not redistributed), 2–3 tries each.`],
    ["Charts", "Best setup per model. Every setup is in the table."],
  ];
  document.getElementById("facts").innerHTML = facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");

  // ---- Tooltip ---------------------------------------------------------------
  function showTip(e, r) {
    tip.hidden = false;
    tip.innerHTML = `<b>${esc(modelOf(r.system))}</b>${setupOf(r.system) ? `<br>${esc(setupOf(r.system))}` : ""}<br>${esc(TASKS[task].score(r))}<br>${usd(r.cost)} per lot, ${secs(r.time)}`;
    tip.style.left = Math.max(8, Math.min(e.clientX + 14, innerWidth - 300)) + "px";
    tip.style.top = e.clientY + 14 + "px";
  }
  const hideTip = () => (tip.hidden = true);
  function bindTips(root, sel, find) {
    root.querySelectorAll(sel).forEach((el) => {
      const r = find(el.dataset.s);
      el.addEventListener("mousemove", (e) => showTip(e, r));
      el.addEventListener("click", (e) => showTip(e, r));
      el.addEventListener("mouseleave", hideTip);
    });
  }
  addEventListener("scroll", hideTip, { passive: true });

  // ---- Bars ------------------------------------------------------------------
  let task = "composite";
  function renderBars() {
    const cfg = TASKS[task];
    const rows = bestPerModel(ROWS[task]).sort((a, b) => (cfg.asc ? 1 : -1) * (cfg.value(a) - cfg.value(b)));
    const max = cfg.max(rows);
    const el = document.getElementById("bars");
    el.innerHTML = `<div class="bars-head"><span></span><span>${esc(cfg.head)}</span><span>cost per lot</span></div>` + rows.map((r) =>
      `<div class="bar-row" data-s="${esc(r.system)}"><span class="bn">${esc(modelOf(r.system))}</span>` +
      `<span class="bt"><i style="width:${(78 * cfg.value(r) / max).toFixed(1)}%;background:${color(r.provider)}"></i><b>${esc(cfg.fmt(r))}</b></span>` +
      `<span class="bc">${esc(usd(r.cost))}</span></div>`).join("");
    bindTips(el, ".bar-row", (s) => rows.find((r) => r.system === s));
  }

  // ---- Score vs. cost chart --------------------------------------------------
  let axis = "cost";
  const svg = document.getElementById("chart");
  const wrap = document.getElementById("chart-wrap");
  function renderChart() {
    const key = axis;
    const rows = bestPerModel(ROWS[task]).filter((r) => r[key] > 0);
    const W = Math.max(300, wrap.clientWidth - 16), H = Math.round(Math.min(520, Math.max(320, W * 0.52)));
    const narrow = W < 560;
    const L = 44, R = 14, T = 14, B = 40, pw = W - L - R, ph = H - T - B;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    document.getElementById("chart-h").textContent = `Score vs. ${axis === "cost" ? "cost" : "time"}`;
    if (!rows.length) { svg.innerHTML = ""; return; }
    const xs = rows.map((r) => r[key]);
    const lo = Math.min(...xs) / 1.8, hi = Math.max(...xs) * 1.8;
    const yMin = Math.max(0, Math.floor((Math.min(...rows.map((r) => r.accuracy)) - 0.05) * 10) / 10);
    const sx = (v) => L + ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * pw;
    const sy = (v) => T + (1 - (v - yMin) / (1 - yMin)) * ph;
    let g = `<title id="chart-title">${esc(TASKS[task].y)} against ${axis} per lot</title>`;
    for (let e = Math.floor(Math.log10(lo)); 10 ** e <= hi; e++) for (const m of narrow ? [1] : [1, 2, 5]) {
      const v = m * 10 ** e; if (v < lo || v > hi) continue;
      const label = axis === "cost" ? "$" + +v.toPrecision(2) : +(v / 1000).toPrecision(2) + " s";
      g += `<line class="gl" x1="${sx(v)}" x2="${sx(v)}" y1="${T}" y2="${T + ph}"/><text class="ax" x="${sx(v)}" y="${T + ph + 18}" text-anchor="middle">${label}</text>`;
    }
    for (let v = yMin; v <= 1.0001; v += narrow ? 0.2 : 0.1) g += `<line class="gl" x1="${L}" x2="${L + pw}" y1="${sy(v)}" y2="${sy(v)}"/><text class="ax" x="${L - 8}" y="${sy(v) + 4}" text-anchor="end">${task === "stripe" ? (v * 10).toFixed(0) : v.toFixed(1)}</text>`;
    g += `<text class="axl" x="${L + pw}" y="${H - 4}" text-anchor="end">${axis === "cost" ? "cost" : "time"} per lot, log scale</text>`;
    g += `<text class="axl" x="${L + 6}" y="${T + 14}">${esc(TASKS[task].y)}</text>`;
    const front = pareto(rows, key);
    const on = new Set(front.map((r) => r.system));
    const pts = front.map((r) => [sx(r[key]), sy(r.accuracy)]);
    if (pts.length > 1) {
      let d = "";
      pts.forEach(([x, y], i) => { d += (i ? ` L${x},${pts[i - 1][1]} L` : "M") + `${x},${y}`; });
      g += `<path class="front" d="${d}"/>`;
    }
    rows.forEach((r) => {
      g += `<circle class="pt${on.has(r.system) ? " on" : ""}" data-s="${esc(r.system)}" cx="${sx(r[key])}" cy="${sy(Math.max(yMin, r.accuracy))}" r="${on.has(r.system) ? 8 : 6.5}" fill="${color(r.provider)}"/>`;
    });
    // Label every point; labels avoid each other, the points and the frontier line.
    const obstacles = [];
    for (let i = 1; i < pts.length; i++) {
      const [ax, ay] = pts[i - 1], [bx, by] = pts[i];
      obstacles.push([ax, bx, ay - 3, ay + 3], [bx - 3, bx + 3, Math.min(ay, by), Math.max(ay, by)]);
    }
    rows.forEach((r) => { const x = sx(r[key]), y = sy(Math.max(yMin, r.accuracy)); obstacles.push([x - 10, x + 10, y - 10, y + 10]); });
    const hits = (b) => obstacles.filter((o) => b[0] < o[1] && b[1] > o[0] && b[2] < o[3] && b[3] > o[2]).length;
    const fs = narrow ? 11 : 13;
    [...rows].sort((a, b) => b.accuracy - a.accuracy).forEach((r) => {
      const x = sx(r[key]), y = sy(Math.max(yMin, r.accuracy));
      const text = narrow ? modelOf(r.system).replace(/^Claude |^Gemini 4 /, "") : modelOf(r.system);
      const w = text.length * fs * 0.56, h = fs + 2;
      const spots = [[x + 13, y + 4], [x - 13 - w, y + 4], [x - w / 2, y - 13], [x - w / 2, y + 20],
        [x + 10, y - 11], [x - 10 - w, y - 11], [x + 10, y + 18], [x - 10 - w, y + 18], [x - 4, y - 14], [x - 4, y + 22]]
        .filter(([l, b]) => l >= L + 2 && l + w <= L + pw && b - h > T);
      if (!spots.length) return;
      const cost = (s) => hits([s[0], s[0] + w, s[1] - h + 3, s[1] + 3]);
      const [l, b] = spots.reduce((best, s) => (cost(s) < cost(best) ? s : best));
      obstacles.push([l, l + w, b - h + 3, b + 3]);
      g += `<text class="lab" x="${l.toFixed(1)}" y="${b.toFixed(1)}" style="font-size:${fs}px">${esc(text)}</text>`;
    });
    svg.innerHTML = g;
    bindTips(svg, ".pt", (s) => rows.find((r) => r.system === s));
  }
  document.querySelectorAll("#seg-axis button").forEach((b) => b.addEventListener("click", () => {
    axis = b.dataset.axis;
    document.querySelectorAll("#seg-axis button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.axis === axis)));
    renderChart();
  }));
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(renderChart, 120); });

  // ---- All-setups table --------------------------------------------------------
  let sortCol = 0, sortDir = -1;
  function renderTable() {
    const cfg = TASKS[task];
    const all = ROWS[task];
    const front = new Set(pareto(all.filter((r) => !r.excluded), "cost").map((r) => r.system));
    const ranked = [...all].sort((a, b) => b.accuracy - a.accuracy);
    const rows = [...all].sort((a, b) => sortDir * (cfg.cols[sortCol][1](a) - cfg.cols[sortCol][1](b)) * -1 || b.accuracy - a.accuracy);
    const head = `<thead><tr><th scope="col">#</th><th scope="col">Setup</th>${cfg.cols.map((c, i) => `<th scope="col"><button type="button" data-col="${i}"${i === sortCol ? ` data-dir="${sortDir < 0 ? "↓" : "↑"}"` : ""}>${esc(c[0])}</button></th>`).join("")}</tr></thead>`;
    const body = rows.map((r) => {
      const badge = front.has(r.system) ? '<span class="badge">frontier</span>' : r.excluded ? `<span class="badge off" title="${esc(r.frontierNote || "")}">off charts</span>` : "";
      return `<tr><td class="rank">${ranked.indexOf(r) + 1}</td><td class="sys"><span class="vdot" style="background:${color(r.provider)}"></span><span class="sysname">${esc(r.system)}</span>${badge}</td>${cfg.cols.map((c) => `<td class="${c[3] && c[3](r) ? "bad" : ""}">${c[2](r)}</td>`).join("")}</tr>`;
    }).join("");
    const t = document.getElementById("lb");
    t.innerHTML = head + `<tbody>${body}</tbody>`;
    t.querySelectorAll("th button").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.col);
      if (i === sortCol) sortDir = -sortDir; else { sortCol = i; sortDir = -1; }
      renderTable();
    }));
    document.getElementById("all-sum").textContent = `All ${all.length} setups`;
  }

  // ---- Tabs ----------------------------------------------------------------------
  document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => {
    task = b.dataset.task; sortCol = 0; sortDir = -1;
    document.querySelectorAll(".tabs [role=tab]").forEach((x) => x.setAttribute("aria-selected", String(x.dataset.task === task)));
    document.getElementById("panel").setAttribute("aria-labelledby", "tab-" + task);
    render();
  }));
  function render() { hideTip(); renderBars(); renderChart(); renderTable(); }

  // ---- Citation ------------------------------------------------------------------
  document.getElementById("copy-bib").addEventListener("click", (e) => {
    const text = document.getElementById("bib").textContent;
    const done = () => { e.target.textContent = "Copied"; setTimeout(() => (e.target.textContent = "Copy citation"), 1600); };
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(done, () => {
      const range = document.createRange(); range.selectNodeContents(document.getElementById("bib"));
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    });
  });

  render();
})();
