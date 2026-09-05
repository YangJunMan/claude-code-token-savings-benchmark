"use strict";

const NS = "http://www.w3.org/2000/svg";
const fmt = (n) => Math.round(n).toLocaleString("en-US");

/* ---------- CSV ---------- */

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false; }
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const header = rows.shift();
  return rows.filter((r) => r.length === header.length)
    .map((r) => Object.fromEntries(header.map((h, i) => [h, r[i]])));
}

const num = (v) => (v === "" || v == null ? 0 : Number(v));

/* ---------- SVG helpers ---------- */

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function frame(id, width, height) {
  const svg = document.getElementById(id);
  svg.innerHTML = "";
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  return svg;
}

function ink(role) {
  return getComputedStyle(document.documentElement).getPropertyValue(role).trim();
}

/* Rounded only on the data end, anchored to the baseline. */
function barUp(x, y, w, h, r) {
  if (h <= 0) return `M${x} ${y} h${w}`;
  const rr = Math.min(r, w / 2, h);
  return `M${x} ${y + h} L${x} ${y + rr} Q${x} ${y} ${x + rr} ${y} L${x + w - rr} ${y} Q${x + w} ${y} ${x + w} ${y + rr} L${x + w} ${y + h} Z`;
}
function barRight(x, y, w, h, r) {
  if (w <= 0) return `M${x} ${y} v${h}`;
  const rr = Math.min(r, h / 2, w);
  return `M${x} ${y} L${x + w - rr} ${y} Q${x + w} ${y} ${x + w} ${y + rr} L${x + w} ${y + h - rr} Q${x + w} ${y + h} ${x + w - rr} ${y + h} L${x} ${y + h} Z`;
}

/* ---------- tooltip ---------- */

const tip = document.getElementById("tip");
function showTip(event, html) {
  tip.innerHTML = html;
  tip.classList.add("on");
  const pad = 14, box = tip.getBoundingClientRect();
  let x = event.clientX + pad, y = event.clientY + pad;
  if (x + box.width > innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > innerHeight - 8) y = event.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
function hideTip() { tip.classList.remove("on"); }

function hoverable(node, html) {
  node.addEventListener("mousemove", (e) => showTip(e, html));
  node.addEventListener("mouseleave", hideTip);
}

/* ---------- state ---------- */

const state = { activity: [], summary: [], runId: null, revealed: Infinity };

const toolsOf = (row) => (row.tools ? row.tools.split(" ").filter(Boolean) : []);

/* One turn can fire the same tool many times in parallel; listing it 15 times
   buries the count that actually matters. */
function toolSummary(row) {
  const names = toolsOf(row);
  if (!names.length) return "";
  const counts = new Map();
  names.forEach((n) => counts.set(n, (counts.get(n) || 0) + 1));
  return [...counts.entries()].map(([n, c]) => (c > 1 ? `${n}\u00d7${c}` : n)).join(", ");
}

function turnsFor(runId) {
  return state.activity
    .filter((r) => `${r.run_date}/${r.run_id}` === runId)
    .sort((a, b) => num(a.turn) - num(b.turn));
}

function visibleTurns() {
  return turnsFor(state.runId).slice(0, state.revealed);
}

/* ---------- charts ---------- */

function drawTimeline(turns) {
  const all = turnsFor(state.runId);
  const padL = 64, padR = 16, padT = 14, padB = 34;
  const bw = 22, gap = 6;
  const width = Math.max(720, padL + padR + all.length * (bw + gap));
  const height = 260, plot = height - padT - padB;
  const svg = frame("timeline", width, height);
  const max = Math.max(1, ...all.map((r) => num(r.context_tax_tokens)));

  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 8, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = fmt((max * (4 - i)) / 4);
  }
  el("line", { x1: padL, y1: padT + plot, x2: width - padR, y2: padT + plot, class: "axis-line" }, svg);

  const peak = all.reduce((a, b) => (num(a.context_tax_tokens) > num(b.context_tax_tokens) ? a : b), all[0]);
  turns.forEach((row) => {
    const i = num(row.turn) - 1;
    const v = num(row.context_tax_tokens);
    const h = (v / max) * plot;
    const x = padL + i * (bw + gap);
    const isPeak = peak && row.turn === peak.turn;
    const path = el("path", {
      d: barUp(x, padT + plot - h, bw, h, 4),
      fill: isPeak ? ink("--series-2") : ink("--seq-400"),
    }, svg);
    hoverable(path, `<b>턴 ${row.turn}</b><br>${toolSummary(row) || "툴 없음"}<br>
      결과 <b>${fmt(num(row.result_tokens))}</b> 토큰<br>tax <b>${fmt(v)}</b> 토큰`);
    if (isPeak && h > 0) {
      const label = el("text", { x: x + bw / 2, y: padT + plot - h - 6, class: "mark-label", "text-anchor": "middle" }, svg);
      label.textContent = fmt(v);
    }
    if (i % 5 === 0) {
      const t = el("text", { x: x + bw / 2, y: height - 12, class: "tick", "text-anchor": "middle" }, svg);
      t.textContent = row.turn;
    }
  });
}

function drawGrowth(turns) {
  const all = turnsFor(state.runId);
  const padL = 64, padR = 16, padT = 14, padB = 34;
  const width = Math.max(720, padL + padR + all.length * 28);
  const height = 220, plot = height - padT - padB;
  const svg = frame("growth", width, height);
  const max = Math.max(1, ...all.map((r) => num(r.context_tokens)));
  const step = all.length > 1 ? (width - padL - padR) / (all.length - 1) : 0;
  const px = (i) => padL + i * step;
  const py = (v) => padT + plot - (v / max) * plot;

  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 8, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = fmt((max * (4 - i)) / 4);
  }
  if (!turns.length) return;

  const pts = turns.map((r, i) => [px(i), py(num(r.context_tokens))]);
  el("path", {
    d: `M${padL} ${padT + plot} ` + pts.map(([x, y]) => `L${x} ${y}`).join(" ") + ` L${pts[pts.length - 1][0]} ${padT + plot} Z`,
    fill: ink("--seq-400"), opacity: ".14",
  }, svg);
  el("path", {
    d: pts.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" "),
    fill: "none", stroke: ink("--seq-400"), "stroke-width": 2, "stroke-linejoin": "round",
  }, svg);

  turns.forEach((r, i) => {
    const c = el("circle", { cx: px(i), cy: py(num(r.context_tokens)), r: 5, fill: ink("--seq-400"),
      stroke: ink("--surface-1"), "stroke-width": 2 }, svg);
    hoverable(c, `<b>턴 ${r.turn}</b><br>컨텍스트 <b>${fmt(num(r.context_tokens))}</b> 토큰`);
    if (i % 5 === 0) {
      const t = el("text", { x: px(i), y: height - 12, class: "tick", "text-anchor": "middle" }, svg);
      t.textContent = r.turn;
    }
  });
}

const RECONCILE_PARTS = [
  ["opening", "초기 컨텍스트", "--series-1"],
  ["output", "모델 출력", "--series-2"],
  ["tool_result", "tool result", "--series-3"],
  ["discarded", "버려진 컨텍스트", "--series-4"],
];

/* Read the shares off the summary row rather than recomputing them here: the
   formula lives in benchmark/reports/activity_log.py, and a copy of it in the
   page would be a second place for it to drift from what was published. */
function reconcileShares() {
  const run = state.summary.find((r) => `${r.run_date}/${r.run_id}` === state.runId);
  if (!run) return null;
  return {
    observed: num(run.reconcile_observed),
    opening: num(run.reconcile_opening),
    output: num(run.reconcile_output),
    tool_result: num(run.reconcile_tool_result),
    discarded: num(run.reconcile_discarded),
  };
}

function drawReconcile() {
  const s = reconcileShares();
  if (!s) { frame("reconcile", 720, 0); document.getElementById("reconcile-legend").innerHTML = ""; return; }
  const legend = document.getElementById("reconcile-legend");
  legend.innerHTML = "";
  const width = 720, height = 96, padL = 8, padR = 8, barY = 18, barH = 34;
  const svg = frame("reconcile", width, height);
  const positive = RECONCILE_PARTS.filter(([k]) => s[k] > 0);
  const total = positive.reduce((a, [k]) => a + s[k], 0) || 1;
  const span = width - padL - padR;

  let x = padL;
  positive.forEach(([key, label, role], i) => {
    const w = (s[key] / total) * span;
    const gap = i < positive.length - 1 ? 2 : 0;   /* surface gap between fills */
    const path = el("path", {
      d: i === positive.length - 1
        ? barRight(x, barY, Math.max(0, w - gap), barH, 4)
        : `M${x} ${barY} h${Math.max(0, w - gap)} v${barH} h${-Math.max(0, w - gap)} Z`,
      fill: ink(role),
    }, svg);
    hoverable(path, `<b>${label}</b><br>${fmt(s[key])} 토큰 · ${((s[key] / total) * 100).toFixed(1)}%`);
    if (w > 64) {
      const text = `${label} ${fmt(s[key])}`;
      const half = text.length * 3.1;   /* ~6.2px per char at 11px */
      const cx = Math.min(Math.max(x + w / 2, padL + half), width - padR - half);
      const t = el("text", { x: cx, y: barY + barH + 16, class: "mark-label", "text-anchor": "middle" }, svg);
      t.textContent = text;
    }
    const item = document.createElement("span");
    item.innerHTML = `<i class="swatch" style="background:${ink(role)}"></i>${label}`;
    legend.appendChild(item);
    x += w;
  });

  const sum = s.opening + s.output + s.tool_result + s.discarded;
  const diff = s.observed - sum;
  const note = document.getElementById("reconcile-check");
  note.textContent = `실측 재청구 ${fmt(s.observed)} 토큰 · 분해 합계 ${fmt(sum)} 토큰 · 차이 ${fmt(diff)}`;
  note.className = diff === 0 ? "muted" : "muted warn";
}

function drawTools(turns) {
  const tally = new Map();
  turns.forEach((r) => {
    const names = toolsOf(r);
    if (!names.length) return;
    const share = num(r.context_tax_tokens) / names.length;
    names.forEach((n) => tally.set(n, (tally.get(n) || 0) + share));
  });
  const items = [...tally.entries()].sort((a, b) => b[1] - a[1]);
  const rowH = 30, padL = 130, padR = 90, padT = 6;
  const width = 720, height = Math.max(60, padT + items.length * rowH + 6);
  const svg = frame("tools", width, height);
  if (!items.length) return;
  const max = Math.max(...items.map(([, v]) => v)) || 1;
  const span = width - padL - padR;

  items.forEach(([name, value], i) => {
    const y = padT + i * rowH;
    const w = (value / max) * span;
    const path = el("path", { d: barRight(padL, y + 5, w, rowH - 14, 4), fill: ink("--seq-400") }, svg);
    hoverable(path, `<b>${name}</b><br>누적 tax <b>${fmt(value)}</b> 토큰`);
    const label = el("text", { x: padL - 10, y: y + rowH / 2 + 1, class: "mark-label", "text-anchor": "end" }, svg);
    label.textContent = name;
    const val = el("text", { x: padL + w + 8, y: y + rowH / 2 + 1, class: "mark-label" }, svg);
    val.textContent = fmt(value);
  });
}

function drawTrend() {
  const byCondition = new Map();
  state.summary.forEach((r) => {
    if (!byCondition.has(r.condition)) byCondition.set(r.condition, new Map());
    const dates = byCondition.get(r.condition);
    const cost = num(r.cost_usd);
    dates.set(r.run_date, [...(dates.get(r.run_date) || []), cost]);
  });
  const dates = [...new Set(state.summary.map((r) => r.run_date))].sort();
  const legend = document.getElementById("trend-legend");
  const note = document.getElementById("trend-note");
  legend.innerHTML = "";

  const padL = 64, padR = 90, padT = 14, padB = 34;
  const width = 720, height = 240, plot = height - padT - padB;
  const svg = frame("trend", width, height);
  const values = state.summary.map((r) => num(r.cost_usd));
  const max = Math.max(0.1, ...values) * 1.15;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 8, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = `$${((max * (4 - i)) / 4).toFixed(2)}`;
  }

  const step = dates.length > 1 ? (width - padL - padR) / (dates.length - 1) : 0;
  const px = (i) => padL + i * step;
  const py = (v) => padT + plot - (v / max) * plot;

  [...byCondition.entries()].forEach(([condition, perDate], slot) => {
    const role = `--series-${(slot % 5) + 1}`;
    const pts = dates.map((d, i) => {
      const arr = perDate.get(d);
      return arr ? [px(i), py(arr.reduce((a, b) => a + b, 0) / arr.length), arr] : null;
    }).filter(Boolean);
    if (pts.length > 1) {
      el("path", { d: pts.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" "),
        fill: "none", stroke: ink(role), "stroke-width": 2, "stroke-linejoin": "round" }, svg);
    }
    pts.forEach(([x, y, arr]) => {
      const c = el("circle", { cx: x, cy: y, r: 5, fill: ink(role), stroke: ink("--surface-1"), "stroke-width": 2 }, svg);
      hoverable(c, `<b>${condition}</b><br>평균 비용 <b>$${(arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(3)}</b><br>실행 ${arr.length}건`);
    });
    if (pts.length) {
      const [lx, ly] = pts[pts.length - 1];
      const t = el("text", { x: lx + 10, y: ly + 4, class: "mark-label", fill: ink(role) }, svg);
      t.textContent = condition;
    }
    const item = document.createElement("span");
    item.innerHTML = `<i class="swatch" style="background:${ink(role)}"></i>${condition}`;
    legend.appendChild(item);
  });

  dates.forEach((d, i) => {
    const t = el("text", { x: px(i), y: height - 12, class: "tick", "text-anchor": "middle" }, svg);
    t.textContent = d;
  });
  note.textContent = dates.length < 2
    ? `회차가 ${dates.length}개뿐이라 추세선은 아직 그려지지 않습니다. 다음 회차가 수집되면 자동으로 이어집니다.`
    : `회차 ${dates.length}개.`;
}

function drawTable(turns) {
  const cols = [["turn", "턴"], ["tools", "호출한 툴"], ["context_tokens", "컨텍스트"],
    ["output_tokens", "출력"], ["result_tokens", "결과"], ["context_tax_tokens", "context tax"]];
  const table = document.getElementById("table");
  table.innerHTML = "";
  const head = table.insertRow();
  cols.forEach(([, label]) => { const th = document.createElement("th"); th.textContent = label; head.appendChild(th); });
  turns.forEach((r) => {
    const row = table.insertRow();
    cols.forEach(([key]) => {
      const cell = row.insertCell();
      cell.textContent = key === "tools" ? (toolSummary(r) || "—")
        : key === "turn" ? r.turn : fmt(num(r[key]));
    });
  });
}

/* ---------- summary panels ---------- */

function drawHeroAndKpis(turns) {
  const hero = document.getElementById("hero");
  const note = document.getElementById("hero-note");
  const kpis = document.getElementById("kpis");
  kpis.innerHTML = "";
  if (!turns.length) { hero.textContent = "—"; note.textContent = ""; return; }

  const peak = turns.reduce((a, b) => (num(a.context_tax_tokens) > num(b.context_tax_tokens) ? a : b));
  const factor = num(peak.result_tokens) ? num(peak.context_tax_tokens) / num(peak.result_tokens) : 0;
  hero.textContent = `${fmt(num(peak.context_tax_tokens))} 토큰`;
  note.innerHTML = `턴 ${peak.turn}의 <strong>${toolSummary(peak) || "툴 없음"}</strong> 호출 —
    결과 ${fmt(num(peak.result_tokens))} 토큰이 이후 턴들에 반복 실려 <strong>${factor.toFixed(1)}배</strong>로 청구됐습니다.`;

  const run = state.summary.find((r) => `${r.run_date}/${r.run_id}` === state.runId) || {};
  const totalTax = turns.reduce((a, r) => a + num(r.context_tax_tokens), 0);
  const compacted = turns.some((r) => num(r.compacted));
  const cards = [
    ["조건", run.condition || "—"],
    ["턴 수", fmt(turns.length)],
    ["누적 context tax", `${fmt(totalTax)} 토큰`],
    ["비용 (API 환산)", run.cost_usd ? `$${Number(run.cost_usd).toFixed(3)}` : "—"],
    ["품질", run.quality_score ? `${run.quality_score} · critical ${run.critical_pass}` : "—"],
    ["측정 유효", compacted ? "아니오 (compaction)" : num(run.measurable) ? "예" : "아니오"],
  ];
  cards.forEach(([label, value]) => {
    const box = document.createElement("div");
    box.className = "kpi";
    box.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
    kpis.appendChild(box);
  });
}

/* ---------- render ---------- */

function render() {
  const turns = visibleTurns();
  drawHeroAndKpis(turnsFor(state.runId));
  drawTimeline(turns);
  drawGrowth(turns);
  drawReconcile();
  drawTools(turns);
  drawTrend();
  drawTable(turnsFor(state.runId));
}

function play() {
  const total = turnsFor(state.runId).length;
  if (!total) return;
  state.revealed = 0;
  const timer = setInterval(() => {
    state.revealed += 1;
    render();
    if (state.revealed >= total) { clearInterval(timer); state.revealed = Infinity; }
  }, 90);
}

/* ---------- boot ---------- */

async function load(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return parseCsv(await response.text());
}

async function boot() {
  try {
    [state.activity, state.summary] = await Promise.all([
      load("../data/activity-log.csv"), load("../data/run-summary.csv"),
    ]);
  } catch (error) {
    document.querySelector(".wrap").insertAdjacentHTML("beforeend",
      `<section class="card"><h2>데이터를 불러오지 못했습니다</h2>
       <p class="sub">${error.message}</p>
       <p class="muted">저장소 루트에서 <code>python3 -m http.server</code>를 실행한 뒤
       <code>/web/</code>을 여세요. <code>file://</code>로 직접 열면 브라우저가 CSV 읽기를 막습니다.</p>
       </section>`);
    return;
  }

  const select = document.getElementById("run");
  const ids = [...new Set(state.activity.map((r) => `${r.run_date}/${r.run_id}`))];
  ids.forEach((id) => {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = id;
    select.appendChild(option);
  });
  state.runId = ids[0] || null;
  select.addEventListener("change", () => { state.runId = select.value; state.revealed = Infinity; render(); });
  document.getElementById("play").addEventListener("click", play);

  const themeButton = document.getElementById("theme");
  themeButton.addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    themeButton.setAttribute("aria-pressed", String(!dark));
    render();
  });

  render();
}

boot();
