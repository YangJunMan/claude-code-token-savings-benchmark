"use strict";

const NS = "http://www.w3.org/2000/svg";
const fmt = (n) => Math.round(n).toLocaleString("en-US");
/* 기법 이름은 어느 표에서나 같은 모양(BE_BRIEF 등)으로 유지한다. 이름표의 출처는
   conditions.json의 label 하나다. 결과 CSV에는 id(be-brief)만 있으므로, 같은 실행의
   run-summary.csv 행(condition 열 = label)을 run_id로 맞대어 이름을 찾는다. */
let labelCache = { results: null, summary: null, map: new Map() };
function conditionLabel(id) {
  if (labelCache.results !== state.results || labelCache.summary !== state.summary) {
    const byRun = new Map(state.summary.map((r) => [r.run_id, r.condition]));
    const map = new Map();
    state.results.forEach((r) => {
      const label = byRun.get(r.run_id);
      if (label && r.condition_id && !map.has(r.condition_id)) map.set(r.condition_id, label);
    });
    labelCache = { results: state.results, summary: state.summary, map };
  }
  return labelCache.map.get(id) || String(id || "");
}
const commas = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : fmt(v));
const usd = (v) => (v === null || v === undefined || Number.isNaN(v)
  ? "—"
  : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const signed = (n) => (n >= 0 ? "+" : "−") + fmt(Math.abs(n));
const pct = (n, digits = 1) => (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(digits) + "%";

const STATUS_LABEL = {
  succeeded: "성공",
  timeout: "시간 초과",
  failed: "실패",
  cancelled: "취소됨",
  blocked: "중단됨",
};
const friendlyStatus = (status) => STATUS_LABEL[status] || status || "—";

/* invalid_reason은 token_bench/ledger.py:_invalid_reason이 만든 이유를 "+"로 이은 값이다.
   이유마다 따로 옮기고, 버전이 붙는 구버전 CLI 격리(legacy_cli_<버전>)는 형식으로 읽는다. */
const INVALID_REASON_LABEL = {
  execution_error: "실행 오류",
  no_turns: "대화 기록 없음",
  reconcile_unbalanced: "토큰 합계 불일치",
  compacted: "대화 중간 요약(compaction) 발생",
};
function friendlyInvalid(reason) {
  if (!reason) return "측정 불가";
  return String(reason).split("+").map((part) => {
    const legacy = /^legacy_cli_(.+)$/.exec(part);
    if (legacy) return `구버전 CLI (${legacy[1]})`;
    return INVALID_REASON_LABEL[part] || part;
  }).join(", ");
}

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
  return rows.filter((r) => r.length > 1 || r[0] !== "");
}

/* 첫 줄을 헤더로 삼아 행을 객체로 바꾼다. 열 수가 헤더와 다른 행은 버린다. */
function toRecords(rows) {
  if (rows.length === 0) return [];
  const header = rows[0];
  return rows.slice(1).filter((r) => r.length === header.length)
    .map((r) => Object.fromEntries(header.map((h, i) => [h, r[i]])));
}

const num = (v) => (v === "" || v == null ? 0 : Number(v));

/* ---------- table helpers ---------- */

function addHeader(headRow, label, { extra = false, align = "" } = {}) {
  const th = document.createElement("th");
  th.textContent = label;
  if (extra) th.classList.add("extra-col");
  if (align) th.style.textAlign = align;
  headRow.appendChild(th);
  return th;
}

function addCell(row, text, { extra = false, className = "", align = "" } = {}) {
  const td = row.insertCell();
  td.textContent = text;
  if (extra) td.classList.add("extra-col");
  if (className) className.split(" ").filter(Boolean).forEach((c) => td.classList.add(c));
  if (align) td.style.textAlign = align;
  return td;
}

/* ---------- SVG helpers ---------- */

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

/* 카드 폭에 맞춰 그린다. 숨겨진 탭이나 접힌 details는 폭이 0으로 잡히므로
   그때만 기본값을 쓰고, 화면에 나타나는 순간 다시 그린다. */
function boxWidth(id, fallback) {
  const target = document.getElementById(id);
  const host = target ? target.parentElement : null;
  const available = host ? host.clientWidth : 0;
  return available > 80 ? available : fallback;
}

/* 그릴 내용이 그대로면 SVG를 다시 만들지 않는다. */
function unchanged(id, signature) {
  const node = document.getElementById(id);
  if (!node) return true;
  if (node.dataset.sig === signature) return true;
  node.dataset.sig = signature;
  return false;
}

function chartSignature(width, extra = "") {
  const theme = document.documentElement.getAttribute("data-theme") || "system";
  return `${Math.round(width)}|${theme}|${extra}`;
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

/* Node 기반 테스트는 순수 함수만 require 하므로 DOM 없이도 읽혀야 한다. */
const tip = typeof document === "undefined" ? null : document.getElementById("tip");
function showTip(event, html) {
  if (!tip) return;
  tip.innerHTML = html;
  tip.classList.add("on");
  const pad = 14, box = tip.getBoundingClientRect();
  let x = event.clientX + pad, y = event.clientY + pad;
  if (x + box.width > innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > innerHeight - 8) y = event.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
function hideTip() { if (tip) tip.classList.remove("on"); }

function hoverable(node, html) {
  node.addEventListener("mousemove", (e) => showTip(e, html));
  node.addEventListener("mouseleave", hideTip);
}

/* ---------- state ---------- */

const state = {
  activity: [], summary: [], comparison: [], runId: null, condition: null,
  view: "overview", promptId: null, modelId: null, diagnostics: {}, results: [],
};

function drawPicker(field, elementId, column) {
  let ids = [...new Set(state.summary.map((r) => r[column]).filter(Boolean))].sort();
  if (field === "promptId") {
    ids = ids.filter((id) => !id.startsWith("legacy:"));
  }
  const picker = document.getElementById(elementId);
  if (!picker) return;
  if (state[field] && !ids.includes(state[field])) state[field] = null;
  picker.replaceChildren();
  const all = document.createElement("option");
  all.value = ""; all.textContent = "전체"; picker.appendChild(all);
  ids.forEach((id) => {
    const option = document.createElement("option");
    option.value = id; option.textContent = id; picker.appendChild(option);
  });
  picker.value = state[field] || "";
  picker.onchange = () => { state[field] = picker.value || null; render(); };
}

const toolsOf = (row) => (row.tools ? row.tools.split(" ").filter(Boolean) : []);

function toolSummary(row) {
  const names = toolsOf(row);
  if (!names.length) return "";
  const counts = new Map();
  names.forEach((n) => counts.set(n, (counts.get(n) || 0) + 1));
  return [...counts.entries()].map(([n, c]) => (c > 1 ? `${n}×${c}` : n)).join(", ");
}

const targetsOf = (row) => (row.targets ? row.targets.split(" | ").filter(Boolean) : []);

const ROLES = {
  Read: "read", Glob: "read", Grep: "read", NotebookRead: "read", WebFetch: "read",
  Write: "write", Edit: "write", NotebookEdit: "write",
  Bash: "run", BashOutput: "run", KillShell: "run",
};
const ROLE_TEXT = {
  read: ["파일을 읽은", "읽어 들인 파일 내용이"],
  write: ["파일을 작성·수정한", "쓰기 도구가 돌려준 결과가"],
  run: ["명령어를 실행한", "명령어 출력이"],
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

function targetPhrase(row, limit = 2) {
  const targets = targetsOf(row);
  if (!targets.length) return "";
  const head = targets.slice(0, limit).join(", ");
  return targets.length > limit ? `${head} 외 ${targets.length - limit}개` : head;
}

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

/* ---------- aggregation ---------- */

const PARTS = [
  ["opening", "첫 턴 기본 문맥", "--series-1"],
  ["output", "모델 답변", "--series-2"],
  ["tool_result", "도구 실행 결과", "--series-3"],
  ["discarded", "중간 요약 제외분", "--series-4"],
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

  summaryByKey.forEach((_, key) => { if (!byKey.has(key)) byKey.set(key, []); });
  const runs = [];
  byKey.forEach((rows, key) => {
    const s = summaryByKey.get(key) || {};
    if (state.promptId && s.prompt_id !== state.promptId) return;
    if (state.modelId && s.model !== state.modelId) return;
    rows.sort((a, b) => num(a.turn) - num(b.turn));
    const sum = (f) => rows.reduce((a, r) => a + num(r[f]), 0);
    const turns = rows.length || num(s.turns);
    runs.push({
      key,
      run_date: s.run_date || rows[0]?.run_date,
      run_id: s.run_id || rows[0]?.run_id,
      condition: s.condition || rows[0]?.condition,
      promptId: s.prompt_id || "",
      pipeline: s.pipeline || "subscription",
      status: s.terminal_reason || "",
      invalidReason: s.invalid_reason || "",
      rows,
      turns,
      processed: num(s.processed_tokens),
      tax: num(s.context_tax_tokens),
      totalOutput: sum("output_tokens"),
      totalResult: sum("result_tokens"),
      firstContext: num(rows[0]?.context_tokens),
      cost: num(s.cost_usd),
      costKnown: s.cost_usd !== "" && s.cost_usd != null,
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

function batchTime(label) {
  const match = /\d{4}-\d{2}-\d{2}/.exec(label);
  return match ? match[0] : label;
}
const byBatch = (a, b) => batchTime(a).localeCompare(batchTime(b)) || a.localeCompare(b);

/* 화면에 늘어놓는 순서만 정한다. 목록에 없는 기법이 데이터에 생겨도 뒤에 붙어서 그대로 그려진다. */
const CONDITION_ORDER = ["BASE", "BE_BRIEF", "CAVEMAN-FULL", "HEADROOM", "RTK"];
function conditionRank(condition) {
  const index = CONDITION_ORDER.indexOf(condition);
  return index === -1 ? CONDITION_ORDER.length : index;
}
const conditionSort = (a, b) => conditionRank(a) - conditionRank(b) || a.localeCompare(b);

/* 전체 데이터에 등장하는 기법 목록. 과제·모델 필터와 무관하게 고정이라
   색이 필터에 따라 바뀌지 않는다(색은 순위가 아니라 기법을 따른다). */
function knownConditions() {
  return [...new Set(state.summary.map((r) => r.condition).filter(Boolean))].sort(conditionSort);
}
const conditionStyle = (condition) => seriesStyle(Math.max(0, knownConditions().indexOf(condition)));

/* 같은 BASE끼리의 흔들림 폭을 비용·토큰 모두 넘었는지. 판정은 이 함수 하나로만 한다. */
function beatsNoise(row, noise) {
  return noise.processed != null && noise.cost != null &&
    Math.abs(row.processed) > noise.processed && Math.abs(row.cost) > noise.cost;
}

/* 지금 선택한 과제·모델의 판정. 결론 문구, 상태 배지, 지표 띠가 모두 이 결과를 쓴다. */
function judge(data) {
  if (!data.rows.length) return { kind: "none", label: "비교 불가", clears: [] };
  const clears = data.rows.filter((r) => beatsNoise(r, data.noise));
  return clears.length
    ? { kind: "clear", label: "차이 관측", clears }
    : { kind: "unclear", label: "효과 미확인", clears };
}

/* 평균에 넣을 수 있는 실행. 하나도 없으면 참고용으로 제외된 실행을 돌려준다. */
function plottableRuns(data) {
  const valid = data.runs.filter((r) => r.measurable && r.costKnown);
  return valid.length
    ? { runs: valid, fallback: false }
    : { runs: data.runs.filter((r) => r.costKnown), fallback: true };
}

/* 과제·모델 선택이 바뀌면 다시 그리도록 차트 캐시 키에 넣는다. */
const cohortKey = () => `${state.promptId || ""}/${state.modelId || ""}`;

/* 그래프 아래 기법 이름 버튼. 마우스를 올리거나 Tab으로 이동하면 그 기법만 강조한다. */
function drawFocusKeys(keysId, svgId, conditions, swatch) {
  const keys = document.getElementById(keysId);
  if (!keys) return;
  keys.replaceChildren();
  conditions.forEach((condition) => {
    const key = document.createElement("button");
    key.type = "button";
    key.className = "trend-key";
    key.dataset.cond = condition;
    key.title = "마우스를 올리면 이 기법만 강조합니다";
    key.innerHTML = `${swatch(condition)}${condition}`;
    const on = () => focusChart(svgId, keysId, condition);
    const off = () => focusChart(svgId, keysId, "");
    key.addEventListener("mouseenter", on);
    key.addEventListener("mouseleave", off);
    key.addEventListener("focus", on);
    key.addEventListener("blur", off);
    keys.appendChild(key);
  });
}

function comparisonRows() {
  const rows = state.comparison.filter((r) =>
    (!state.promptId || r.prompt_id === state.promptId) &&
    (!state.modelId || r.model === state.modelId));
  const cohorts = new Set(rows.map((r) => `${r.model}/${r.prompt_id}`));
  return cohorts.size > 1 ? [] : rows;
}

function buildBatches(runs) {
  const byDate = new Map();
  runs.forEach((r) => {
    if (!byDate.has(r.run_date)) byDate.set(r.run_date, []);
    byDate.get(r.run_date).push(r);
  });
  const published = new Map(comparisonRows().map((r) => [r.run_date, r]));
  const batches = [];
  [...byDate.keys()].sort(byBatch).forEach((date) => {
    const all = byDate.get(date);
    const row = published.get(date);
    batches.push({
      date,
      runs: all,
      base: all.filter((r) => r.condition === "BASE"),
      noise: {
        processed: row && row.noise_processed_pct !== "" ? num(row.noise_processed_pct) : null,
        cost: row && row.noise_cost_pct !== "" ? num(row.noise_cost_pct) : null,
      },
    });
  });
  return batches;
}

function buildComparison() {
  const rowsSource = comparisonRows();
  const perCondition = new Map();
  rowsSource.forEach((row) => {
    if (!perCondition.has(row.condition)) perCondition.set(row.condition, []);
    perCondition.get(row.condition).push(row);
  });
  const floors = (field) => {
    const values = rowsSource
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

function drawArchive(data) {
  const countEl = document.getElementById("archive-count");
  if (countEl) countEl.textContent = `(${commas(data.runs.length)}건)`;
  const table = document.getElementById("archive-table");
  if (!table) return;
  table.replaceChildren();
  const head = table.insertRow();
  addHeader(head, "날짜", { align: "left" });
  addHeader(head, "기법", { align: "left" });
  addHeader(head, "비용");
  addHeader(head, "턴 수");
  addHeader(head, "상태", { align: "left" });
  addHeader(head, "실행 ID", { extra: true, align: "left" });
  addHeader(head, "과제", { extra: true, align: "left" });
  addHeader(head, "모델", { extra: true, align: "left" });
  addHeader(head, "평균 포함", { extra: true, align: "left" });
  addHeader(head, "진단 메모", { extra: true, align: "left" });
  addHeader(head, "평가 방식", { extra: true, align: "left" });

  [...data.runs].reverse().forEach((run) => {
    const row = table.insertRow();
    addCell(row, run.run_date || "—", { align: "left" });
    addCell(row, run.condition || "—", { align: "left" });
    addCell(row, run.costKnown ? usd(run.cost) : "—");
    addCell(row, commas(run.turns));
    addCell(row, friendlyStatus(run.status), { align: "left" });
    addCell(row, run.run_id || "—", { extra: true, align: "left", className: "mono-cell" });
    addCell(row, run.promptId || "—", { extra: true, align: "left" });
    addCell(row, run.model || "—", { extra: true, align: "left" });
    addCell(row, run.measurable ? "포함" : `제외 (${friendlyInvalid(run.invalidReason)})`, { extra: true, align: "left" });
    addCell(row, state.diagnostics[run.run_id]?.summary || "—", { extra: true, align: "left", className: "diag-cell" });
    addCell(row, run.pipeline === "legacy" ? "과거 점수 평가" : "공개 테스트", { extra: true, align: "left" });
  });
}

/* ---------- overview ---------- */

function drawVerdict(data) {
  const verdict = document.getElementById("verdict");
  const note = document.getElementById("verdict-note");
  if (!verdict || !note) return;
  const { rows, noise } = data;
  if (!rows.length) {
    const cohorts = new Set(data.runs.map((r) => `${r.model}/${r.promptId}`));
    if (cohorts.size > 1) {
      verdict.textContent = "상단에서 비교할 과제와 모델을 하나씩 선택해 주세요";
      note.textContent = "서로 다른 과제나 모델의 실행 결과는 조건이 달라 하나로 합쳐 평균을 내지 않습니다. 같은 과제와 모델을 고르면 비교 결과가 표시됩니다.";
    } else {
      verdict.textContent = "이 과제는 기법끼리 비교할 수 있는 데이터가 없습니다";
      note.textContent = `${emptyReason(data)} 아래 그래프에는 참고용으로 원본 비용만 흐리게 표시합니다.`;
    }
    return;
  }
  const { clears } = judge(data);
  if (!clears.length) {
    verdict.textContent = "어떤 절약법도 확실한 효과가 확인되지 않았습니다";
    note.innerHTML = `일부 기법은 비용이 낮게 나왔지만, 아무 설정도 하지 않은 <strong>BASE</strong>끼리도 그만큼 결과가 흔들렸습니다.
      아래 그래프에서 다른 기법의 점들이 <strong>BASE</strong>의 흔들림 범위 안에서 겹치는 것을 볼 수 있습니다.`;
    return;
  }
  const names = clears.map((r) => `${r.condition} (비용 ${pct(r.cost)}, 토큰 사용량 ${pct(r.processed)})`);
  verdict.textContent = clears.length === 1
    ? `${clears[0].condition}에서 흔들림 폭을 넘는 차이가 관측되었습니다`
    : `${clears.length}개 기법에서 흔들림 폭을 넘는 차이가 관측되었습니다`;
  const thin = clears.filter((r) => r.batches < 2);
  note.innerHTML = `같은 <strong>BASE</strong> 실행끼리의 흔들림 폭(비용 ±${noise.cost.toFixed(1)}%, 토큰 사용량 ±${noise.processed.toFixed(1)}%)을 넘어선 기법은 ${names.join(", ")}입니다. 나머지 기법은 흔들림 폭 안에 머물렀습니다.${thin.length
    ? ` 다만 ${thin.map((r) => `${r.condition}은 ${r.batches}회차(${r.runs}건)`).join(", ")} 기록뿐이라 반복 확인이 더 필요합니다.` : ""}`;
}

function drawScope(data) {
  const conditions = new Set(data.runs.map((r) => r.condition).filter(Boolean));
  const last = data.batches.length ? batchTime(data.batches[data.batches.length - 1].date) : null;
  const chips = [
    `비교 기법 <b>${fmt(conditions.size)}종</b>`,
    `실행 <b>${fmt(data.runs.length)}건</b>`,
    `회차 <b>${fmt(data.batches.length)}회</b>`,
    ...(last ? [`마지막 측정 ${last}`] : []),
  ].map((text) => `<span class="chip">${text}</span>`).join("");
  ["scope-overview", "scope-verify"].forEach((id) => {
    const box = document.getElementById(id);
    if (box) box.innerHTML = chips;
  });
}

/* 지금 선택한 과제·모델에서 평균에 넣을 수 없는 이유를 사람이 읽는 문장으로. */
function emptyReason(data) {
  const excluded = data.runs.filter((r) => !r.measurable);
  const reasons = [...new Set(excluded.map((r) => friendlyInvalid(r.invalidReason)))];
  const missing = knownConditions().filter((c) => !data.runs.some((r) => r.condition === c));
  const parts = [];
  if (!data.runs.length) parts.push("이 과제·모델 조합에는 실행 기록이 없습니다.");
  else if (excluded.length === data.runs.length) {
    parts.push(`이 과제의 실행 ${data.runs.length}건은 모두 평균에서 제외됐습니다(${reasons.join(", ")}).`);
  } else {
    parts.push("같은 회차에 BASE와 비교 기법이 함께 있는 유효한 실행이 없습니다.");
  }
  if (missing.length && data.runs.length) parts.push(`${missing.join(", ")}은(는) 이 과제의 실행 기록이 없습니다.`);
  return parts.join(" ");
}

/* 개요 맨 위 지표 띠: 판정, 규모, 비용을 한눈에. */
function drawKpiStrip(data) {
  const box = document.getElementById("kpi-strip");
  if (!box) return;
  const conditions = new Set(data.runs.map((r) => r.condition));
  const total = data.runs.reduce((a, r) => a + (r.cost || 0), 0);
  const verdict = judge(data);
  const verdictSub = {
    none: "유효한 BASE 비교 없음",
    unclear: "모든 기법이 흔들림 폭 안",
    clear: `${verdict.clears.map((r) => r.condition).join(", ")}이(가) 흔들림 폭 밖`,
  }[verdict.kind];
  const tiles = [
    ["판정", verdict.label, verdictSub, verdict.kind === "none" ? "muted-tile" : "neutral"],
    ["비교 기법", `${conditions.size}종`, conditions.has("BASE") ? "BASE 포함" : "BASE 없음", ""],
    ["실험 규모", `${data.runs.length}건`, `${data.batches.length}회차`, ""],
    ["기록된 비용 합계", `$${total.toFixed(2)}`, "모든 실행의 API 환산 비용", ""],
  ];
  const pill = document.getElementById("status-pill");
  if (pill) {
    pill.textContent = verdict.label;
    pill.classList.toggle("is-muted", verdict.kind === "none");
  }
  box.innerHTML = tiles.map(([label, value, sub, tone]) =>
    `<div class="kpi-tile ${tone}"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-sub">${sub}</div></div>`).join("");
}

/* 기법별 실행 비용을 점 하나 = 실행 1회로 보여 준다. BASE가 흔들린 범위(회색 띠)와
   다른 기법의 점이 겹치는 모습이 곧 "효과를 단정할 수 없다"는 근거다. */
function drawStrip(data) {
  const legend = document.getElementById("strip-legend");
  if (!legend) return;
  const { runs, fallback } = plottableRuns(data);
  const intro = document.getElementById("strip-intro");
  if (intro) {
    intro.dataset.normal ??= intro.innerHTML;
    intro.innerHTML = fallback
      ? "점 하나가 실행 1회입니다. 이 과제는 평균에 넣을 수 있는 실행이 없어, 제외된 실행의 비용을 참고용으로만 속이 빈 점으로 보여 줍니다."
      : intro.dataset.normal;
  }
  legend.innerHTML = fallback
    ? `<span><i class="swatch dot hollow"></i>평균에서 제외된 실행 (참고용)</span>`
    : `<span><i class="swatch dot"></i>실행 1회</span>
    <span><i class="swatch bar"></i>평균</span><span><i class="swatch band"></i>BASE가 흔들린 범위</span>`;
  const known = knownConditions();
  const conds = fallback ? known : known.filter((c) => runs.some((r) => r.condition === c));
  const padL = 112, padR = 22, padT = 26, padB = 34, rowH = 74;
  const width = boxWidth("strip", 640);
  if (unchanged("strip", chartSignature(width, `${runs.length}/${fallback}/${cohortKey()}`))) return;
  const height = padT + padB + Math.max(1, conds.length) * rowH;
  const svg = frame("strip", width, height);
  if (!runs.length) {
    el("text", { x: width / 2, y: height / 2, class: "tick", "text-anchor": "middle" }, svg).textContent = "표시할 실행 기록이 없습니다";
    return;
  }

  const rawMax = Math.max(...runs.map((r) => r.cost)) * 1.06;
  const step = Math.max(0.5, Math.ceil(rawMax / 4 / 0.5) * 0.5);
  const maxCost = Math.ceil(rawMax / step) * step;
  const x = (v) => padL + (v / maxCost) * (width - padL - padR);
  for (let t = 0; t <= maxCost + 1e-9; t += step) {
    el("line", { x1: x(t), y1: padT - 6, x2: x(t), y2: height - padB, class: "grid-line" }, svg);
    el("text", { x: x(t), y: height - padB + 18, class: "tick", "text-anchor": "middle" }, svg).textContent = `$${t.toFixed(1)}`;
  }

  const baseRuns = runs.filter((r) => r.condition === "BASE");
  const n = data.noise.cost;
  if (!fallback && baseRuns.length && n != null) {
    const mean = baseRuns.reduce((a, r) => a + r.cost, 0) / baseRuns.length;
    const lo = x(mean * (1 - n / 100)), hi = x(mean * (1 + n / 100));
    const band = el("rect", { x: lo, y: padT - 6, width: hi - lo, height: height - padB - padT + 6, rx: 6,
      fill: ink("--grid"), opacity: ".7" }, svg);
    hoverable(band, `<b>BASE가 흔들린 범위</b><br>같은 설정으로 돌려도 비용이<br>평균의 ±${n.toFixed(1)}%만큼 달라졌습니다`);
  }

  drawFocusKeys("strip-keys", "strip", conds.filter((c) => runs.some((r) => r.condition === c)),
    (c) => `<i class="swatch dot" style="background:${ink(conditionStyle(c).role)}"></i>`);
  conds.forEach((cond, i) => {
    const yc = padT + i * rowH + rowH / 2;
    const { role } = conditionStyle(cond);
    el("circle", { cx: 10, cy: yc, r: 5, fill: ink(role), "data-cond": cond }, svg);
    el("text", { x: 24, y: yc + 4, class: "mark-label", "data-cond": cond }, svg).textContent = cond;
    const mine = runs.filter((r) => r.condition === cond).sort((a, b) => String(a.run_date).localeCompare(String(b.run_date)));
    if (!mine.length) {
      el("text", { x: padL + 8, y: yc + 4, class: "tick" }, svg).textContent = "이 과제의 실행 기록 없음";
      return;
    }
    mine.forEach((r, k) => {
      const jitter = (((k * 37) % 11) - 5) / 5 * 20;
      const dot = fallback
        ? el("circle", { cx: x(r.cost), cy: yc + jitter, r: 6, fill: "none", stroke: ink(role), "stroke-width": 2, "data-cond": cond }, svg)
        : el("circle", { cx: x(r.cost), cy: yc + jitter, r: 5, fill: ink(role), "fill-opacity": ".85",
          stroke: ink("--surface-1"), "stroke-width": 2, "data-cond": cond }, svg);
      hoverable(dot, `<b>${cond}</b><br>${r.run_date}<br>비용 <b>$${r.cost.toFixed(2)}</b>${fallback ? `<br>평균 제외: ${friendlyInvalid(r.invalidReason)}` : ""}`);
    });
    if (fallback) return;
    const avg = mine.reduce((a, r) => a + r.cost, 0) / mine.length;
    el("line", { x1: x(avg), y1: yc - 26, x2: x(avg), y2: yc + 26, stroke: ink("--surface-1"), "stroke-width": 7, "stroke-linecap": "round", "data-cond": cond }, svg);
    const mark = el("line", { x1: x(avg), y1: yc - 26, x2: x(avg), y2: yc + 26, stroke: ink(role), "stroke-width": 3.5, "stroke-linecap": "round", "data-cond": cond }, svg);
    hoverable(mark, `<b>${cond}</b> 평균<br>$${avg.toFixed(2)} · ${mine.length}건`);
  });
}

function drawCorpusKpis(data) {
  const box = document.getElementById("corpus-kpis");
  if (!box) return;
  box.innerHTML = "";
  const turns = data.runs.reduce((a, r) => a + r.turns, 0);
  const conditions = new Set(data.runs.map((r) => r.condition).filter(Boolean));
  const cards = [
    ["비교 기법", `${fmt(conditions.size)}종`],
    ["전체 실행", `${fmt(data.runs.length)}건`],
    ["측정 회차", `${fmt(data.batches.length)}회`],
    ["누적 대화 턴", `${fmt(turns)}턴`],
    ["기록된 비용 합계", usd(data.runs.reduce((a, r) => a + r.cost, 0))],
  ];
  cards.forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "kpi";
    card.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
    box.appendChild(card);
  });
}

const METRICS = [["cost", "비용", "--series-5"], ["processed", "토큰 사용량", "--series-1"]];

function drawDelta(data) {
  const { rows, noise } = data;
  const legend = document.getElementById("delta-legend");
  const note = document.getElementById("delta-note");
  if (!legend || !note) return;
  legend.innerHTML = "";
  legend.hidden = !rows.length;
  METRICS.forEach(([key, label, role]) => {
    const item = document.createElement("span");
    const band = noise[key];
    item.innerHTML = `<i class="swatch" style="background:${ink(role)}"></i>${label}${band != null ? ` (같은 설정 흔들림 ±${band.toFixed(1)}%)` : ""}`;
    legend.appendChild(item);
  });

  const width = boxWidth("delta", 720);
  const compact = width < 460;
  const padL = compact ? 92 : 108;
  const padR = compact ? 52 : 76;
  const padT = 24, padB = 28;
  const rowH = 72, barH = 24, gap = 6;
  if (unchanged("delta", chartSignature(width, `${rows.length}:${state.promptId}:${state.modelId}`))) return;
  const height = padT + padB + Math.max(1, rows.length) * rowH;
  const svg = frame("delta", width, height);
  if (!rows.length) {
    el("text", { x: width / 2, y: height / 2, class: "tick", "text-anchor": "middle" }, svg).textContent =
      "BASE와 비교할 수 있는 유효한 실행이 없어 증감률을 계산하지 않았습니다";
    note.textContent = "";
    return;
  }

  const limit = Math.max(
    5, ...rows.flatMap((r) => [Math.abs(r.processed), Math.abs(r.cost)]),
    noise.processed || 0, noise.cost || 0) * 1.15;
  const span = Math.max(80, width - padL - padR);
  const zero = padL + span / 2;
  const x = (v) => zero + (v / limit) * (span / 2);

  el("line", { x1: zero, y1: padT - 8, x2: zero, y2: height - padB + 4, class: "axis-line" }, svg);

  rows.forEach((row, i) => {
    const top = padT + i * rowH;
    const label = el("text", { x: padL - 8, y: top + rowH / 2 - 2, class: "mark-label", "text-anchor": "end" }, svg);
    label.textContent = row.condition;
    const sub = el("text", { x: padL - 8, y: top + rowH / 2 + 13, class: "tick", "text-anchor": "end" }, svg);
    sub.textContent = `${fmt(row.runs)}건 · ${fmt(row.batches)}회`;

    METRICS.forEach(([key, name, role], m) => {
      const value = row[key];
      const y = top + 8 + m * (barH + gap);
      const w = Math.abs(x(value) - zero);
      const saving = value < 0;
      const band = noise[key];
      if (band != null && band > 0) {
        el("rect", { x: x(-band), y: y - 2, width: x(band) - x(-band), height: barH + 4,
          rx: 3, fill: ink("--grid"), opacity: ".72" }, svg);
      }
      const path = el("path", {
        d: saving ? barLeft(zero, y, w, barH, 4) : barRight(zero, y, w, barH, 4),
        fill: ink(role), opacity: saving ? "1" : ".55",
      }, svg);
      hoverable(path, `<b>${row.condition} · ${name}</b><br>BASE 대비 <b>${pct(value)}</b><br>
        실행 ${fmt(row.runs)}건 · 회차 ${fmt(row.batches)}개`);
      const inside = w > 46;
      const t = el("text", {
        x: saving ? (inside ? zero - w + 6 : zero - w - 6) : (inside ? zero + w - 6 : zero + w + 6),
        y: y + barH - 5,
        class: inside ? "mark-label on-mark" : "mark-label",
        "text-anchor": saving === inside ? "start" : "end",
      }, svg);
      t.textContent = pct(value);
    });
  });

  const left = el("text", { x: padL, y: height - 8, class: "tick" }, svg);
  left.textContent = "← BASE보다 절감";
  const right = el("text", { x: width - padR, y: height - 8, class: "tick", "text-anchor": "end" }, svg);
  right.textContent = "BASE보다 증가 →";
  note.textContent = "막대 위에 마우스를 올리거나 터치하면 정확한 수치와 실행 건수를 볼 수 있습니다.";
}

function drawOverviewTable(data) {
  const table = document.getElementById("condition-table");
  if (!table) return;
  table.innerHTML = "";
  const head = table.insertRow();
  addHeader(head, "기법", { align: "left" });
  addHeader(head, "비용 차이");
  addHeader(head, "토큰 차이");
  addHeader(head, "판정", { align: "left" });
  addHeader(head, "비교 건수", { extra: true, align: "left" });
  addHeader(head, "상세", { extra: true, align: "left" });

  data.rows.forEach((delta) => {
    const beats = beatsNoise(delta, data.noise);
    const row = table.insertRow();
    addCell(row, delta.condition, { align: "left" });
    addCell(row, pct(delta.cost), { className: delta.cost < 0 ? "good" : "bad" });
    addCell(row, pct(delta.processed), { className: delta.processed < 0 ? "good" : "bad" });
    addCell(row, beats ? "흔들림 폭 초과" : "흔들림 폭 안", { align: "left" });
    addCell(row, `${fmt(delta.runs)}건 (${fmt(delta.batches)}회차)`, { extra: true, align: "left" });
    const go = addCell(row, "", { extra: true, align: "left" });
    const link = document.createElement("button");
    link.type = "button"; link.className = "link-button";
    link.textContent = "실행 상세 보기";
    link.addEventListener("click", () => openRun(delta.condition));
    go.appendChild(link);
  });
}

function openRun(condition) {
  const entries = runsGroupedByCondition().get(condition);
  if (!entries || !entries.length) return;
  state.condition = condition;
  state.runId = entries[entries.length - 1].id;
  showView("run");
  render();
  window.scrollTo(0, 0);
}

function drawConditionTable(data) {
  const table = document.getElementById("condition-table-verify");
  if (!table) return;
  table.innerHTML = "";
  const head = table.insertRow();
  addHeader(head, "기법", { align: "left" });
  addHeader(head, "유효 실행");
  addHeader(head, "평균 비용");
  addHeader(head, "BASE 대비 비용");
  addHeader(head, "흔들림 초과", { align: "left" });
  addHeader(head, "평균 총 사용 토큰", { extra: true });
  addHeader(head, "BASE 대비 토큰", { extra: true });
  addHeader(head, "평균 반복 청구 토큰", { extra: true });
  addHeader(head, "테스트 점수", { extra: true });

  if (new Set(data.runs.map((r) => `${r.model}/${r.promptId}`)).size > 1) {
    const row = table.insertRow();
    const td = row.insertCell();
    td.colSpan = 9;
    td.style.textAlign = "left";
    td.textContent = "상단에서 과제와 모델을 하나씩 선택하면 같은 조건 안에서 평균을 계산해 보여줍니다.";
    return;
  }

  const byCondition = new Map();
  data.runs.filter((r) => r.measurable).forEach((r) => {
    if (!byCondition.has(r.condition)) byCondition.set(r.condition, []);
    byCondition.get(r.condition).push(r);
  });
  if (!byCondition.size) {
    const td = table.insertRow().insertCell();
    td.colSpan = 9;
    td.style.textAlign = "left";
    td.textContent = emptyReason(data);
    return;
  }
  const deltaOf = (condition) => data.rows.find((r) => r.condition === condition);
  const order = [...byCondition.keys()].sort(conditionSort);

  order.forEach((condition) => {
    const runs = byCondition.get(condition);
    const delta = deltaOf(condition);
    const row = table.insertRow();
    const beats = delta && beatsNoise(delta, data.noise);
    addCell(row, condition, { align: "left" });
    addCell(row, `${fmt(runs.length)}건`);
    addCell(row, usd(avgOf(runs, "cost")));
    addCell(row, delta ? pct(delta.cost) : "기준", {
      className: delta ? (delta.cost < 0 ? "good" : "bad") : "",
    });
    addCell(row, delta ? (beats ? "예" : "아니오") : "—", {
      align: "left",
      className: delta && beats ? "good" : "",
    });
    addCell(row, fmt(avgOf(runs, "processed")), { extra: true });
    addCell(row, delta ? pct(delta.processed) : "기준", {
      extra: true,
      className: delta ? (delta.processed < 0 ? "good" : "bad") : "",
    });
    addCell(row, fmt(avgOf(runs, "tax")), { extra: true });
    addCell(row, avgOf(runs, "quality").toFixed(1), { extra: true });
  });
}

/* ---------- run report ---------- */

function resultByRole(rows) {
  const totals = { read: 0, write: 0, run: 0, other: 0 };
  rows.forEach((row) => {
    const role = roleOf(row);
    if (role) totals[role.kind] += num(row.result_tokens);
  });
  return totals;
}

const ROLE_NAME = { read: "파일 읽기", write: "파일 쓰기", run: "명령어 실행", other: "기타 도구" };

function componentNote(key, run, base) {
  const d = run[key] - base[key];
  const openingPerTurn = (r) => (r.turns > 1 ? r.opening / (r.turns - 1) : r.firstContext);
  if (key === "opening") {
    const same = Math.abs(openingPerTurn(run) - openingPerTurn(base)) < openingPerTurn(base) * 0.05;
    return `과제 설명과 도구 정의로 이루어진 첫 턴 기본 문맥은 매 턴 다시 전달됩니다.
      1턴당 크기는 ${fmt(openingPerTurn(run))} 토큰으로 BASE(${fmt(openingPerTurn(base))} 토큰)와
      ${same ? "거의 같습니다" : "조금 다릅니다"}. 이 항목이 ${signed(d)} 토큰 달라진 것은
      대화 횟수가 ${base.turns.toFixed(1)}턴에서 ${fmt(run.turns)}턴으로 바뀌어 다시 읽은 횟수가 달라졌기 때문입니다.`;
  }
  if (key === "output") {
    const perTurn = run.totalOutput / Math.max(1, run.turns);
    const basePerTurn = base.totalOutput / Math.max(1, base.turns);
    const thinkShare = run.totalOutput ? (run.thinking / run.totalOutput) * 100 : 0;
    const baseThink = base.totalOutput ? (base.thinking / base.totalOutput) * 100 : 0;
    return `모델 답변 총량이 BASE 평균 ${fmt(base.totalOutput)} 토큰에서 ${fmt(run.totalOutput)} 토큰으로 바뀌었습니다
      (턴당 ${fmt(basePerTurn)} → ${fmt(perTurn)} 토큰). 내부 추론 비중은 ${thinkShare.toFixed(1)}%입니다(BASE ${baseThink.toFixed(1)}%).
      한 번 작성한 답변은 대화 기록에 남아 이후 턴마다 다시 읽히므로, 누적 기준으로는 ${signed(d)} 토큰 차이가 났습니다.`;
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
      : "활동별로 나눌 만한 큰 차이가 없습니다";
    const head = moved[0];
    return `도구가 돌려준 결과 총량이 BASE 평균 ${fmt(base.totalResult)} 토큰에서
      ${fmt(run.totalResult)} 토큰으로 바뀌었습니다(${where}).${head ? ` 주로 <strong>${ROLE_NAME[head.kind]}</strong> 단계에서
      내용을 ${head.d < 0 ? "덜 읽어 들였습니다" : "더 많이 읽어 들였습니다"}.` : ""}
      이후 턴마다 다시 읽힌 누적 차이는 ${signed(d)} 토큰입니다.`;
  }
  return `대화 도중 문맥 요약(compaction)이 일어나 ${signed(d)} 토큰이 정리되었습니다.
    중간에 줄어든 내용이 있으면 반복 청구 토큰(context tax)이 실제보다 크게 잡힐 수 있어 해석에 주의해야 합니다.`;
}

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
    ? `<p class="verdict run-verdict">비교 기준 실행 (BASE)</p>
       <p class="hero-note">아무 절약법도 쓰지 않은 기본 상태의 실행입니다. 위쪽에서 다른 기법(<code>BE_BRIEF</code> 등)을 선택하면 같은 날 실행한 <code>BASE</code> 평균과 얼마나 차이가 났는지 바로 비교해 보여줍니다.</p>`
    : `<p class="verdict run-verdict">비교 기준 없음</p>
       <p class="hero-note"><strong>${run.run_date}</strong> 회차에는 비교 기준이 될 <code>BASE</code> 실행 기록이 없습니다. 아래에서 이 실행 자체의 요약 수치와 턴별 흐름을 확인할 수 있습니다.</p>`;
}

function drawRunDelta(data) {
  const box = document.getElementById("delta-run");
  if (!box) return;
  const run = data.runs.find((r) => r.key === state.runId);
  if (!run) { box.innerHTML = `<p class="empty">위쪽에서 살펴볼 실행을 선택해 주세요.</p>`; return; }
  const { batch, base } = baselineFor(run, data);
  const runNote = document.getElementById("delta-run-note");
  if (runNote) runNote.hidden = !base;
  if (!base) { box.innerHTML = missingBaseline(run); return; }

  const total = run.observed - base.observed;
  const parts = PARTS.map(([key, label]) => ({ key, label, d: run[key] - base[key] }))
    .filter((p) => p.d !== 0)
    .sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  const noise = batch.noise.processed;
  const processedPct = base.processed ? ((run.processed - base.processed) / base.processed) * 100 : 0;
  const inNoise = noise != null && Math.abs(processedPct) <= noise;

  const hostWidth = box.clientWidth || 600;
  const width = Math.max(280, hostWidth);
  const compact = width < 460;
  const rowH = 34, padL = compact ? 104 : 124, padR = compact ? 62 : 92, padT = 6;
  const limit = Math.max(1, ...parts.map((p) => Math.abs(p.d)));
  const span = Math.max(80, width - padL - padR), zero = padL + span / 2;
  const bars = parts.map((p, i) => {
    const y = padT + i * rowH + 7;
    const w = (Math.abs(p.d) / limit) * (span / 2);
    const saving = p.d < 0;
    const d = saving ? barLeft(zero, y, w, 18, 4) : barRight(zero, y, w, 18, 4);
    const inside = w > 58;
    const tx = saving ? (inside ? zero - w + 6 : zero - w - 6) : (inside ? zero + w - 6 : zero + w + 6);
    return `<path d="${d}" fill="var(${saving ? "--good" : "--critical"})"></path>
      <text x="${padL - 8}" y="${y + 13}" class="mark-label" text-anchor="end">${p.label}</text>
      <text x="${tx}" y="${y + 13}" class="${inside ? "mark-label on-mark" : "mark-label"}"
        text-anchor="${saving === inside ? "start" : "end"}">${signed(p.d)}</text>`;
  }).join("");
  const height = padT + parts.length * rowH + 10;

  const amount = `${Math.abs(processedPct).toFixed(1)}%`;
  const howMuch = processedPct < 0 ? `${amount} 적게 썼` : `${amount} 더 썼`;
  const summaryConclusion = noise != null
    ? (inNoise
      ? `같은 날 BASE보다 토큰을 ${howMuch}지만, 같은 설정끼리의 흔들림 폭 안이라 효과로 보기 어렵습니다`
      : `같은 날 BASE보다 토큰을 ${howMuch}고, 이날의 흔들림 폭을 넘었습니다`)
    : `같은 날 BASE보다 토큰을 ${howMuch}습니다`;

  box.innerHTML = `
    <p class="verdict run-verdict ${total < 0 ? "good" : "bad"}">${summaryConclusion}</p>
    <p class="hero-note">다시 읽히며 청구된 문맥 합계가 <strong>${fmt(run.observed)}</strong> 토큰으로, 같은 날 <code>BASE</code> 평균(${fmt(base.observed)} 토큰)보다 <strong>${signed(total)}</strong> 토큰 ${total < 0 ? "적었습니다" : "많았습니다"}. 대화 횟수는 ${base.turns.toFixed(1)}턴에서 ${fmt(run.turns)}턴이 되었습니다.${noise != null ? ` 이날 같은 <code>BASE</code> 실행끼리의 흔들림 폭(noise floor)은 ±${noise.toFixed(1)}%였습니다.` : ""}</p>
    <div class="chart run-delta-chart"><svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
      role="img" aria-label="BASE 대비 항목별 토큰 차이">
      <line x1="${zero}" y1="${padT}" x2="${zero}" y2="${height - 6}" class="axis-line"></line>
      ${bars}
      <text x="${padL}" y="${height - 1}" class="tick">← 절감</text>
      <text x="${width - padR}" y="${height - 1}" class="tick" text-anchor="end">증가 →</text>
    </svg></div>`;
}

function repeatReadCount(row, run) {
  const targets = targetsOf(row);
  if (!targets.length) return 0;
  const index = run.rows.indexOf(row);
  let count = 0;
  for (let i = 0; i < index; i++) {
    if (targetsOf(run.rows[i]).some((t) => targets.includes(t))) count += 1;
  }
  return count;
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function resultOutlierRatio(row, run) {
  const others = run.rows.map((r) => num(r.result_tokens)).filter((v) => v > 0);
  const typical = median(others);
  return typical > 0 ? num(row.result_tokens) / typical : 0;
}

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
  const repeats = repeatReadCount(row, run);
  const ratio = resultOutlierRatio(row, run);
  const why = [
    repeats > 0 ? `앞서 이미 ${repeats}번 확인했던 대상을 다시 읽었습니다` : "",
    ratio >= 2 ? `돌려받은 결과 크기가 다른 턴들의 중앙값보다 ${ratio.toFixed(1)}배 큽니다` : "",
  ].filter(Boolean).join(". ");
  return `<li><b>턴 ${row.turn} — ${doing} 단계</b>${mix}
    ${what ? `<br><span class="targets">${what}</span>` : ""}
    <br>${produced} <b>${fmt(result)} 토큰</b> 들어왔고, 이후 남은 ${fmt(remaining)}턴 동안 매번 다시 읽히며
    총 <b>${fmt(tax)} 토큰</b>이 반복 청구되었습니다(이 실행 전체 반복 청구량의 ${share.toFixed(1)}%).
    ${why ? `<br><span class="muted">${why}.</span>` : ""}</li>`;
}

function turnRow(row, run, lead) {
  const role = roleOf(row);
  const tax = num(row.context_tax_tokens);
  const result = num(row.result_tokens);
  const remaining = result ? Math.round(tax / result) : 0;
  const share = (tax / (run.tax || 1)) * 100;
  const ratio = resultOutlierRatio(row, run);
  const what = targetPhrase(row);
  return `<div class="turn-row${lead ? " lead" : ""}">
    <div class="turn-what">
      <b>턴 ${row.turn} · ${ROLE_TEXT[role ? role.kind : "other"][0]} 단계</b>
      ${what ? `<span class="targets">${what}</span>` : ""}
    </div>
    <div class="turn-figure"><b>${fmt(tax)}</b> 토큰</div>
    <div class="turn-metrics">
      <div><span class="label">남은 턴</span>${fmt(remaining)}턴</div>
      <div><span class="label">전체 비중</span>${share.toFixed(1)}%</div>
      <div><span class="label">평소 대비</span>${ratio >= 2 ? `${ratio.toFixed(1)}배` : "보통"}</div>
    </div>
  </div>`;
}

function drawTopTurns(data) {
  const box = document.getElementById("top-turns");
  if (!box) return;
  const run = data.runs.find((r) => r.key === state.runId);
  if (!run) { box.innerHTML = `<p class="empty">실행을 선택해 주세요.</p>`; return; }
  const top = [...run.rows]
    .sort((a, b) => num(b.context_tax_tokens) - num(a.context_tax_tokens))
    .slice(0, 3)
    .filter((r) => num(r.context_tax_tokens) > 0);
  if (!top.length) {
    box.innerHTML = `<p class="sub">이 실행에는 반복 청구 토큰(context tax)이 기록된 턴이 없습니다.</p>`;
    return;
  }
  const head = top[0];
  const early = num(head.turn) <= Math.ceil(run.turns / 3);
  box.innerHTML = `<p class="muted">가장 많은 누적 비용을 만든 단계는 <strong>턴 ${head.turn}</strong>입니다.
    ${early
      ? "실행 초반에 큰 내용이 들어오면서 이후 끝날 때까지 매 턴 반복해서 읽혔습니다."
      : "실행 후반이라 남은 턴이 적었는데도 상위에 올랐을 만큼 한 번에 들어온 내용이 컸습니다."}</p>
    ${top.map((r, i) => turnRow(r, run, i === 0)).join("")}
    <details class="turn-detail">
      <summary>턴별 상세 설명 펼치기</summary>
      <ul class="notes">${top.map((r) => turnStory(r, run)).join("")}</ul>
    </details>`;
}

function drawReport(data) {
  const box = document.getElementById("report");
  if (!box) return;
  const run = data.runs.find((r) => r.key === state.runId);
  if (!run) { box.innerHTML = `<p class="empty">실행을 선택해 주세요.</p>`; return; }
  const { base } = baselineFor(run, data);
  const parts = base
    ? PARTS.map(([key, label]) => ({ key, label, d: run[key] - base[key] }))
        .filter((p) => p.d !== 0)
        .sort((a, b) => Math.abs(b.d) - Math.abs(a.d))
        .slice(0, 3)
    : [];
  const diag = state.diagnostics[run.run_id];
  const causeBlock = `<h3>실행 중 감지된 특이 사건</h3>
    ${diag
      ? `<ul class="notes">${diag.events.map((e) => `<li>${escapeHtml(e.summary)}</li>`).join("")}</ul>`
      : `<p class="muted">테스트 실패 후 재수정이나 같은 파일 반복 읽기 같은 특이 사건은 감지되지 않았습니다. 일반적인 실행 과정의 자연스러운 편차로 보입니다.</p>`}`;
  box.innerHTML = base
    ? `<h3>BASE와 어디서 차이가 났나요?</h3>
       <ul class="notes">${parts.map((p) =>
         `<li><b>${p.label} (${signed(p.d)} 토큰)</b> — ${componentNote(p.key, run, base)}</li>`).join("")}</ul>
       ${causeBlock}`
    : causeBlock;
}

/* ---------- run charts ---------- */

function drawTimeline(turns) {
  const width = boxWidth("timeline", 560);
  const compact = width < 460;
  const padL = compact ? 54 : 64, padR = 14, padT = 28, padB = 34;
  if (unchanged("timeline", chartSignature(width, state.runId))) return;
  const height = 250, plot = height - padT - padB;
  const svg = frame("timeline", width, height);
  const max = Math.max(1, ...turns.map((r) => num(r.context_tax_tokens)));
  const count = Math.max(1, turns.length);
  const step = (width - padL - padR) / count;
  const gap = step > 8 ? 3 : step > 3.5 ? 1 : 0.4;
  const bw = Math.max(1, step - gap);

  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 6, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = fmt((max * (4 - i)) / 4);
  }
  el("line", { x1: padL, y1: padT + plot, x2: width - padR, y2: padT + plot, class: "axis-line" }, svg);
  el("text", { x: 4, y: 11, class: "tick unit-label" }, svg).textContent = "단위: 토큰";

  if (!turns.length) return;
  const peak = turns.reduce((a, b) => (num(a.context_tax_tokens) > num(b.context_tax_tokens) ? a : b), turns[0]);
  const tickEvery = count > 45 ? 10 : 5;

  turns.forEach((row, idx) => {
    const v = num(row.context_tax_tokens);
    const h = (v / max) * plot;
    const x = padL + idx * step;
    const isPeak = peak && row.turn === peak.turn;
    const path = el("path", {
      d: barUp(x, padT + plot - h, bw, h, 3),
      fill: isPeak ? ink("--series-2") : ink("--seq-400"),
    }, svg);
    hoverable(path, `<b>턴 ${row.turn}</b><br>${toolSummary(row) || "도구 호출 없음"}<br>
      새로 들어온 양 <b>${fmt(num(row.result_tokens))}</b> 토큰<br>반복 청구량 <b>${fmt(v)}</b> 토큰`);
    if (isPeak && h > 0) {
      const lx = Math.min(width - padR - 26, Math.max(padL + 26, x + bw / 2));
      const label = el("text", { x: lx, y: padT + plot - h - 6, class: "mark-label", "text-anchor": "middle" }, svg);
      label.textContent = fmt(v);
    }
    if (idx % tickEvery === 0) {
      const t = el("text", { x: x + bw / 2, y: height - 10, class: "tick", "text-anchor": "middle" }, svg);
      t.textContent = row.turn;
    }
  });
}

function drawGrowth(turns) {
  const width = boxWidth("growth", 560);
  const compact = width < 460;
  const padL = compact ? 54 : 64, padR = 14, padT = 28, padB = 34;
  if (unchanged("growth", chartSignature(width, state.runId))) return;
  const height = 220, plot = height - padT - padB;
  const svg = frame("growth", width, height);
  const max = Math.max(1, ...turns.map((r) => num(r.context_tokens)));
  const step = turns.length > 1 ? (width - padL - padR) / (turns.length - 1) : 0;
  const px = (i) => padL + i * step;
  const py = (v) => padT + plot - (v / max) * plot;

  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 6, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = fmt((max * (4 - i)) / 4);
  }
  el("text", { x: 4, y: 11, class: "tick unit-label" }, svg).textContent = "단위: 토큰";
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

  const tickEvery = turns.length > 45 ? 10 : 5;
  const dotR = step > 9 ? 4 : 2.5;
  turns.forEach((r, i) => {
    const c = el("circle", { cx: px(i), cy: py(num(r.context_tokens)), r: dotR, fill: ink("--seq-400"),
      stroke: ink("--surface-1"), "stroke-width": 1.5 }, svg);
    hoverable(c, `<b>턴 ${r.turn}</b><br>전체 문맥 크기 <b>${fmt(num(r.context_tokens))}</b> 토큰`);
    if (i % tickEvery === 0) {
      const t = el("text", { x: px(i), y: height - 10, class: "tick", "text-anchor": "middle" }, svg);
      t.textContent = r.turn;
    }
  });
}

function drawReconcileCheck() {
  const note = document.getElementById("reconcile-check");
  if (!note) return;
  const run = state.summary.find((r) => `${r.run_date}/${r.run_id}` === state.runId);
  if (!run) { note.textContent = ""; return; }
  const sum = num(run.reconcile_opening) + num(run.reconcile_output)
    + num(run.reconcile_tool_result) + num(run.reconcile_discarded);
  const diff = num(run.reconcile_observed) - sum;
  note.textContent = `합계 검증: 실제 다시 읽힌 문맥 합계 ${fmt(num(run.reconcile_observed))} 토큰 · `
    + `네 항목(첫 턴 문맥·모델 답변·도구 결과·중간 요약 제외분) 합계 ${fmt(sum)} 토큰 · 오차 ${fmt(diff)} 토큰`;
  note.className = diff === 0 ? "note" : "note warn";
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
  const width = boxWidth("tools", 560);
  const compact = width < 460;
  const rowH = 30, padL = compact ? 92 : 124, padR = compact ? 64 : 88, padT = 6;
  const height = Math.max(60, padT + items.length * rowH + 6);
  if (unchanged("tools", chartSignature(width, state.runId))) return;
  const svg = frame("tools", width, height);
  if (!items.length) return;
  const max = Math.max(...items.map(([, v]) => v)) || 1;
  const span = Math.max(60, width - padL - padR);

  items.forEach(([name, value], i) => {
    const y = padT + i * rowH;
    const w = (value / max) * span;
    const path = el("path", { d: barRight(padL, y + 5, w, rowH - 14, 4), fill: ink("--seq-400") }, svg);
    hoverable(path, `<b>${name}</b><br>누적 반복 청구량 <b>${fmt(value)}</b> 토큰`);
    const label = el("text", { x: padL - 8, y: y + rowH / 2 + 1, class: "mark-label", "text-anchor": "end" }, svg);
    label.textContent = name;
    const val = el("text", { x: padL + w + 6, y: y + rowH / 2 + 1, class: "mark-label" }, svg);
    val.textContent = fmt(value);
  });
}

/* 회차별 평균 비용 추세. 개요와 같은 과제·모델 선택, 같은 유효 실행 기준을 쓴다. */
function drawTrend(data) {
  const legend = document.getElementById("trend-legend");
  const note = document.getElementById("trend-note");
  if (!legend || !note) return;
  const { runs, fallback } = plottableRuns(data);
  const byCondition = new Map();
  [...runs].sort((a, b) => conditionSort(a.condition, b.condition)).forEach((r) => {
    if (!byCondition.has(r.condition)) byCondition.set(r.condition, new Map());
    const perDate = byCondition.get(r.condition);
    perDate.set(r.run_date, [...(perDate.get(r.run_date) || []), r.cost]);
  });
  const dates = [...new Set(runs.map((r) => r.run_date))].sort(byBatch);

  const width = boxWidth("trend", 560);
  const compact = width < 460;
  const padL = compact ? 48 : 64, padR = compact ? 88 : 98, padT = 28, padB = 34;
  const height = 240, plot = height - padT - padB;
  if (unchanged("trend", chartSignature(width, `${runs.length}/${fallback}/${cohortKey()}`))) return;
  legend.replaceChildren();
  const svg = frame("trend", width, height);
  if (!runs.length) {
    el("text", { x: width / 2, y: height / 2, class: "tick", "text-anchor": "middle" }, svg).textContent = "표시할 실행 기록이 없습니다";
    note.textContent = emptyReason(data);
    return;
  }
  el("text", { x: 4, y: 11, class: "tick unit-label" }, svg).textContent = "평균 비용 (USD)";
  const max = Math.max(0.1, ...runs.map((r) => r.cost)) * 1.15;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plot * i) / 4;
    el("line", { x1: padL, y1: y, x2: width - padR, y2: y, class: "grid-line" }, svg);
    const t = el("text", { x: padL - 6, y: y + 4, class: "tick", "text-anchor": "end" }, svg);
    t.textContent = usd((max * (4 - i)) / 4);
  }

  const step = dates.length > 1 ? (width - padL - padR) / (dates.length - 1) : 0;
  const px = (i) => (dates.length > 1 ? padL + i * step : (padL + width - padR) / 2);
  const py = (v) => padT + plot - (v / max) * plot;

  const endLabels = [];
  [...byCondition.entries()].forEach(([condition, perDate]) => {
    const { role, dash } = conditionStyle(condition);
    const pts = dates.map((d, i) => {
      const arr = perDate.get(d);
      return arr ? [px(i), py(mean(arr)), arr, d] : null;
    }).filter(Boolean);
    if (pts.length > 1) {
      el("path", { d: pts.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" "),
        fill: "none", stroke: ink(role), "stroke-width": 2, "stroke-linejoin": "round",
        "stroke-dasharray": fallback ? "4 4" : dash, "data-cond": condition, class: "trend-line" }, svg);
    }
    pts.forEach(([x, y, arr, d]) => {
      const r = step > 22 || pts.length === 1 ? 4.5 : step > 10 ? 3 : 0;
      const c = r
        ? el("circle", { cx: x, cy: y, r, fill: fallback ? ink("--surface-1") : ink(role),
          stroke: fallback ? ink(role) : ink("--surface-1"), "stroke-width": fallback ? 2 : 1.8, "data-cond": condition }, svg)
        : el("circle", { cx: x, cy: y, r: 6, fill: "transparent" }, svg);
      hoverable(c, `<b>${condition}</b><br>${d}<br>평균 비용 <b>${usd(mean(arr))}</b><br>실행 ${fmt(arr.length)}건`);
    });
    if (pts.length) endLabels.push({ condition, role, x: pts[pts.length - 1][0], y: pts[pts.length - 1][1] });
  });
  drawFocusKeys("trend-legend", "trend", [...byCondition.keys()], (condition) => {
    const { role, dash } = conditionStyle(condition);
    return `<svg class="swatch-line" width="18" height="11" aria-hidden="true">
      <line x1="0" y1="6" x2="18" y2="6" stroke="${ink(role)}" stroke-width="2"
        stroke-dasharray="${fallback ? "4 4" : dash}"></line></svg>`;
  });

  endLabels.sort((a, b) => a.y - b.y).forEach((label, i, all) => {
    if (i > 0 && label.y - all[i - 1].y < 13) label.y = all[i - 1].y + 13;
    const t = el("text", { x: label.x + 8, y: label.y + 4, class: "mark-label", fill: ink(label.role),
      "data-cond": label.condition }, svg);
    t.textContent = label.condition;
  });

  const perLabel = compact ? 86 : 78;
  const step_ = Math.max(1, Math.ceil(dates.length / Math.max(1, Math.floor((width - padL - padR) / perLabel))));
  dates.forEach((d, i) => {
    if (i % step_ && i !== dates.length - 1) return;
    if (i === dates.length - 1 && (dates.length - 1) % step_ && dates.length > 1
        && px(i) - px(i - ((dates.length - 1) % step_)) < perLabel) return;
    const t = el("text", { x: px(i), y: height - 10, class: "tick", "text-anchor": "middle" }, svg);
    t.textContent = compact ? d.replace(/^\d{4}-/, "") : d;
  });
  const parts = [dates.length < 2
    ? `회차가 ${fmt(dates.length)}개뿐이라 추세선 대신 점으로 표시했습니다.`
    : `총 ${fmt(dates.length)}개 회차의 평균 비용 흐름입니다. 점에 마우스를 올리면 그 회차의 값이 보입니다.`];
  if (fallback) parts.push(`${emptyReason(data)} 점선과 속이 빈 점은 참고용입니다.`);
  note.textContent = parts.join(" ");
}

/* 결과 검증 맨 위 결론. 선택한 과제·모델의 날짜별 비교(comparison.csv)에서 직접 센다. */
function drawVerifyVerdict(data) {
  const title = document.getElementById("verify-verdict");
  const note = document.getElementById("verify-note");
  if (!title || !note) return;
  const scope = [state.promptId, state.modelId].filter(Boolean).join(" · ");
  const scopeHtml = scope ? ` <small class="muted">(${escapeHtml(scope)} 기준)</small>` : "";
  const verdict = judge(data);
  if (verdict.kind === "none") {
    title.innerHTML = `날짜별로 비교할 수 있는 데이터가 없습니다${scopeHtml}`;
    note.textContent = emptyReason(data);
    return;
  }
  title.innerHTML = (verdict.kind === "clear"
    ? `${verdict.clears.map((r) => r.condition).join(", ")}은(는) 흔들림 폭을 넘는 차이를 보였습니다`
    : "날짜별로 나눠 봐도 확실히 앞서는 기법은 없었습니다") + scopeHtml;
  const perDay = comparisonRows().filter((r) => r.cost_delta_pct !== "");
  const lower = new Map();
  perDay.forEach((r) => {
    const [win, all] = lower.get(r.condition) || [0, 0];
    lower.set(r.condition, [win + (num(r.cost_delta_pct) < 0 ? 1 : 0), all + 1]);
  });
  const counts = [...lower.entries()].sort((a, b) => conditionSort(a[0], b[0]))
    .map(([c, [win, all]]) => `<code>${escapeHtml(c)}</code> ${fmt(all)}번 중 ${fmt(win)}번`);
  const ids = new Set(data.runs.map((r) => r.run_id));
  const evaluated = state.results.filter((r) => ids.has(r.run_id) && r.evaluation_ran === "True");
  const passed = evaluated.filter((r) => r.evaluation_passed === "True").length;
  note.innerHTML = `같은 날 <code>BASE</code>보다 비용이 낮았던 횟수는 ${counts.join(", ")}입니다.
    ${verdict.kind === "unclear" ? "다만 그 차이는 모두 같은 설정끼리의 흔들림 폭 안에 있었습니다." : ""}
    ${evaluated.length ? `공개 테스트를 돌린 ${fmt(evaluated.length)}건 중 ${fmt(passed)}건이 통과했습니다.` : ""}`;
}

/* 그래프 아래 기법 이름에 마우스를 올리면 그 기법만 진하게, 나머지는 옅게. 떼면 원래대로. */
function focusChart(svgId, keysId, condition) {
  const svg = document.getElementById(svgId);
  const keys = document.getElementById(keysId);
  if (!svg) return;
  svg.querySelectorAll("[data-cond]").forEach((node) => {
    const mine = !condition || node.dataset.cond === condition;
    node.style.opacity = mine ? "1" : "0.12";
    if (node.classList.contains("trend-line")) {
      node.setAttribute("stroke-width", condition && mine ? "3.5" : "2");
    }
  });
  if (condition) svg.querySelectorAll(`[data-cond="${condition}"]`).forEach((n) => svg.appendChild(n));
  if (keys) keys.querySelectorAll(".trend-key").forEach((key) => {
    key.classList.toggle("is-dim", Boolean(condition) && key.dataset.cond !== condition);
    key.classList.toggle("is-on", key.dataset.cond === condition);
  });
}

function drawTable(turns) {
  const countEl = document.getElementById("table-count");
  if (countEl) countEl.textContent = `(${commas(turns.length)}턴)`;
  const cols = [
    ["turn", "턴", false, "right"],
    ["tools", "호출한 도구", false, "left"],
    ["result_tokens", "새로 들어온 토큰", false, "right"],
    ["context_tax_tokens", "반복 청구 토큰", false, "right"],
    ["targets", "대상 파일·명령", true, "left"],
    ["context_tokens", "전체 문맥 크기", true, "right"],
    ["output_tokens", "모델 답변 토큰", true, "right"],
  ];
  const table = document.getElementById("table");
  if (!table) return;
  table.innerHTML = "";
  const head = table.insertRow();
  cols.forEach(([, label, extra, align]) => addHeader(head, label, { extra, align }));
  turns.forEach((r) => {
    const row = table.insertRow();
    cols.forEach(([key, , extra, align]) => {
      const value = key === "tools" ? (toolSummary(r) || "—")
        : key === "targets" ? (targetPhrase(r, 2) || "—")
        : key === "turn" ? commas(num(r.turn)) : fmt(num(r[key]));
      addCell(row, value, { extra, align });
    });
  });
}

function drawKpis(turns) {
  const kpis = document.getElementById("kpis");
  if (!kpis) return;
  kpis.innerHTML = "";
  if (!turns.length) return;
  const run = state.summary.find((r) => `${r.run_date}/${r.run_id}` === state.runId) || {};
  const totalTax = turns.reduce((a, r) => a + num(r.context_tax_tokens), 0);
  const validity = num(run.measurable) ? "포함" : `제외 (${friendlyInvalid(run.invalid_reason)})`;
  const testText = run.critical_pass === "pass"
    ? "통과"
    : run.critical_pass === "fail"
      ? "실패"
      : (run.quality_score ? `${Number(run.quality_score).toFixed(0)}점` : "—");
  const cards = [
    ["기법", run.condition || "—"],
    ["비용 (API 환산)", run.cost_usd ? usd(Number(run.cost_usd)) : "—"],
    ["대화 횟수", `${commas(turns.length)}턴`],
    ["반복 청구 토큰 (context tax)", fmt(totalTax)],
    ["핵심 공개 테스트 (critical pass)", testText],
    ["평균 집계", validity],
  ];
  cards.forEach(([label, value]) => {
    const box = document.createElement("div");
    box.className = "kpi";
    box.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
    kpis.appendChild(box);
  });

  const data = corpus();
  const r = data.runs.find((x) => x.key === state.runId);
  const line = document.getElementById("provenance");
  if (!line) return;
  if (!r) { line.textContent = ""; return; }
  const washoutText = r.washoutGap === null
    ? "회차의 첫 실행"
    : r.washoutGap >= 4200
      ? `직전 실행과 ${fmt(r.washoutGap)}초 간격 (캐시 대기 시간 충족)`
      : `직전 실행과 ${fmt(r.washoutGap)}초 간격 (<b class="warn">캐시 대기 시간 70분 미달</b>)`;
  line.innerHTML = [
    `모델: ${escapeHtml(r.model || "미기록")}`,
    `소요 시간: ${(r.duration / 60).toFixed(1)}분`,
    `도구 호출: ${fmt(r.toolCalls)}회`,
    `변경 파일: ${fmt(r.changedFiles)}개`,
    `첫 턴 캐시 읽기: ${fmt(r.firstCacheRead)} 토큰`,
    washoutText,
    `보조 모델 사용량: ${fmt(r.auxTokens)} 토큰`,
  ].join(" · ");
}

/* ---------- render ---------- */

function runsGroupedByCondition() {
  const allowed = new Set(buildRuns().map((r) => r.key));
  const byId = new Map();
  state.activity.forEach((r) => {
    const id = `${r.run_date}/${r.run_id}`;
    if (allowed && !allowed.has(id)) return;
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
  const conditions = [...groups.keys()].sort(conditionSort);
  if (!state.condition || !groups.has(state.condition)) {
    // 처음에는 BASE가 아닌 첫 기법을 보여 준다. 실행 상세는 BASE와의 비교가 핵심이라서다.
    state.condition = conditions.find((c) => c !== "BASE") || conditions[0] || null;
  }

  const picker = document.getElementById("condition-picker");
  if (!picker) return;
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
      state.runId = entries[entries.length - 1].id;
      render();
    });
    picker.appendChild(button);
  });

  const entries = state.condition ? groups.get(state.condition) : [];
  if (!entries.some((entry) => entry.id === state.runId)) {
    state.runId = entries.length ? entries[entries.length - 1].id : null;
  }

  const list = document.getElementById("run-select");
  if (!list) return;
  list.innerHTML = "";
  entries.forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.id;
    option.textContent = `${entry.run_date} · ${String(entry.run_id).replace(/^[0-9a-f]{8,}-/, "")}`;
    option.selected = entry.id === state.runId;
    list.appendChild(option);
  });
  list.onchange = () => { state.runId = list.value; render(); };

  const countLabel = document.getElementById("run-picker-count");
  if (countLabel) countLabel.textContent = `(${fmt(entries.length)}건)`;
}

function render() {
  drawPicker("promptId", "prompt-picker", "prompt_id");
  drawPicker("modelId", "model-picker", "model");
  const data = corpus();
  drawScope(data);
  const methodTitle = document.getElementById("method-title");
  if (methodTitle) methodTitle.textContent = `비교한 ${knownConditions().length}가지 기법`;
  drawArchive(data);
  const visibleIds = new Set(data.runs.map((r) => r.run_id));
  drawBench(state.results.filter((r) => visibleIds.has(r.run_id)));
  drawVerdict(data);
  drawKpiStrip(data);
  drawCorpusKpis(data);
  drawDelta(data);
  drawStrip(data);
  drawOverviewTable(data);
  drawConditionTable(data);
  drawVerifyVerdict(data);
  drawTrend(data);

  drawRunPicker();
  drawTopTurns(data);
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

const VIEWS = ["overview", "run", "verify", "settings"];

function showView(view) {
  state.view = VIEWS.includes(view) ? view : "overview";
  VIEWS.forEach((name) => {
    const viewEl = document.getElementById(`view-${name}`);
    if (viewEl) viewEl.hidden = name !== state.view;
  });
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.view === state.view));
  });
  if (location.hash.slice(1) !== state.view) location.hash = state.view;
  render();
}

/* ---------- token-bench 실행 결과 (결과 검증 탭) ---------- */

/* 이 배열의 이름과 순서는 token_bench/publish.py의 CSV_COLUMNS와 반드시 같아야
   한다(같은 스키마를 두 곳에 둘 수밖에 없어서 tests/test_web.py가 일치를 검사한다). */
const CSV_COLUMNS = [
  "run_id", "batch_id", "condition_id", "repeat_index", "content_id",
  "auth_method", "api_provider", "claude_version", "model", "status",
  "evaluation_ran", "evaluation_passed", "num_turns", "cost_usd",
  "input_tokens", "output_tokens", "cache_creation_input_tokens",
  "cache_read_input_tokens", "started_at", "finished_at", "duration_seconds",
];

const missing = (v) => v === undefined || v === "";
const orNull = (v) => (missing(v) ? null : Number(v));

function meanPresent(values) {
  const present = values.filter((v) => v !== null && !Number.isNaN(v));
  return present.length === 0 ? null : present.reduce((a, b) => a + b, 0) / present.length;
}

function fixed(value, digits = 2) {
  return value === null ? "—" : value.toFixed(digits);
}

function summarizeByCondition(records) {
  const byCondition = new Map();
  for (const r of records) {
    if (!byCondition.has(r.condition_id)) byCondition.set(r.condition_id, []);
    byCondition.get(r.condition_id).push(r);
  }
  return [...byCondition.entries()].map(([conditionId, rows]) => {
    const ok = rows.filter((r) => r.status === "succeeded");
    const evaluated = ok.filter((r) => r.evaluation_ran === "True");
    const passed = evaluated.filter((r) => r.evaluation_passed === "True");
    return {
      conditionId,
      runCount: ok.length,
      totalCount: rows.length,
      avgCost: meanPresent(ok.map((r) => orNull(r.cost_usd))),
      avgTurns: meanPresent(ok.map((r) => orNull(r.num_turns))),
      avgOutputTokens: meanPresent(ok.map((r) => orNull(r.output_tokens))),
      avgCacheReadTokens: meanPresent(ok.map((r) => orNull(r.cache_read_input_tokens))),
      passRate: evaluated.length === 0 ? null : passed.length / evaluated.length,
      evaluatedCount: evaluated.length,
    };
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function cell(row, text) {
  const td = row.insertCell();
  td.textContent = text;
  return td;
}

function drawBench(records) {
  const note = document.getElementById("bench-status");
  const summaryBody = document.querySelector("#summary-table tbody");
  const detailBody = document.querySelector("#detail-table tbody");
  if (!note || !summaryBody || !detailBody) return;
  summaryBody.innerHTML = "";
  detailBody.innerHTML = "";

  if (records.length === 0) {
    note.textContent = "선택한 범위에 게시된 실행 결과가 없습니다.";
    return;
  }
  note.textContent = `총 ${commas(records.length)}건의 실행 결과를 표시하고 있습니다.`;

  for (const s of summarizeByCondition(records)) {
    const row = summaryBody.insertRow();
    addCell(row, conditionLabel(s.conditionId), { align: "left" });
    addCell(row, s.runCount === s.totalCount
      ? `${commas(s.runCount)}건`
      : `${commas(s.runCount)} / ${commas(s.totalCount)}건`);
    addCell(row, s.avgCost === null ? "—" : usd(s.avgCost));
    addCell(row, fixed(s.avgTurns, 1), { extra: true });
    addCell(row, commas(s.avgOutputTokens), { extra: true });
    addCell(row, commas(s.avgCacheReadTokens), { extra: true });
    addCell(row, s.passRate === null ? "—"
      : `${(s.passRate * 100).toFixed(0)}% (${commas(s.evaluatedCount)}건)`);
  }

  for (const r of records) {
    const row = detailBody.insertRow();
    addCell(row, conditionLabel(r.condition_id), { align: "left" });
    addCell(row, friendlyStatus(r.status), { align: "left" });
    addCell(row, missing(r.cost_usd) ? "—" : usd(Number(r.cost_usd)));
    addCell(row, missing(r.num_turns) ? "—" : commas(Number(r.num_turns)));
    addCell(row, r.evaluation_ran === "True" ? (r.evaluation_passed === "True" ? "통과" : "실패") : "—");
    addCell(row, r.run_id, { extra: true, align: "left", className: "mono-cell" });
    addCell(row, missing(r.repeat_index) ? "—" : commas(Number(r.repeat_index)), { extra: true });
    addCell(row, missing(r.model) ? "—" : r.model, { extra: true, align: "left" });
    addCell(row, missing(r.started_at) ? "—" : r.started_at.slice(0, 16).replace("T", " "), { extra: true, align: "left" });
    addCell(row, missing(r.finished_at) ? "—" : r.finished_at.slice(0, 16).replace("T", " "), { extra: true, align: "left" });
  }
}

/* ---------- boot ---------- */

async function load(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return toRecords(parseCsv(await response.text()));
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
       <p class="sub">${escapeHtml(error.message)}</p>
       <p class="muted">저장소 루트에서 <code>python3 -m http.server</code>를 실행한 뒤
       <code>/web/</code>을 여세요. 파일을 직접 열면(<code>file://</code>) 브라우저가 CSV 읽기를 차단합니다.</p>
       </section>`);
  }

  try {
    const res = await fetch("../data/run-diagnostics.json");
    state.diagnostics = res.ok ? await res.json() : {};
  } catch (error) {
    console.warn("진단 데이터를 불러오지 못했습니다:", error);
    state.diagnostics = {};
  }

  try {
    state.results = await load("../data/token-bench-results.csv");
  } catch (error) {
    const statusNode = document.getElementById("bench-status");
    if (statusNode) {
      statusNode.textContent = `실행 결과 원본을 불러오지 못했습니다: ${error.message}`;
    }
  }

  document.querySelectorAll("#tabs button").forEach((b) => {
    b.addEventListener("click", () => showView(b.dataset.view));
  });
  addEventListener("hashchange", () => showView(location.hash.slice(1)));

  document.querySelectorAll(".toggle-cols-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTable = document.getElementById(btn.dataset.target);
      if (!targetTable) return;
      const expanded = targetTable.classList.toggle("show-extra-cols");
      btn.setAttribute("aria-expanded", String(expanded));
      btn.textContent = expanded ? "세부 열 접기" : "세부 열 펼치기";
    });
  });

  document.querySelectorAll("details.fold").forEach((detailEl) => {
    detailEl.addEventListener("toggle", () => {
      if (!detailEl.open) return;
      detailEl.querySelectorAll("svg[data-sig]").forEach((svg) => { svg.dataset.sig = ""; });
      render();
    });
  });

  const themeButton = document.getElementById("theme");
  if (themeButton) {
    themeButton.addEventListener("click", () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark";
      document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
      themeButton.setAttribute("aria-pressed", String(!dark));
      render();
    });
  }

  let resizing = null;
  addEventListener("resize", () => {
    clearTimeout(resizing);
    resizing = setTimeout(render, 150);
  });

  // 처음 화면은 유효한 실행이 가장 많은 과제·모델 조합으로 연다. 특정 과제 이름에 기대지 않는다.
  if (!state.promptId && !state.modelId) {
    const counts = new Map();
    state.summary
      .filter((r) => num(r.measurable) === 1 && r.prompt_id && !r.prompt_id.startsWith("legacy:"))
      .forEach((r) => {
        const key = JSON.stringify([r.prompt_id, r.model]);
        counts.set(key, (counts.get(key) || 0) + 1);
      });
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
    if (top) [state.promptId, state.modelId] = JSON.parse(top[0]);
  }

  showView(location.hash.slice(1) || "overview");
}

if (typeof document !== "undefined") boot();

/* "비교한 기법": 이름은 항상 보이고, 설명만 접었다 펼 수 있다. */
(function setupMethodToggle() {
  if (typeof document === "undefined") return;
  const button = document.getElementById("method-toggle");
  const list = document.getElementById("method-list");
  if (!button || !list) return;
  button.addEventListener("click", () => {
    const collapsed = list.classList.toggle("collapsed");
    button.textContent = collapsed ? "설명 펼치기" : "설명 접기";
    button.setAttribute("aria-expanded", String(!collapsed));
  });
})();

/* Node 기반 테스트(tests/test_web.py)가 순수 함수만 불러 쓸 수 있게 한다. */
if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseCsv, toRecords, summarizeByCondition, CSV_COLUMNS, state, buildRuns, comparisonRows };
}
