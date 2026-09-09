"use strict";

const NS = "http://www.w3.org/2000/svg";
const fmt = (n) => Math.round(n).toLocaleString("en-US");
const signed = (n) => (n >= 0 ? "+" : "−") + fmt(Math.abs(n));
const pct = (n, digits = 1) => (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(digits) + "%";

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
function barLeft(x, y, w, h, r) {
  if (w <= 0) return `M${x} ${y} v${h}`;
  const rr = Math.min(r, h / 2, w);
  return `M${x} ${y} L${x - w + rr} ${y} Q${x - w} ${y} ${x - w} ${y + rr} L${x - w} ${y + h - rr} Q${x - w} ${y + h} ${x - w + rr} ${y + h} L${x} ${y + h} Z`;
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

const state = { activity: [], summary: [], comparison: [], runId: null, condition: null, view: "overview" };

const toolsOf = (row) => (row.tools ? row.tools.split(" ").filter(Boolean) : []);

/* One turn can fire the same tool many times in parallel; listing it 15 times
   buries the count that actually matters. */
function toolSummary(row) {
  const names = toolsOf(row);
  if (!names.length) return "";
  const counts = new Map();
  names.forEach((n) => counts.set(n, (counts.get(n) || 0) + 1));
  return [...counts.entries()].map(([n, c]) => (c > 1 ? `${n}×${c}` : n)).join(", ");
}

const targetsOf = (row) => (row.targets ? row.targets.split(" | ").filter(Boolean) : []);

/* What a turn was doing, named from the tools it called - a classification of
   recorded tool names, not a guess about intent. */
const ROLES = {
  Read: "read", Glob: "read", Grep: "read", NotebookRead: "read", WebFetch: "read",
  Write: "write", Edit: "write", NotebookEdit: "write",
  Bash: "run", BashOutput: "run", KillShell: "run",
};
const ROLE_TEXT = {
  read: ["파일을 읽어 들인", "읽어 들인 파일 내용이"],
  write: ["파일을 쓴", "쓰기 도구가 돌려준 결과가"],
  run: ["명령을 실행한", "명령 출력이"],
  other: ["도구를 호출한", "도구가 돌려준 결과가"],
};

function roleOf(row) {
  const counts = { read: 0, write: 0, run: 0, other: 0 };
  toolsOf(row).forEach((n) => { counts[ROLES[n] || "other"] += 1; });
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return null;
  const kind = Object.keys(counts).reduce((a, b) => (counts[a] >= counts[b] ? a : b));
  return { kind, counts, total, mixed: Object.values(counts).filter((v) => v > 0).length > 1 };
}

/* "gpu_platform/models.py 외 4개" - naming every file would bury the count. */
function targetPhrase(row, limit = 2) {
  const targets = targetsOf(row);
  if (!targets.length) return "";
  const head = targets.slice(0, limit).join(", ");
  return targets.length > limit ? `${head} 외 ${targets.length - limit}개` : head;
}

/* The palette has five series roles, so a sixth condition would repeat BASE's
   colour. Pair the hue with a dash pattern: 20 combinations before anything
   repeats, and no new palette entries to keep in sync. */
const DASHES = ["", "7 3", "2 3", "9 3 2 3"];
function seriesStyle(index) {
  return {
    role: `--series-${(index % 5) + 1}`,
    dash: DASHES[Math.floor(index / 5) % DASHES.length],
  };
}

function turnsFor(runId) {
  return state.activity
    .filter((r) => `${r.run_date}/${r.run_id}` === runId)
    .sort((a, b) => num(a.turn) - num(b.turn));
}

/* ---------- aggregation ----------

   Every figure below is a sum or a subtraction of published columns.  The four
   reconcile shares add up to the context the provider actually reread, so the
   difference between two runs decomposes into the same four parts exactly -
   which is what lets the report say *where* a condition saved without guessing.  */

const PARTS = [
  ["opening", "초기 컨텍스트", "--series-1"],
  ["output", "모델 출력", "--series-2"],
  ["tool_result", "tool result", "--series-3"],
  ["discarded", "버려진 컨텍스트", "--series-4"],
];

function buildRuns() {
  const byKey = new Map();
  state.activity.forEach((r) => {
    const key = `${r.run_date}/${r.run_id}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(r);
  });
  const summaryByKey = new Map(
    state.summary.map((r) => [`${r.run_date}/${r.run_id}`, r]));

  const runs = [];
  byKey.forEach((rows, key) => {
    rows.sort((a, b) => num(a.turn) - num(b.turn));
    const s = summaryByKey.get(key) || {};
    const sum = (f) => rows.reduce((a, r) => a + num(r[f]), 0);
    const turns = rows.length;
    runs.push({
      key,
      run_date: rows[0].run_date,
      run_id: rows[0].run_id,
      condition: rows[0].condition,
      rows,
      turns,
      /* Published by benchmark/reports/collect.py rather than re-summed here.
         These two are all the overview needs from the turn log, so the screen
         does not depend on the largest file growing week after week. */
      processed: num(s.processed_tokens),
      tax: num(s.context_tax_tokens),
      totalOutput: sum("output_tokens"),
      totalResult: sum("result_tokens"),
      firstContext: num(rows[0].context_tokens),
      cost: num(s.cost_usd),
      quality: num(s.quality_score),
      criticalPass: s.critical_pass || "",
      measurable: num(s.measurable) === 1,
      model: s.model || "",
      duration: num(s.duration_seconds),
      changedFiles: num(s.changed_files),
      toolCalls: num(s.tool_calls),
      firstCacheRead: num(s.first_turn_cache_read_tokens),
      washoutGap: s.washout_gap_seconds === "" ? null : num(s.washout_gap_seconds),
      auxTokens: num(s.aux_model_tokens),
      thinking: sum("thinking_tokens"),
      observed: num(s.reconcile_observed),
      opening: num(s.reconcile_opening),
      output: num(s.reconcile_output),
      tool_result: num(s.reconcile_tool_result),
      discarded: num(s.reconcile_discarded),
    });
  });
  runs.sort((a, b) => (a.run_date === b.run_date
    ? a.run_id.localeCompare(b.run_id) : byBatch(a.run_date, b.run_date)));
  return runs;
}

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
const avgOf = (runs, field) => mean(runs.map((r) => r[field]));

/* Batch labels are not all plain dates - the pilot is "pilot-2026-09-05" - and
   any such label sorts after every YYYY-MM-DD batch, which would put the oldest
   batch at the right-hand end of the trend line. Order by the date inside. */
function batchTime(label) {
  const match = /\d{4}-\d{2}-\d{2}/.exec(label);
  return match ? match[0] : label;
}
const byBatch = (a, b) => batchTime(a).localeCompare(batchTime(b)) || a.localeCompare(b);

/* The published arm order (benchmark/config.json). A condition not on this
   list - some future optimizer - just sorts after the ones that are. */
const CONDITION_ORDER = ["BASE", "H-ON", "C-FULL", "C-BRIEF", "R-ON"];
function conditionRank(condition) {
  const index = CONDITION_ORDER.indexOf(condition);
  return index === -1 ? CONDITION_ORDER.length : index;
}

function buildBatches(runs) {
  const byDate = new Map();
  runs.forEach((r) => {
    if (!byDate.has(r.run_date)) byDate.set(r.run_date, []);
    byDate.get(r.run_date).push(r);
  });
  const published = new Map(state.comparison.map((r) => [r.run_date, r]));
  const batches = [];
  [...byDate.keys()].sort(byBatch).forEach((date) => {
    const all = byDate.get(date);
    const row = published.get(date);
    batches.push({
      date,
      runs: all,
      base: all.filter((r) => r.condition === "BASE"),
      /* Read off data/comparison.csv rather than recomputed here. The formula
         lives in benchmark/reports/comparison.py; a second copy in the page
         would be a second chance to disagree with what was published. */
      noise: {
        processed: row && row.noise_processed_pct !== "" ? num(row.noise_processed_pct) : null,
        cost: row && row.noise_cost_pct !== "" ? num(row.noise_cost_pct) : null,
      },
    });
  });
  return batches;
}

/* Average the published per-batch differences. Each batch was already compared
   against its own baseline, so this is a mean of results - not a second
   implementation of the comparison. */
function buildComparison() {
  const perCondition = new Map();
  state.comparison.forEach((row) => {
    if (!perCondition.has(row.condition)) perCondition.set(row.condition, []);
    perCondition.get(row.condition).push(row);
  });
  const floors = (field) => {
    const values = state.comparison
      .filter((r) => r[field] !== "")
      .map((r) => ({ date: r.run_date, value: num(r[field]) }));
    const byDate = new Map(values.map((v) => [v.date, v.value]));
    return byDate.size ? mean([...byDate.values()]) : null;
  };
  const rows = [...perCondition.entries()].map(([condition, entries]) => ({
    condition,
    batches: new Set(entries.map((e) => e.run_date)).size,
    runs: entries.reduce((a, e) => a + num(e.runs), 0),
    processed: mean(entries.map((e) => num(e.processed_delta_pct))),
    cost: mean(entries.map((e) => num(e.cost_delta_pct))),
    tax: mean(entries.map((e) => num(e.tax_delta_pct))),
    quality: mean(entries.map((e) => num(e.quality_delta))),
  }));
  rows.sort((a, b) => a.processed - b.processed);
  return { rows, noise: { processed: floors("noise_processed_pct"), cost: floors("noise_cost_pct") } };
}

function corpus() {
  const runs = buildRuns();
  return { runs, batches: buildBatches(runs), ...buildComparison() };
}

/* ---------- overview ---------- */

function drawVerdict(data) {
  const verdict = document.getElementById("verdict");
  const note = document.getElementById("verdict-note");
  const { rows, noise } = data;
  if (!rows.length) {
    verdict.textContent = "비교할 조건이 아직 없습니다";
    note.textContent = "BASE 외의 조건이 최소 한 번은 실행돼야 비교가 생깁니다.";
    return;
  }
  const clears = rows.filter((r) =>
    noise.processed != null && noise.cost != null &&
    Math.abs(r.processed) > noise.processed && Math.abs(r.cost) > noise.cost);
  const best = rows[0];
  if (!clears.length) {
    verdict.textContent = "아직 noise floor를 넘은 조건이 없습니다";
    note.innerHTML = `가장 크게 줄인 것은 <strong>${best.condition}</strong>
      (처리 토큰 ${pct(best.processed)})이지만, 조건이 똑같은 BASE 실행끼리도
      ${noise.processed != null ? noise.processed.toFixed(1) + "%" : "—"} 벌어졌습니다.
      이 폭을 넘지 못한 차이는 조건의 효과라고 말할 수 없습니다.`;
    return;
  }
  const names = clears.map((r) => `${r.condition} (처리 토큰 ${pct(r.processed)}, 비용 ${pct(r.cost)})`);
  verdict.textContent = clears.length === 1 ? clears[0].condition : `${clears.length}개 조건`;
  /* Clearing the noise floor once is a reason to keep measuring, not a result.
     Say how thin the evidence is in the same breath as the claim. */
  const thin = clears.filter((r) => r.batches < 2);
  note.innerHTML = `실행 간 자연 변동(처리 토큰 ${noise.processed.toFixed(1)}%, 비용
    ${noise.cost.toFixed(1)}%)을 넘어선 조건입니다 — ${names.join(", ")}.
    나머지 조건의 차이는 변동 폭 안에 있습니다.${thin.length
      ? ` 다만 ${thin.map((r) => `${r.condition}은 ${r.batches}회차 ${r.runs}건`).join(", ")}
        관측이라, 아직 방향을 확인한 것이지 크기를 잰 것은 아닙니다.` : ""}`;
}

function drawCorpusKpis(data) {
  const box = document.getElementById("corpus-kpis");
  box.innerHTML = "";
  const turns = data.runs.reduce((a, r) => a + r.turns, 0);
  const conditions = new Set(data.runs.map((r) => r.condition));
  const cards = [
    ["회차", fmt(data.batches.length)],
    ["실행", fmt(data.runs.length)],
    ["조건", fmt(conditions.size)],
    ["측정한 턴", fmt(turns)],
    ["측정 비용 합계", `$${data.runs.reduce((a, r) => a + r.cost, 0).toFixed(2)}`],
  ];
  cards.forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "kpi";
    card.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
    box.appendChild(card);
  });
}

const METRICS = [["processed", "처리 토큰", "--series-1"], ["cost", "비용", "--series-5"]];

function drawDelta(data) {
  const { rows, noise } = data;
  const legend = document.getElementById("delta-legend");
  const note = document.getElementById("delta-note");
  legend.innerHTML = "";
  METRICS.forEach(([, label, role]) => {
    const item = document.createElement("span");
    item.innerHTML = `<i class="swatch" style="background:${ink(role)}"></i>${label}`;
    legend.appendChild(item);
  });

  const padL = 96, padR = 76, padT = 26, padB = 28;
  const rowH = 58, barH = 18, gap = 4;
  const width = 720;
  const height = padT + padB + Math.max(1, rows.length) * rowH;
  const svg = frame("delta", width, height);
  if (!rows.length) { note.textContent = ""; return; }

  const limit = Math.max(
    5, ...rows.flatMap((r) => [Math.abs(r.processed), Math.abs(r.cost)]),
    noise.processed || 0, noise.cost || 0) * 1.15;
  const span = width - padL - padR;
  const zero = padL + span / 2;
  const x = (v) => zero + (v / limit) * (span / 2);

  /* Noise band first, so the bars read against it. */
  const band = Math.max(noise.processed || 0, noise.cost || 0);
  if (band > 0) {
    el("rect", { x: x(-band), y: padT - 8, width: x(band) - x(-band),
      height: height - padT - padB + 12, fill: ink("--grid"), opacity: ".55" }, svg);
    const t = el("text", { x: zero, y: padT - 12, class: "tick", "text-anchor": "middle" }, svg);
    t.textContent = `noise floor ±${band.toFixed(1)}%`;
  }
  el("line", { x1: zero, y1: padT - 8, x2: zero, y2: height - padB + 4, class: "axis-line" }, svg);

  rows.forEach((row, i) => {
    const top = padT + i * rowH;
    const label = el("text", { x: padL - 12, y: top + rowH / 2 - 2, class: "mark-label", "text-anchor": "end" }, svg);
    label.textContent = row.condition;
    const sub = el("text", { x: padL - 12, y: top + rowH / 2 + 13, class: "tick", "text-anchor": "end" }, svg);
    sub.textContent = `${row.runs}건 · ${row.batches}회차`;

    METRICS.forEach(([key, name, role], m) => {
      const value = row[key];
      const y = top + 8 + m * (barH + gap);
      const w = Math.abs(x(value) - zero);
      const saving = value < 0;
      const path = el("path", {
        d: saving ? barLeft(zero, y, w, barH, 4) : barRight(zero, y, w, barH, 4),
        fill: ink(role), opacity: saving ? "1" : ".55",
      }, svg);
      hoverable(path, `<b>${row.condition} · ${name}</b><br>BASE 대비 <b>${pct(value)}</b><br>
        실행 ${row.runs}건 · 회차 ${row.batches}개`);
      /* A long bar reaches the label gutter, so the value goes inside it there.
         Short bars have no room for text, so those keep it outside. */
      const inside = w > 46;
      const t = el("text", {
        x: saving ? (inside ? zero - w + 7 : zero - w - 8) : (inside ? zero + w - 7 : zero + w + 8),
        y: y + barH - 5,
        /* A presentation attribute loses to the .mark-label rule, so the
           on-bar colour has to come from a class of its own. */
        class: inside ? "mark-label on-mark" : "mark-label",
        "text-anchor": saving === inside ? "start" : "end",
      }, svg);
      t.textContent = pct(value);
    });
  });

  const left = el("text", { x: padL, y: height - 8, class: "tick" }, svg);
  left.textContent = "← 절감";
  const right = el("text", { x: width - padR, y: height - 8, class: "tick", "text-anchor": "end" }, svg);
  right.textContent = "증가 →";
  note.textContent = "막대가 회색 띠 안에 있으면 BASE 실행끼리의 변동과 구별되지 않습니다.";
}

function drawConditionTable(data) {
  const table = document.getElementById("condition-table");
  table.innerHTML = "";
  const head = table.insertRow();
  ["조건", "실행", "평균 처리 토큰", "평균 비용", "평균 context tax", "vs BASE 처리", "vs BASE 비용", "noise 초과", "평균 품질"]
    .forEach((label) => { const th = document.createElement("th"); th.textContent = label; head.appendChild(th); });

  const byCondition = new Map();
  data.runs.forEach((r) => {
    if (!byCondition.has(r.condition)) byCondition.set(r.condition, []);
    byCondition.get(r.condition).push(r);
  });
  const deltaOf = (condition) => data.rows.find((r) => r.condition === condition);
  const order = ["BASE", ...data.rows.map((r) => r.condition)];

  order.forEach((condition) => {
    const runs = byCondition.get(condition);
    if (!runs) return;
    const delta = deltaOf(condition);
    const row = table.insertRow();
    const beats = delta && data.noise.processed != null && data.noise.cost != null &&
      Math.abs(delta.processed) > data.noise.processed && Math.abs(delta.cost) > data.noise.cost;
    const cells = [
      condition,
      fmt(runs.length),
      fmt(avgOf(runs, "processed")),
      `$${avgOf(runs, "cost").toFixed(2)}`,
      fmt(avgOf(runs, "tax")),
      delta ? pct(delta.processed) : "기준",
      delta ? pct(delta.cost) : "기준",
      delta ? (beats ? "예" : "아니오") : "—",
      avgOf(runs, "quality").toFixed(1),
    ];
    cells.forEach((value, i) => {
      const cell = row.insertCell();
      cell.textContent = value;
      if (i >= 5 && i <= 6 && delta) cell.className = delta[i === 5 ? "processed" : "cost"] < 0 ? "good" : "bad";
      if (i === 7 && delta) cell.className = beats ? "good" : "";
    });
  });
}

/* ---------- run report ---------- */

/* Tool results grouped by what the turn was doing, so a saving can be named:
   "read less" and "run fewer commands" are different findings. */
function resultByRole(rows) {
  const totals = { read: 0, write: 0, run: 0, other: 0 };
  rows.forEach((row) => {
    const role = roleOf(row);
    if (role) totals[role.kind] += num(row.result_tokens);
  });
  return totals;
}

const ROLE_NAME = { read: "파일 읽기", write: "파일 쓰기", run: "명령 실행", other: "기타 도구" };

function componentNote(key, run, base) {
  const d = run[key] - base[key];
  const openingPerTurn = (r) => (r.turns > 1 ? r.opening / (r.turns - 1) : r.firstContext);
  if (key === "opening") {
    const same = Math.abs(openingPerTurn(run) - openingPerTurn(base)) < openingPerTurn(base) * 0.05;
    return `과제 설명과 도구 정의로 이뤄진 첫 턴 컨텍스트는 매 턴 통째로 다시 실립니다.
      그 크기는 ${fmt(openingPerTurn(run))} 토큰으로 BASE의 ${fmt(openingPerTurn(base))} 토큰과
      ${same ? "사실상 같습니다" : "다릅니다"}. 이 항목이 ${signed(d)} 토큰 움직인 것은
      ${same ? "오직 " : ""}턴 수가 ${base.turns.toFixed(1)}턴에서 ${run.turns}턴으로 바뀌어
      같은 컨텍스트를 다시 읽은 횟수가 달라졌기 때문입니다.`;
  }
  if (key === "output") {
    const perTurn = run.totalOutput / Math.max(1, run.turns);
    const basePerTurn = base.totalOutput / Math.max(1, base.turns);
    const thinkShare = run.totalOutput ? (run.thinking / run.totalOutput) * 100 : 0;
    const baseThink = base.totalOutput ? (base.thinking / base.totalOutput) * 100 : 0;
    return `모델이 쓴 글의 총량이 BASE 평균 ${fmt(base.totalOutput)} 토큰에서
      ${fmt(run.totalOutput)} 토큰으로 바뀌었습니다. 턴당으로는 ${fmt(basePerTurn)} →
      ${fmt(perTurn)} 토큰입니다. 그중 추론(thinking)이 ${thinkShare.toFixed(1)}%로
      BASE의 ${baseThink.toFixed(1)}%와 견줍니다 — 짧게 쓰라는 지시는 글을 줄이지
      추론을 줄이지는 않습니다. 한 턴의 출력은 대화에 남아 이후 모든 턴에 다시 실리므로,
      재청구 기준으로는 ${signed(d)} 토큰이 됩니다.`;
  }
  if (key === "tool_result") {
    const mine = resultByRole(run.rows);
    const theirs = base.resultByRole;
    const moved = Object.keys(ROLE_NAME)
      .map((kind) => ({ kind, d: mine[kind] - theirs[kind] }))
      .filter((x) => Math.abs(x.d) >= 1)
      .sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
    const where = moved.length
      ? moved.map((x) => `${ROLE_NAME[x.kind]} ${signed(x.d)}`).join(", ")
      : "역할별로 나눌 만한 차이가 없습니다";
    const head = moved[0];
    return `도구가 돌려준 내용의 총량이 BASE 평균 ${fmt(base.totalResult)} 토큰에서
      ${fmt(run.totalResult)} 토큰으로 바뀌었습니다. 어느 역할에서 갈렸는지 보면 ${where}
      입니다.${head ? ` 즉 이 실행은 <strong>${ROLE_NAME[head.kind]}</strong>에서
      ${head.d < 0 ? "덜 가져왔습니다" : "더 가져왔습니다"}.` : ""}
      재청구 기준으로는 ${signed(d)} 토큰입니다.`;
  }
  return `컨텍스트가 도중에 줄어(compaction) ${signed(d)} 토큰이 분해에서 빠졌습니다.
    버려진 내용은 되살릴 수 없어 이 실행의 context tax는 실제보다 부풀려져 있습니다.`;
}

/* The batch's baseline, averaged - the yardstick every run figure is read against. */
function baselineFor(run, data) {
  const batch = data.batches.find((b) => b.date === run.run_date);
  const peers = batch ? batch.base.filter((r) => r.key !== run.key) : [];
  if (!peers.length) return { batch, peers, base: null };
  const avg = (f) => mean(peers.map((r) => r[f]));
  const roles = peers.map((r) => resultByRole(r.rows));
  return {
    batch, peers,
    base: {
      turns: avg("turns"), processed: avg("processed"), observed: avg("observed"),
      totalOutput: avg("totalOutput"), totalResult: avg("totalResult"),
      thinking: avg("thinking"),
      firstContext: avg("firstContext"), opening: avg("opening"), output: avg("output"),
      tool_result: avg("tool_result"), discarded: avg("discarded"),
      resultByRole: Object.fromEntries(Object.keys(ROLE_NAME)
        .map((kind) => [kind, mean(roles.map((r) => r[kind]))])),
    },
  };
}

function missingBaseline(run) {
  return run.condition === "BASE"
    ? `<p class="sub">이 실행은 <strong>${run.run_date}</strong> 회차의 기준선이고, 같은 회차에
       견줄 다른 BASE 실행이 없습니다. 비교는 BASE가 2회 이상인 회차에서만 만들어집니다.</p>`
    : `<p class="sub"><strong>${run.run_date}</strong> 회차에 BASE 실행이 없어 비교할 기준이
       없습니다.</p>`;
}

function drawRunDelta(data) {
  const box = document.getElementById("delta-run");
  const run = data.runs.find((r) => r.key === state.runId);
  if (!run) { box.innerHTML = `<p class="empty">실행을 선택하세요.</p>`; return; }
  const { batch, base } = baselineFor(run, data);
  if (!base) { box.innerHTML = missingBaseline(run); return; }

  const total = run.observed - base.observed;
  const parts = PARTS.map(([key, label]) => ({ key, label, d: run[key] - base[key] }))
    .filter((p) => p.d !== 0)
    .sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  const noise = batch.noise.processed;
  const processedPct = base.processed ? ((run.processed - base.processed) / base.processed) * 100 : 0;
  const inNoise = noise != null && Math.abs(processedPct) <= noise;

  const width = 660, rowH = 34, padL = 108, padR = 92, padT = 6;
  const limit = Math.max(1, ...parts.map((p) => Math.abs(p.d)));
  const span = width - padL - padR, zero = padL + span / 2;
  const bars = parts.map((p, i) => {
    const y = padT + i * rowH + 7;
    const w = (Math.abs(p.d) / limit) * (span / 2);
    const saving = p.d < 0;
    const d = saving ? barLeft(zero, y, w, 18, 4) : barRight(zero, y, w, 18, 4);
    /* The longest bar reaches the label gutter, so its value goes inside. */
    const inside = w > 62;
    const tx = saving ? (inside ? zero - w + 7 : zero - w - 8) : (inside ? zero + w - 7 : zero + w + 8);
    return `<path d="${d}" fill="var(${saving ? "--good" : "--critical"})"></path>
      <text x="${padL - 12}" y="${y + 13}" class="mark-label" text-anchor="end">${p.label}</text>
      <text x="${tx}" y="${y + 13}" class="${inside ? "mark-label on-mark" : "mark-label"}"
        text-anchor="${saving === inside ? "start" : "end"}">${signed(p.d)}</text>`;
  }).join("");
  const height = padT + parts.length * rowH + 8;

  box.innerHTML = `
    <p class="verdict ${total < 0 ? "good" : "bad"}">${pct(processedPct)}</p>
    <p class="hero-note">다시 청구된 컨텍스트가 <strong>${fmt(run.observed)}</strong> 토큰으로,
      같은 회차 BASE 평균 ${fmt(base.observed)} 토큰보다 <strong>${signed(total)}</strong> 토큰
      ${total < 0 ? "적습니다" : "많습니다"}. 턴 수는 ${base.turns.toFixed(1)} → ${run.turns}턴입니다.</p>
    ${noise != null ? `<p class="${inNoise ? "muted warn" : "muted"}">이 회차 BASE 실행끼리의 변동은
      ${noise.toFixed(1)}%입니다. ${inNoise
        ? "위 차이는 그 안에 있어 조건의 효과로 읽을 수 없습니다."
        : "위 차이는 그 폭을 넘습니다."}</p>` : ""}
    <div class="scroll-x"><svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
      role="img" aria-label="BASE 대비 항목별 차이">
      <line x1="${zero}" y1="${padT}" x2="${zero}" y2="${height - 4}" class="axis-line"></line>
      ${bars}
      <text x="${padL}" y="${height - 1}" class="tick">← 절감</text>
      <text x="${width - padR}" y="${height - 1}" class="tick" text-anchor="end">증가 →</text>
    </svg></div>`;
}

/* One paragraph per turn that mattered: what the turn was doing, and why doing
   it there costs what it costs. */
function turnStory(row, run) {
  const role = roleOf(row);
  const tax = num(row.context_tax_tokens);
  const result = num(row.result_tokens);
  const remaining = result ? Math.round(tax / result) : 0;
  const share = (tax / (run.tax || 1)) * 100;
  const [doing, produced] = ROLE_TEXT[role ? role.kind : "other"];
  const what = targetPhrase(row);
  const counts = role ? role.counts : null;
  const mix = counts && role.mixed
    ? ` (${Object.keys(ROLE_NAME).filter((k) => counts[k]).map((k) => `${ROLE_NAME[k]} ${counts[k]}회`).join(", ")})`
    : "";
  return `<li><b>턴 ${row.turn} — ${doing} 턴</b>${mix}
    ${what ? `<br><span class="targets">${what}</span>` : ""}
    <br>${produced} <b>${fmt(result)} 토큰</b>만큼 컨텍스트에 들어왔고, 남은 ${remaining}턴이
    매번 그것을 다시 읽어 <b>${fmt(tax)} 토큰</b>으로 청구됐습니다.
    이 실행 전체 context tax의 ${share.toFixed(1)}%입니다.</li>`;
}

function expensiveSection(run) {
  const top = [...run.rows]
    .sort((a, b) => num(b.context_tax_tokens) - num(a.context_tax_tokens))
    .slice(0, 3)
    .filter((r) => num(r.context_tax_tokens) > 0);
  if (!top.length) return `<p class="sub">이 실행에는 context tax가 잡힌 턴이 없습니다.</p>`;
  const head = top[0];
  const headRole = roleOf(head);
  const early = num(head.turn) <= Math.ceil(run.turns / 3);
  return `<p class="sub">가장 비쌌던 턴은 <strong>턴 ${head.turn}</strong>입니다.
    ${ROLE_TEXT[headRole ? headRole.kind : "other"][0]} 턴이었고,
    ${early
      ? "실행 앞쪽에서 일어나 남은 턴이 많았습니다. 같은 크기라도 앞 턴에서 들어온 내용이 더 오래, 더 여러 번 다시 실립니다."
      : "실행 뒤쪽이라 다시 실릴 턴이 적었는데도 상위에 올랐습니다. 들여온 내용 자체가 컸다는 뜻입니다."}</p>
    <ul class="notes">${top.map((r) => turnStory(r, run)).join("")}</ul>`;
}

function drawReport(data) {
  const box = document.getElementById("report");
  const run = data.runs.find((r) => r.key === state.runId);
  if (!run) { box.innerHTML = `<p class="empty">실행을 선택하세요.</p>`; return; }
  const { base } = baselineFor(run, data);
  const parts = base
    ? PARTS.map(([key, label]) => ({ key, label, d: run[key] - base[key] }))
        .filter((p) => p.d !== 0)
        .sort((a, b) => Math.abs(b.d) - Math.abs(a.d))
        .slice(0, 3)
    : [];
  box.innerHTML = `
    <h3>왜 이렇게 갈렸나</h3>
    ${base
      ? `<ul class="notes">${parts.map((p) =>
          `<li><b>${p.label} ${signed(p.d)} 토큰</b> — ${componentNote(p.key, run, base)}</li>`).join("")}</ul>`
      : missingBaseline(run)}
    <h3>토큰이 가장 많이 든 턴</h3>
    ${expensiveSection(run)}`;
}

/* ---------- run charts ---------- */

function drawTimeline(turns) {
  const padL = 64, padR = 16, padT = 14, padB = 34;
  const bw = 22, gap = 6;
  const width = Math.max(720, padL + padR + turns.length * (bw + gap));
  const height = 260, plot = height - padT - padB;
  const svg = frame("timeline", width, height);
  const max = Math.max(1, ...turns.map((r) => num(r.context_tax_tokens)));

  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 8, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = fmt((max * (4 - i)) / 4);
  }
  el("line", { x1: padL, y1: padT + plot, x2: width - padR, y2: padT + plot, class: "axis-line" }, svg);

  const peak = turns.reduce((a, b) => (num(a.context_tax_tokens) > num(b.context_tax_tokens) ? a : b), turns[0]);
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
  const padL = 64, padR = 16, padT = 14, padB = 34;
  const width = Math.max(720, padL + padR + turns.length * 28);
  const height = 220, plot = height - padT - padB;
  const svg = frame("growth", width, height);
  const max = Math.max(1, ...turns.map((r) => num(r.context_tokens)));
  const step = turns.length > 1 ? (width - padL - padR) / (turns.length - 1) : 0;
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

/* The stacked breakdown chart is gone; what has to survive is the claim it
   backed - that the four shares add up to what the provider actually reread.
   Read the shares off the summary row rather than recomputing them here: the
   formula lives in benchmark/reports/activity_log.py, and a copy of it in the
   page would be a second place for it to drift from what was published. */
function drawReconcileCheck() {
  const note = document.getElementById("reconcile-check");
  const run = state.summary.find((r) => `${r.run_date}/${r.run_id}` === state.runId);
  if (!run) { note.textContent = ""; return; }
  const sum = num(run.reconcile_opening) + num(run.reconcile_output)
    + num(run.reconcile_tool_result) + num(run.reconcile_discarded);
  const diff = num(run.reconcile_observed) - sum;
  note.textContent = `회계 검증 — 실측 재청구 ${fmt(num(run.reconcile_observed))} 토큰 · `
    + `초기 컨텍스트·모델 출력·tool result·버려진 컨텍스트로 분해한 합계 ${fmt(sum)} 토큰 · 차이 ${fmt(diff)}`;
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
  const dates = [...new Set(state.summary.map((r) => r.run_date))].sort(byBatch);
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

  const endLabels = [];
  [...byCondition.entries()].forEach(([condition, perDate], slot) => {
    const { role, dash } = seriesStyle(slot);
    const pts = dates.map((d, i) => {
      const arr = perDate.get(d);
      return arr ? [px(i), py(arr.reduce((a, b) => a + b, 0) / arr.length), arr] : null;
    }).filter(Boolean);
    if (pts.length > 1) {
      el("path", { d: pts.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" "),
        fill: "none", stroke: ink(role), "stroke-width": 2, "stroke-linejoin": "round",
        "stroke-dasharray": dash }, svg);
    }
    /* Markers crowd out the line they sit on once batches pile up. Shrink them
       with the spacing, and past the point where they would touch, let the line
       carry the series on its own - the hover target stays either way. */
    pts.forEach(([x, y, arr]) => {
      const r = step > 22 ? 5 : step > 10 ? 3 : 0;
      const c = r
        ? el("circle", { cx: x, cy: y, r, fill: ink(role), stroke: ink("--surface-1"), "stroke-width": 2 }, svg)
        : el("circle", { cx: x, cy: y, r: 6, fill: "transparent" }, svg);
      hoverable(c, `<b>${condition}</b><br>평균 비용 <b>$${(arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(3)}</b><br>실행 ${arr.length}건`);
    });
    if (pts.length) endLabels.push({ condition, role, x: pts[pts.length - 1][0], y: pts[pts.length - 1][1] });
    const item = document.createElement("span");
    item.innerHTML = `<svg class="swatch-line" width="18" height="11" aria-hidden="true">
      <line x1="0" y1="6" x2="18" y2="6" stroke="${ink(role)}" stroke-width="2"
        stroke-dasharray="${dash}"></line></svg>${condition}`;
    legend.appendChild(item);
  });

  /* Conditions that land on nearly the same cost would print their names on top
     of each other, so nudge each one below the previous. */
  endLabels.sort((a, b) => a.y - b.y).forEach((label, i, all) => {
    if (i > 0 && label.y - all[i - 1].y < 13) label.y = all[i - 1].y + 13;
    const t = el("text", { x: label.x + 10, y: label.y + 4, class: "mark-label", fill: ink(label.role) }, svg);
    t.textContent = label.condition;
  });

  /* At one batch a week the labels collide into a smear, so only as many are
     drawn as fit; the first and last are always kept to anchor the range. */
  const perLabel = 78;
  const step_ = Math.max(1, Math.ceil(dates.length / Math.max(1, Math.floor((width - padL - padR) / perLabel))));
  dates.forEach((d, i) => {
    if (i % step_ && i !== dates.length - 1) return;
    if (i === dates.length - 1 && (dates.length - 1) % step_ && dates.length > 1
        && px(i) - px(i - ((dates.length - 1) % step_)) < perLabel) return;
    const t = el("text", { x: px(i), y: height - 12, class: "tick", "text-anchor": "middle" }, svg);
    t.textContent = d;
  });
  note.textContent = dates.length < 2
    ? `회차가 ${dates.length}개뿐이라 추세선은 아직 그려지지 않습니다. 다음 회차가 수집되면 자동으로 이어집니다.`
    : `회차 ${dates.length}개.`;
}

function drawTable(turns) {
  document.getElementById("table-count").textContent = `${turns.length}턴 · 펼쳐 보기`;
  const cols = [["turn", "턴"], ["tools", "호출한 툴"], ["targets", "대상"], ["context_tokens", "컨텍스트"],
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
        : key === "targets" ? (targetPhrase(r, 2) || "—")
        : key === "turn" ? r.turn : fmt(num(r[key]));
    });
  });
}

function drawKpis(turns) {
  const kpis = document.getElementById("kpis");
  kpis.innerHTML = "";
  if (!turns.length) return;
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

  /* The raw run directories are not kept, so the provenance a reader would have
     checked there has to be readable here. */
  const data = corpus();
  const r = data.runs.find((x) => x.key === state.runId);
  const line = document.getElementById("provenance");
  if (!r) { line.textContent = ""; return; }
  line.innerHTML = [
    `${r.model || "모델 미기록"}`,
    `${(r.duration / 60).toFixed(1)}분`,
    `툴 호출 ${fmt(r.toolCalls)}회`,
    `변경 파일 ${fmt(r.changedFiles)}개`,
    `첫 턴 캐시 읽기 ${fmt(r.firstCacheRead)} 토큰`,
    r.washoutGap === null
      ? "직전 실행 없음 (배치의 첫 실행)"
      : `직전 실행과 ${fmt(r.washoutGap)}초 간격 · ${r.washoutGap >= 4200 ? "washout 통과" : "<b class=\"warn\">washout 미달</b>"}`,
    `보조 모델 ${fmt(r.auxTokens)} 토큰`,
  ].join(" · ");
}

/* ---------- render ---------- */

/* Only the five published conditions are ever clickable at the top level, no
   matter how many rounds pile up. A round adds an entry inside its condition's
   "날짜별 상세" list, not a new top-level choice. */
function runsGroupedByCondition() {
  const byId = new Map();
  state.activity.forEach((r) => {
    const id = `${r.run_date}/${r.run_id}`;
    if (!byId.has(id)) byId.set(id, r);
  });
  const groups = new Map();
  [...byId.entries()].sort((a, b) => byBatch(a[0], b[0])).forEach(([id, row]) => {
    if (!groups.has(row.condition)) groups.set(row.condition, []);
    groups.get(row.condition).push({ id, run_date: row.run_date, run_id: row.run_id });
  });
  return groups;
}

function drawRunPicker() {
  const groups = runsGroupedByCondition();
  const conditions = [...groups.keys()]
    .sort((a, b) => conditionRank(a) - conditionRank(b) || a.localeCompare(b));
  if (!state.condition || !groups.has(state.condition)) state.condition = conditions[0] || null;

  const picker = document.getElementById("condition-picker");
  picker.innerHTML = "";
  conditions.forEach((condition) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = condition;
    button.setAttribute("aria-pressed", String(condition === state.condition));
    button.addEventListener("click", () => {
      if (state.condition === condition) return;
      state.condition = condition;
      const entries = groups.get(condition);
      state.runId = entries[entries.length - 1].id; // most recent round by default
      render();
    });
    picker.appendChild(button);
  });

  const entries = state.condition ? groups.get(state.condition) : [];
  if (!entries.some((entry) => entry.id === state.runId)) {
    state.runId = entries.length ? entries[entries.length - 1].id : null;
  }

  const list = document.getElementById("run-picker-list");
  list.innerHTML = "";
  entries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${entry.run_date} · ${entry.run_id}`;
    button.setAttribute("aria-pressed", String(entry.id === state.runId));
    button.addEventListener("click", () => {
      if (state.runId === entry.id) return;
      state.runId = entry.id;
      render();
    });
    list.appendChild(button);
  });
  document.getElementById("run-picker-count").textContent = `${entries.length}건`;
}

function render() {
  const data = corpus();
  drawVerdict(data);
  drawCorpusKpis(data);
  drawDelta(data);
  drawConditionTable(data);
  drawTrend();

  drawRunPicker();
  drawKpis(turnsFor(state.runId));
  drawReconcileCheck();
  drawRunDelta(data);
  drawReport(data);
  const turns = turnsFor(state.runId);
  drawTimeline(turns);
  drawGrowth(turns);
  drawTools(turns);
  drawTable(turns);
}

function showView(view) {
  state.view = view === "run" ? "run" : "overview";
  document.getElementById("view-overview").hidden = state.view !== "overview";
  document.getElementById("view-run").hidden = state.view !== "run";
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.view === state.view));
  });
  if (location.hash.slice(1) !== state.view) location.hash = state.view;
}

/* ---------- boot ---------- */

async function load(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return parseCsv(await response.text());
}

async function boot() {
  try {
    [state.activity, state.summary, state.comparison] = await Promise.all([
      load("../data/activity-log.csv"), load("../data/run-summary.csv"),
      load("../data/comparison.csv"),
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

  document.querySelectorAll("#tabs button").forEach((b) => {
    b.addEventListener("click", () => showView(b.dataset.view));
  });
  addEventListener("hashchange", () => showView(location.hash.slice(1)));

  const themeButton = document.getElementById("theme");
  themeButton.addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    themeButton.setAttribute("aria-pressed", String(!dark));
    render();
  });

  showView(location.hash.slice(1) || "overview");
  render();
}

boot();
