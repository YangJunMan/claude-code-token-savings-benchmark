// index.html의 "실험 설정" 탭. token_bench serve가 띄우는 로컬 API를 호출해
// 조건을 고르고, estimate -> approve -> enqueue 순서로 실험을 등록한다.
// 공개 배포본에서도 같은 탭이 보이지만, 로컬 서버가 없으면 그 사실을 알린다.

const API_BASE = "http://127.0.0.1:8787";

let currentPlan = null;
let currentPlanPath = null;

async function fetchJson(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const body = await res.json();
  if (!res.ok) {
    throw new Error(body.error || `${path} 요청이 ${res.status}로 실패했다.`);
  }
  return body;
}

/* 도구가 없어 지금 못 돌리는 조건은 고르지 못하게 하고, 왜 그런지와 어떻게
   설치하는지를 그 자리에 적는다. clone 직후에도 남은 조건으로 바로 실험할 수
   있어야 한다. */
function renderConditionList(conditions) {
  const container = document.getElementById("condition-list");
  container.innerHTML = "";
  container.className = "";
  for (const c of conditions) {
    const reasons = c.unavailable_reasons || [];
    const available = reasons.length === 0;

    const row = document.createElement("div");
    row.className = available ? "condition-row" : "condition-row unavailable";

    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = c.id;
    checkbox.checked = available;
    checkbox.disabled = !available;
    checkbox.className = "condition-checkbox";
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(` ${c.id}`));
    row.appendChild(label);

    if (!available) {
      const why = document.createElement("p");
      why.className = "note";
      why.textContent = `설치되지 않음 — ${reasons.join(", ")}.`;
      row.appendChild(why);
      if (c.repository_url) {
        const repository = document.createElement("a");
        repository.href = c.repository_url;
        repository.target = "_blank";
        repository.rel = "noopener noreferrer";
        repository.textContent = "공식 GitHub repository";
        row.appendChild(repository);
      }
    }
    container.appendChild(row);
  }
}

function selectedConditionIds() {
  return [...document.querySelectorAll(".condition-checkbox:checked")].map(
    (el) => el.value
  );
}

async function loadConditions() {
  const body = await fetchJson("/api/conditions");
  renderConditionList(body.conditions);
}

/* 계획을 읽을 수 있는 형태로만 보여 준다. 원본 JSON 전체가 아니라 무엇을
   몇 번 돌리는지, 얼마나 기다리는지, 어떤 인증으로 도는지다. */
function renderPlan(plan) {
  const repeats = new Map();
  for (const run of plan.runs) {
    repeats.set(run.condition_id, (repeats.get(run.condition_id) || 0) + 1);
  }

  const kpis = document.getElementById("plan-kpis");
  kpis.innerHTML = "";
  const cards = [
    ["실행할 스킬", String(repeats.size)],
    ["총 실행", `${plan.run_count}회`],
    ["실행당 제한 시간", `${plan.timeout_seconds}초`],
    ["인증", plan.auth && plan.auth.auth_method ? plan.auth.auth_method : "—"],
  ];
  for (const [label, value] of cards) {
    const box = document.createElement("div");
    box.className = "kpi";
    box.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
    kpis.appendChild(box);
  }

  const tbody = document.querySelector("#plan-table tbody");
  tbody.innerHTML = "";
  for (const [conditionId, count] of repeats) {
    const row = tbody.insertRow();
    row.insertCell().textContent = conditionId;
    row.insertCell().textContent = `${count}회`;
  }

  document.getElementById("cost-disclaimer").textContent = plan.cost_disclaimer;
  // 추적용 식별자. 전체 해시는 plan.json에 있으니 여기서는 앞머리만 보여 준다.
  document.getElementById("plan-digest").textContent =
    `batch ${plan.batch_id} · digest ${plan.digest.slice(0, 12)}…`;
}

async function onPlan() {
  const status = document.getElementById("status");
  try {
    const include = selectedConditionIds();
    if (include.length === 0) {
      throw new Error("최소 하나의 조건을 선택하세요.");
    }
    const timeoutSeconds = Number(
      document.getElementById("timeout-seconds").value
    );
    const promptPath = document.getElementById("prompt-path").value.trim();
    const preset = document.getElementById("prompt-preset").value;
    if (preset && promptPath) {
      throw new Error("프리셋과 직접 경로를 동시에 지정할 수 없습니다.");
    }

    const payload = {
      include,
      timeout_seconds: timeoutSeconds,
    };
    if (preset) {
      payload.preset = preset;
    } else if (promptPath) {
      payload.prompt_path = promptPath;
    }

    const body = await fetchJson("/api/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    currentPlan = body.plan;
    currentPlanPath = body.plan_path;

    document.getElementById("plan-section").hidden = false;
    renderPlan(currentPlan);
    status.textContent = "계획을 만들었습니다. 내용을 확인하고 등록하세요.";
  } catch (err) {
    status.textContent = `계획 생성 실패: ${err.message}`;
  }
}

/* 승인과 등록을 버튼 하나로 처리한다. 사용자가 digest를 따라 입력하는 단계는
   두지 않고(사용자 요청), 화면에 보이는 그 계획의 digest를 그대로 보낸다.
   계획이 그 사이 바뀌었다면 서버가 digest 불일치로 거부한다. CLI의
   `approve --confirm`은 그대로라 터미널 경로에는 확인 단계가 남아 있다. */
async function onSubmit() {
  const status = document.getElementById("status");
  try {
    if (!currentPlan) throw new Error("먼저 실행 계획을 만드세요.");
    const confirmDigest = currentPlan.digest;

    const approval = await fetchJson("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_path: currentPlanPath,
        confirm_digest: confirmDigest,
      }),
    });

    await fetchJson("/api/enqueue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_path: currentPlanPath,
        approval_path: approval.approval_path,
      }),
    });

    status.textContent =
      "승인하고 큐에 등록했습니다. `token_bench work`를 실행해 처리하세요.";
    await refreshStatus();
  } catch (err) {
    status.textContent = `등록 실패: ${err.message}`;
  }
}

const EVENT_TAGS = {
  text: "[답변]",
  tool_use: "[도구 호출]",
  tool_result: "[도구 결과]",
  result: "[종료]",
};

/* 실행 중인 작업 하나의 stdout을 폴링해 보여준다. Windows/WSL/Linux/macOS
   차이는 여기 없다 — token_bench serve가 파일을 읽어 JSON으로 주고, 이
   함수는 그 JSON을 그릴 뿐이라 OS별 분기가 필요 없다. */
async function updateLiveLog(runningJob) {
  const section = document.getElementById("live-log-section");
  if (!runningJob) {
    section.hidden = true;
    return;
  }
  try {
    const body = await fetchJson(`/api/log?run_id=${encodeURIComponent(runningJob.run_id)}`);
    section.hidden = false;
    document.getElementById("live-log-run-id").textContent = runningJob.run_id;
    const log = document.getElementById("live-log");
    log.innerHTML = "";
    if (body.events.length === 0) {
      log.innerHTML = `<p class="muted">아직 출력이 없습니다.</p>`;
      return;
    }
    for (const event of body.events) {
      const row = document.createElement("div");
      row.className = "event";
      const text = event.name
        ? `${event.name} ${event.input || ""}`
        : event.text || "";
      row.innerHTML = `<span class="tag tag-${event.kind}">${EVENT_TAGS[event.kind] || event.kind}</span><div class="body"></div>`;
      row.querySelector(".body").textContent = text;
      log.appendChild(row);
    }
    log.scrollTop = log.scrollHeight;
  } catch (err) {
    section.hidden = true;
  }
}

async function refreshStatus() {
  // 다른 탭을 보고 있으면 폴링하지 않는다.
  const view = document.getElementById("view-settings");
  if (view && view.hidden) return;
  try {
    const body = await fetchJson("/api/status");
    const runningJob = body.jobs.find((j) => j.status === "running") || null;

    // 표는 내용이 바뀔 때만 다시 그린다 — 3초마다 갈아 끼우면 화면이 미세하게
    // 흔들린다. 실시간 로그는 running 작업의 상태가 그대로여도 계속 갱신한다.
    const serialized = JSON.stringify(body.jobs);
    if (serialized !== lastJobsJson) {
      lastJobsJson = serialized;
      const tbody = document.querySelector("#jobs-table tbody");
      tbody.innerHTML = "";
      for (const job of body.jobs) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${job.run_id}</code></td>
          <td>${job.condition_id}</td>
          <td>${job.status}</td>
          <td>${job.enqueued_at}</td>
        `;
        tbody.appendChild(tr);
      }
    }
    await updateLiveLog(runningJob);
  } catch (err) {
    // 서버가 아직 응답하지 않을 수 있다(초기 로딩 등). 조용히 넘어간다.
  }
}

/* "새 스킬 추가하기" 모달. 딱 하나의 주입 방식만 받는다 — headroom처럼 두 개
   (proxy+env) 조합하는 조건은 이 화면 범위 밖이고, 그런 경우엔 터미널의
   `token_bench add-condition`을 쓰라고 안내한다. "이미 깔려 있다"는 전제라
   도구 설치 확인(requires_tools)은 따로 묻지 않는다 — proxy를 고르면 묻는
   실행 파일 이름을 그대로 쓴다. */
let idTouchedByUser = false;

/* 경로/이름/repository에서 조건 id를 자동으로 만든다. 사용자가 id를 직접
   고치면 그 뒤로는 자동 채움을 멈춘다. conditions.py의 id 정규식(소문자·
   숫자·점·밑줄·하이픈)에 맞춘다. */
function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function repoNameFromUrl(url) {
  const match = url.match(/github\.com\/[^/]+\/([^/.]+)/);
  return match ? match[1] : "";
}

function basenameNoExt(path) {
  const last = path.split("/").pop() || "";
  return last.replace(/\.[^.]+$/, "");
}

function suggestConditionId() {
  if (idTouchedByUser) return;
  const type = document.getElementById("ac-injection-type").value;
  const val = (id) => document.getElementById(id).value.trim();
  let source = "";
  if (type === "proxy") source = val("ac-inj-binary") || repoNameFromUrl(val("ac-inj-repo"));
  else if (type === "env") source = val("ac-inj-name");
  else if (type === "plugin_dir") source = repoNameFromUrl(val("ac-inj-repo")) || basenameNoExt(val("ac-inj-path"));
  else source = basenameNoExt(val("ac-inj-path"));
  const suggestion = slugify(source);
  if (suggestion) document.getElementById("ac-id").value = suggestion;
}

const INJECTION_FIELD_VISIBILITY = {
  prompt_overlay: ["ac-inj-path-field", "ac-inj-text-field"],
  config_ref: ["ac-inj-path-field"],
  plugin_dir: ["ac-inj-path-field", "ac-inj-repo-field"],
  env: ["ac-inj-name-field", "ac-inj-value-field"],
  proxy: ["ac-inj-binary-field", "ac-inj-args-field", "ac-inj-ready-field", "ac-inj-repo-field"],
};

function updateInjectionFieldVisibility() {
  const type = document.getElementById("ac-injection-type").value;
  const visible = new Set(INJECTION_FIELD_VISIBILITY[type] || []);
  for (const id of [
    "ac-inj-path-field", "ac-inj-text-field", "ac-inj-name-field",
    "ac-inj-value-field", "ac-inj-binary-field", "ac-inj-args-field",
    "ac-inj-ready-field", "ac-inj-repo-field",
  ]) {
    document.getElementById(id).hidden = !visible.has(id);
  }
  suggestConditionId();
}

/* {injection, requiresTools, toolProbes} 또는 status에 채울 에러 메시지를
   반환한다. proxy는 검증기가 binary를 requires_tools에도 요구해서 여기서
   같이 만든다 — 사용자에게 따로 묻지 않는다. */
function buildInjectionFromForm() {
  const type = document.getElementById("ac-injection-type").value;
  const val = (id) => document.getElementById(id).value.trim();

  if (type === "prompt_overlay") {
    if (!val("ac-inj-path")) return { error: "경로가 필요합니다." };
    const injection = { type, path: val("ac-inj-path") };
    if (val("ac-inj-text")) injection.text = val("ac-inj-text");
    return { injection, requiresTools: [], toolProbes: {} };
  }
  if (type === "config_ref") {
    if (!val("ac-inj-path")) return { error: "경로가 필요합니다." };
    return { injection: { type, path: val("ac-inj-path") }, requiresTools: [], toolProbes: {} };
  }
  if (type === "plugin_dir") {
    if (!val("ac-inj-path")) return { error: "플러그인 디렉터리 경로가 필요합니다." };
    if (!val("ac-inj-repo")) return { error: "플러그인 방식은 공식 GitHub repository가 필요합니다." };
    return {
      injection: { type, path: val("ac-inj-path") },
      requiresTools: [],
      toolProbes: {},
      repositoryUrl: val("ac-inj-repo"),
    };
  }
  if (type === "env") {
    if (!val("ac-inj-name")) return { error: "환경변수 이름이 필요합니다." };
    return { injection: { type, name: val("ac-inj-name"), value: val("ac-inj-value") }, requiresTools: [], toolProbes: {} };
  }
  // proxy
  if (!val("ac-inj-binary")) return { error: "프록시로 띄울 실행 파일 이름이 필요합니다." };
  if (!val("ac-inj-repo")) return { error: "프록시 방식은 공식 GitHub repository가 필요합니다." };
  const binary = val("ac-inj-binary");
  return {
    injection: {
      type,
      binary,
      args: val("ac-inj-args").split(",").map((a) => a.trim()).filter(Boolean),
      ready_path: val("ac-inj-ready") || "/readyz",
    },
    requiresTools: [binary],
    toolProbes: { [binary]: ["--version"] },
    repositoryUrl: val("ac-inj-repo"),
  };
}

function resetAddConditionForm() {
  document.getElementById("ac-id").value = "";
  document.getElementById("ac-repeat").value = "1";
  document.getElementById("ac-injection-type").value = "prompt_overlay";
  for (const id of ["ac-inj-path", "ac-inj-text", "ac-inj-name", "ac-inj-value", "ac-inj-binary", "ac-inj-args", "ac-inj-repo"]) {
    document.getElementById(id).value = "";
  }
  document.getElementById("ac-inj-ready").value = "/readyz";
  idTouchedByUser = false;
  updateInjectionFieldVisibility();
  document.getElementById("ac-status").textContent = "";
}

async function onSubmitAddCondition() {
  const status = document.getElementById("ac-status");
  const id = document.getElementById("ac-id").value.trim();
  if (!id) { status.textContent = "조건 id를 확인하세요."; return; }

  const built = buildInjectionFromForm();
  if (built.error) { status.textContent = built.error; return; }

  const payload = {
    id,
    repeat: Number(document.getElementById("ac-repeat").value) || 1,
    requires_tools: built.requiresTools,
    tool_probes: built.toolProbes,
    injections: [built.injection],
  };
  if (built.repositoryUrl) payload.repository_url = built.repositoryUrl;

  try {
    await fetchJson("/api/add-condition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    status.textContent = `'${id}' 추가했습니다.`;
    closeAddConditionModal();
    await loadConditions();
  } catch (err) {
    status.textContent = `추가 실패: ${err.message}`;
  }
}

function openAddConditionModal() {
  document.getElementById("add-condition-backdrop").hidden = false;
  updateInjectionFieldVisibility();
  document.getElementById("ac-id").focus();
}

function closeAddConditionModal() {
  document.getElementById("add-condition-backdrop").hidden = true;
  resetAddConditionForm();
}

function main() {
  document.getElementById("plan-btn").addEventListener("click", onPlan);
  document.getElementById("submit-btn").addEventListener("click", onSubmit);

  document.getElementById("add-condition-btn").addEventListener("click", openAddConditionModal);
  document.getElementById("ac-close-btn").addEventListener("click", closeAddConditionModal);
  document.getElementById("ac-cancel-btn").addEventListener("click", closeAddConditionModal);
  document.getElementById("add-condition-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "add-condition-backdrop") closeAddConditionModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("add-condition-backdrop").hidden) {
      closeAddConditionModal();
    }
  });
  document.getElementById("ac-id").addEventListener("input", () => { idTouchedByUser = true; });
  document.getElementById("ac-injection-type").addEventListener("change", updateInjectionFieldVisibility);
  for (const id of ["ac-inj-path", "ac-inj-name", "ac-inj-binary", "ac-inj-repo"]) {
    document.getElementById(id).addEventListener("input", suggestConditionId);
  }
  document.getElementById("ac-submit-btn").addEventListener("click", onSubmitAddCondition);
  updateInjectionFieldVisibility();
  const badge = document.getElementById("settings-availability");
  loadConditions()
    .then(() => {
      badge.className = "chip ok";
      badge.textContent = `로컬 API 연결됨 · ${API_BASE}`;
    })
    .catch((err) => {
      document.getElementById("condition-list").textContent =
        `조건을 불러오지 못했습니다: ${err.message}`;
      badge.className = "chip warn";
      badge.textContent =
        `${API_BASE}에 연결되지 않음 — "token_bench serve" 실행 후 새로고침`;
    });
  refreshStatus();
  setInterval(refreshStatus, 3000);

  // 탭을 펼친 순간 바로 최신 상태를 보여 준다(다음 폴링까지 기다리지 않도록).
  const view = document.getElementById("view-settings");
  if (view) {
    new MutationObserver(() => {
      if (!view.hidden) refreshStatus();
    }).observe(view, { attributes: true, attributeFilter: ["hidden"] });
  }
}

if (typeof document !== "undefined") {
  main();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { selectedConditionIds, API_BASE };
}
