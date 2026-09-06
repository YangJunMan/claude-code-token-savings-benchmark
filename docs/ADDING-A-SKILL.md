# 새 절약법 추가하기

`benchmark/config.json`에 선언 하나만 넣으면 됩니다. **Python은 건드리지 않습니다.**

## 선언

```json
{
  "id": "X-ON",
  "label": "New Skill",
  "optimizer": "newthing",
  "mechanism": "hook",
  "hook": { "event": "PreToolUse", "matcher": "Bash", "command": "newthing hook" }
}
```

| 필드 | 뜻 |
|---|---|
| `id` | 조건 식별자. 실행 디렉터리와 측정값의 키가 되므로 한번 정하면 바꾸지 않습니다 |
| `label` | 결과표와 웹에 표시되는 이름 |
| `optimizer` | 도구 이름 (보고용) |
| `mechanism` | 아래 네 가지 중 하나 |
| `repeat` | 반복 횟수. 생략하면 1 |

## mechanism 네 가지

절약 도구가 Claude Code에 끼어드는 방식은 실제로 네 가지뿐입니다.

### `proxy` — 요청을 중간에서 가공

```json
"mechanism": "proxy",
"proxy": {
  "binary": "headroom",
  "env_override": "HEADROOM_BIN",
  "args": ["proxy", "--port", "{port}", "--mode", "cache", "--log-file", "{log_path}"],
  "ready_path": "/readyz",
  "env": { "ENABLE_TOOL_SEARCH": "true" }
}
```

`{port}`와 `{log_path}`는 실행할 때 채워집니다. runner가 프로세스를 띄우고 `ready_path`가
응답할 때까지 기다린 뒤 `ANTHROPIC_BASE_URL`을 그쪽으로 돌립니다.

### `plugin` — Claude Code plugin 불러오기

```json
"mechanism": "plugin",
"plugin": {
  "path_glob": "~/.claude/plugins/cache/caveman/caveman/*/plugins/caveman",
  "env_override": "CAVEMAN_PLUGIN_DIR",
  "prompt_prefix": "Use the caveman skill in full mode for the entire task.\n\n"
}
```

`prompt_prefix`는 plugin을 불러오는 것만으로는 켜지지 않는 도구에 씁니다.

### `overlay` — prompt에 지시를 덧붙이기

```json
"mechanism": "overlay",
"overlay": { "file": "benchmark/prompts/be-brief.txt" }
```

### `hook` — tool 호출 앞뒤로 끼어들기

```json
"mechanism": "hook",
"hook": { "event": "PreToolUse", "matcher": "Bash", "command": "rtk hook claude" }
```

## 선언 하나가 어디까지 반영되나

추가한 조건은 아래 전부에 자동으로 반영됩니다.

| 단계 | 확인 방법 |
|---|---|
| 처치 적용 | `build_condition`이 해당 mechanism 슬롯만 채웁니다 |
| 실행 계획 | `repeat` 횟수만큼 실행 목록에 들어갑니다 |
| 도구 검사 | `make preflight`가 필요한 실행 파일을 찾습니다 |
| 결과표 | `label vs baseline` 비교 항목이 생깁니다 |
| 웹 | 회차별 추세에 선이 하나 늘어납니다 |

확인해 보려면:

```bash
python3 - <<'PY'
from benchmark.runner.conditions import conditions, build_condition
from benchmark.reports.generate import treatments
c = conditions()["X-ON"]
print(build_condition(c, None))
print(treatments()[-1])
PY

make preflight
```

## 실험 설계가 구조로 강제됩니다

각 조건은 mechanism 슬롯을 **하나만** 채웁니다. 덕분에 "모든 처치는 baseline에서 정확히
한 가지만 다르다"는 규칙이 리뷰가 아니라 코드로 지켜집니다. 대조군(`BASE`)은
`mechanism`이 `none`인 조건이고, 이것 역시 선언으로 정해집니다.

이 불변식은 `tests/test_conditions.py`의
`test_each_treatment_changes_exactly_one_thing_from_the_baseline`이 지킵니다.

## 주의

- `id`는 측정값의 키입니다. 이미 실행한 조건의 `id`를 바꾸면 과거 회차와 연결이 끊깁니다.
- 조건을 하나 더 넣으면 그 회차의 실행 시간이 늘어납니다. 조건 사이에는 캐시가 만료되기를
  기다리는 washout(기본 4200초)이 있기 때문입니다.
- 새 도구를 설치했다면 `make preflight`부터 통과시키세요. 유료 실행 도중에 도구가 없어
  실패하면 그때까지 쓴 비용이 그대로 날아갑니다.
