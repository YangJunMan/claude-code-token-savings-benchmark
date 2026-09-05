# 새 절약법 추가하기

`benchmark/config.json`에 선언 하나를 추가하면 된다. **Python 수정은 없다.**

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
| `id` | 조건 식별자. 실행 디렉터리와 측정값의 키가 되므로 이후 바꾸지 않는다 |
| `label` | 결과표와 웹에 표시되는 이름 |
| `optimizer` | 도구 이름 (보고용) |
| `mechanism` | 아래 네 가지 중 하나 |
| `repeat` | 반복 횟수. 생략하면 1 |

## mechanism 네 가지

절약 도구가 Claude Code에 개입하는 방식은 실제로 네 가지뿐이다.

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

`{port}`와 `{log_path}`는 실행 시 채워진다. runner가 프로세스를 띄우고 `ready_path`가
응답할 때까지 기다린 뒤 `ANTHROPIC_BASE_URL`을 그쪽으로 돌린다.

### `plugin` — Claude Code plugin 적재

```json
"mechanism": "plugin",
"plugin": {
  "path_glob": "~/.claude/plugins/cache/caveman/caveman/*/plugins/caveman",
  "env_override": "CAVEMAN_PLUGIN_DIR",
  "prompt_prefix": "Use the caveman skill in full mode for the entire task.\n\n"
}
```

`prompt_prefix`는 plugin을 적재하는 것만으로 활성화되지 않는 경우에 쓴다.

### `overlay` — prompt에 지시를 덧붙임

```json
"mechanism": "overlay",
"overlay": { "file": "benchmark/prompts/be-brief.txt" }
```

### `hook` — tool 호출 전후에 개입

```json
"mechanism": "hook",
"hook": { "event": "PreToolUse", "matcher": "Bash", "command": "rtk hook claude" }
```

## 선언 하나가 어디까지 도달하나

추가한 조건은 아래 전부에 자동으로 반영된다.

| 단계 | 확인 방법 |
|---|---|
| 처치 적용 | `build_condition`이 해당 mechanism 슬롯만 채운다 |
| 실행 계획 | `repeat` 만큼 실행 목록에 들어간다 |
| 도구 검사 | `make preflight`가 필요한 실행 파일을 찾는다 |
| 결과표 | `label vs baseline` 비교 항목이 생긴다 |
| 웹 | 회차별 추세에 선이 하나 늘어난다 |

확인:

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

## 실험 설계가 구조로 강제된다

각 조건은 mechanism 슬롯을 **하나만** 채운다. 그래서 "모든 처치는 baseline에서 정확히
한 가지만 다르다"는 규칙이 리뷰가 아니라 코드로 지켜진다. 대조군(`BASE`)은
`mechanism`이 `none`인 조건이며, 이것도 선언으로 결정된다.

`tests/test_conditions.py`의 `test_each_treatment_changes_exactly_one_thing_from_the_baseline`이
이 불변식을 감시한다.

## 주의

- `id`는 측정값의 키다. 이미 실행한 조건의 `id`를 바꾸면 과거 회차와 연결이 끊긴다.
- 새 조건을 추가하면 그 회차의 실행 시간이 늘어난다. 조건 사이에는 캐시 만료를 기다리는
  washout(기본 4200초)이 있다.
- 새 도구를 설치한 뒤 `make preflight`가 통과하는지 먼저 확인한다. 유료 실행 중간에
  도구가 없어 실패하면 그때까지의 비용이 낭비된다.
