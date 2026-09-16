# 새 절약법 추가하기

세 가지 방법이 있습니다. 순서대로 쉬운 쪽부터입니다.

## 웹에서 추가하기 (가장 쉬움)

```bash
./quickstart.sh              # 또는 .\quickstart.ps1 (Windows)
```

**실험 설정** 탭 → **+ 새 스킬 추가하기**. 이 절약법이 어떻게 켜지는지(프롬프트
지시문 / 설정 파일 / 플러그인 / 환경변수 / 프록시) 하나만 고르면 됩니다. 조건
id는 입력한 값에서 자동으로 채워집니다. 저장하면 바로 **조건 고르기** 목록에
나타나 체크만 하면 실험에 넣을 수 있습니다.

이 화면은 **주입 방식을 하나만** 받습니다. Headroom처럼 두 가지를 동시에
써야 하는 절약법은 아래 CLI 방법을 쓰세요.

## 대화형으로 추가하기 (터미널, 복합 절약법)

JSON 스키마와 injection type을 몰라도 됩니다. 질문에 답하면 검증까지 마치고
`conditions.json`에 씁니다.

```bash
python3.11 -m token_bench add-condition
```

"이 절약법을 쓰려면 별도 CLI 도구를 설치해야 하나?", "이 절약법은 어떻게
켜집니까?" 같은 질문에 답하면 됩니다. 마지막 질문(주입 방식)은 여러 번 답할 수
있습니다 — 예를 들어 Headroom처럼 proxy와 env 둘 다 필요하면 하나씩 두 번
추가합니다. 잘못된 값은 파일에 쓰기 전에 걸러지고, 실패하면 아무것도 쓰지
않습니다.

## 직접 JSON 작성하기 (스크립트로 여러 개 추가할 때)

`benchmark/conditions.json`에 선언 하나를 직접 넣어도 됩니다.
`token_bench` 파이썬 코드는 건드리지 않습니다.

```json
{
  "schema_version": 1,
  "conditions": [
    {
      "id": "my-skill",
      "repeat": 1,
      "requires_tools": ["newthing"],
      "tool_probes": { "newthing": ["--version"] },
      "repository_url": "https://github.com/example/newthing",
      "injections": [
        { "type": "config_ref", "path": "benchmark/settings/newthing.json" }
      ]
    }
  ]
}
```

선언을 넣으면 `inspect`·`prepare`·`preflight`·`estimate`·`work`·`publish`와 웹의
**실험 설정** 탭이 한꺼번에 그 조건을 알아봅니다.

## 필드

| 필드 | 뜻 |
|---|---|
| `id` | 조건 식별자. 결과 CSV의 `condition_id`와 `run_id`에 그대로 들어갑니다. 중복 불가. |
| `repeat` | 같은 조건을 몇 번 실행할지. 1 이상의 정수. |
| `requires_tools` | 실행 전에 PATH에 있어야 하는 실행 파일 이름. `preflight`가 검사합니다. |
| `tool_probes` | `requires_tools` 각각의 버전을 확인할 인자 배열. 예: `{"newthing": ["--version"]}`. |
| `repository_url` | 필요한 도구의 공식 HTTPS GitHub repository. 설치 명령 대신 이 링크만 제공합니다. |
| `injections` | 이 조건이 Claude Code에 끼어드는 방식. 아래 다섯 가지만 허용합니다. |

## 주입(injection) 다섯 가지

| `type` | 필드 | 실행 시 하는 일 |
|---|---|---|
| `prompt_overlay` | `path` | 그 파일 내용을 과제 프롬프트 뒤에 덧붙입니다. |
| `config_ref` | `path` | `claude --settings <path>`로 설정 파일(hook 등)을 넘깁니다. |
| `plugin_dir` | `path` | `claude --plugin-dir <path>`로 플러그인을 그 세션에만 로드합니다. `~`와 `*` 한 단계를 허용합니다. |
| `env` | `name`, `value` | 자식 프로세스 환경변수를 덧붙입니다. |
| `proxy` | `binary`, `args`, `ready_path` | 실행 동안만 proxy를 띄우고 `ANTHROPIC_BASE_URL`을 그쪽으로 돌립니다. 포트(`{port}`)와 로그 경로(`{log_path}`)는 runner가 채웁니다. |

### 격리 모드 — hook·plugin은 `--safe-mode`에서 꺼진다

`--safe-mode`는 개인 스킬·플러그인·훅·MCP를 통째로 끕니다. 그런데 RTK(hook)와
Caveman(plugin)은 **바로 그 범주를 켜는 것이 처치**라, 그 플래그 아래에서는
처치가 조용히 사라집니다.

그래서 `config_ref`나 `plugin_dir`를 선언한 조건이 배치에 하나라도 있으면,
**배치 전체**가 `--setting-sources project`로 돕니다. 개인 설정은 여전히
배제되지만 runner가 명시적으로 넘긴 `--settings`/`--plugin-dir`는 살아 있습니다.
조건마다 격리가 달라지면 처치 말고도 달라지는 것이 생기므로, 모드는 배치 단위로
하나만 씁니다. 선택한 모드는 `plan.json`의 `isolation`과 승인 digest에 들어가고
`result.json`에도 기록됩니다.

`path`는 저장소 루트 기준 상대경로입니다. 참조한 파일이 없으면 `preflight`가
조건 이름과 함께 실패를 알립니다.

runner가 소유한 이름은 조건이 덮어쓸 수 없습니다 — 덮어쓰면 측정의 전제가
무너지기 때문입니다(`token_bench/conditions.py`의 `RESERVED_ENV_NAMES`). 특히
`ANTHROPIC_API_KEY`·`ANTHROPIC_BASE_URL`·`CLAUDE_CODE_OAUTH_TOKEN` 등이 여기
해당합니다.

## 지금 선언되어 있는 조건

| 조건 | 처치 | 주입 | 필요한 것 |
|---|---|---|---|
| `base` | 없음(대조군) | — | — |
| `be-brief` | 짧게 답하라는 지시 | `prompt_overlay` | — |
| `headroom` | 로컬 proxy가 컨텍스트를 다듬음 | `proxy` + `env` | `headroom` 실행 파일 |
| `caveman-full` | 플러그인을 full 모드로 로드 | `plugin_dir` + `prompt_overlay` | caveman 플러그인 설치 |
| `rtk` | `PreToolUse` hook으로 Bash 출력을 압축 | `config_ref` | `rtk` 실행 파일 |

필요한 도구가 없으면 `preflight`가 조건 이름과 함께 무엇이 없는지 알려주고
종료 코드 1을 반환합니다. `--skip-unavailable`을 붙이면 막는 대신 그 조건만
건너뛰고 이유와 공식 `repository_url`을 출력합니다 — 설치 방법과 지원 OS는
각 upstream 문서를 기준으로 확인합니다. 아무것도 설치하지 않은 사람도
`base`·`be-brief`로 바로 실험할 수 있게 하기 위해서입니다.

### 아직 검증되지 않은 것

hook·plugin이 `--setting-sources project` 아래에서 **실제로 발동하는지**는
모델을 호출하는 실행 1회로만 확인할 수 있습니다. 명령·환경·플래그가 프로세스까지
도달하는 것은 `tests/test_treatments.py`가 검사하지만, Claude Code가 그 hook을
실제로 호출했는지는 실행 로그로 확인해야 합니다. 그 전까지 RTK·Caveman 회차
결과를 "처치가 적용된 측정값"으로 읽으면 안 됩니다.
아직 확인하지 않았다는 사실 자체를 `README.md`의 "알려진 한계"에도 적어
두었습니다.

## 확인 절차

```bash
python3.11 -m token_bench inspect --only <새-조건-id>   # 선언이 해석되는지
python3.11 -m token_bench preflight --only <새-조건-id> # 필요한 도구·파일이 있는지
python3.11 -m token_bench estimate  --only <새-조건-id> --timeout-seconds 3600
```

여기까지는 모델을 호출하지 않습니다. 실제 실행은 `approve` → `enqueue` →
`work` 순서로만 시작됩니다 — 자세한 안전장치는 `README.md`의 "실행 안전장치"를
보세요.
