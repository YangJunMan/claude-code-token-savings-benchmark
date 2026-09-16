# Claude Code 토큰 절약 벤치마크

[![ci](https://github.com/YangJunMan/claude-code-token-savings-benchmark/actions/workflows/ci.yml/badge.svg)](https://github.com/YangJunMan/claude-code-token-savings-benchmark/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> 검증 없이 AI로 작성한 글들이 너무 많아서 불편합니다.
> 신뢰성 있는 정보를 직접 찾아보고 직접 실험해 봅시다.

`Headroom`, `Caveman`, `RTK`, 그리고 단순한 `be brief` 지시가 정말로 Claude Code의
토큰과 비용을 줄여 주는지 **본인의 Claude 구독으로 직접 재 보는** 도구입니다.
같은 개발 과제(SQLite 기반 GPU 작업 admission service)를 조건만 바꿔 실행하고,
토큰·비용뿐 아니라 완성된 코드가 공개 테스트를 통과하는지까지 함께 기록합니다.

**→ 결과 보기: <https://yangjunman.github.io/claude-code-token-savings-benchmark/>**

## 목차

- [빠른 시작](#빠른-시작)
- [무엇을 할 수 있나](#무엇을-할-수-있나)
- [웹 대시보드](#웹-대시보드)
- [실험 흐름 (CLI)](#실험-흐름-cli)
- [최신 결과](#최신-결과)
- [핵심 지표: context tax](#핵심-지표-context-tax)
- [새 절약법 추가하기](#새-절약법-추가하기)
- [데이터 파일](#데이터-파일)
- [저장소 구조](#저장소-구조)
- [알려진 한계](#알려진-한계)
- [문서](#문서)
- [License](#license)

## 빠른 시작

### 요구 사항

| 목적 | 필요한 것 |
|---|---|
| 결과만 보기 | 브라우저 (위 링크) |
| 로컬에서 웹·API 띄우기 | Git, Python 3.11 (추가 패키지 없음) |
| 실험 실행 | 위 + 로그인된 Claude Code CLI (`claude auth status`) |
| Headroom·RTK·Caveman 조건 | 각 도구 설치 (선택 — 없으면 해당 조건만 건너뜀) |

### 한 줄로 시작

macOS · Linux · WSL:

```bash
git clone https://github.com/YangJunMan/claude-code-token-savings-benchmark.git
cd claude-code-token-savings-benchmark
./quickstart.sh
```

Windows (PowerShell):

```powershell
git clone https://github.com/YangJunMan/claude-code-token-savings-benchmark.git
cd claude-code-token-savings-benchmark
.\quickstart.ps1
```

스크립트가 하는 일:

1. `token_bench preflight --skip-unavailable`로 조건별 가용성 확인 (모델 호출 없음)
2. 로컬 실험 API(`127.0.0.1:8787`)와 웹 서버(`127.0.0.1:8765`) 기동
3. 브라우저에서 `http://127.0.0.1:8765/web/#settings` 열기
4. Ctrl+C 시 두 서버 정리

포트는 `WEB_PORT`, `API_PORT` 환경변수로 바꿀 수 있습니다.

### Claude Code 스킬로 시작

이 저장소 안에서 Claude Code에 이렇게 말해도 됩니다.

> 토큰 실험 켜줘

`.claude/skills/token-bench/` 스킬이 가용성 확인 → 실행 계획 제시 →
**사용자 확인 후** 등록·실행 → 결과 해석을 대신 진행합니다.

## 무엇을 할 수 있나

| | 할 수 있는 일 | 필요한 것 | 비용 |
|---|---|---|---|
| 1 | 브라우저에서 턴별 토큰 소모와 원인 보기 | 없음 | 무료 |
| 2 | 집계 로직 테스트 | Python 3.11, `pytest` | 무료 |
| 3 | 같은 실험 직접 재실행 | Claude 구독 로그인 | 구독 사용량 |
| 4 | 내 프롬프트로 실험 | Claude 구독 로그인 | 구독 사용량 |
| 5 | 새 절약법 추가 | JSON 선언 하나 | 구독 사용량 |

## 웹 대시보드

`web/`은 빌드 도구·외부 의존성이 없는 순수 HTML/JS입니다. 한 페이지에 탭 네 개가
있습니다.

| 탭 | 내용 |
|---|---|
| **개요** | 조건별 요약, BASE 대비 조건별 평균, 누적 현황 |
| **실행 상세** | 실행 하나의 턴별 context tax, 툴별 누적, 컨텍스트 성장, **BASE 대비 — 왜 이렇게 갈렸나** |
| **결과 검증** | 조건별 평균 비용·turn 수·토큰, 공개 테스트 통과율, 실행별 원본 값 |
| **실험 설정** | 조건 선택 → 계획 → 승인·등록, 진행 상황 (로컬 `token_bench serve` 필요) |

- 상단 **프롬프트** 선택으로 프리셋(`small`·`large`·`very-large`)과 사용자
  프롬프트(`custom:<hash>`)의 결과를 따로 봅니다. 서로 다른 과제끼리는 비교하지 않습니다.
- **왜 이렇게 갈렸나**는 토큰 차이를 구성요소별로 나눈 뒤, transcript에서 찾은
  실제 사건(예: `turn 29: 테스트 실패 — AttributeError …`, `turn 31: 수정 후 통과`,
  `같은 파일 다시 읽음`)을 턴 번호와 함께 보여줍니다. 감지된 사건이 없으면 그렇다고
  명시합니다. LLM을 호출하지 않는 정규식 탐지입니다(`token_bench/diagnostics.py`).

로컬에서 웹만 띄우려면:

```bash
python3 -m http.server 8765
# http://127.0.0.1:8765/web/
```

> `index.html`을 `file://`로 열면 브라우저가 CSV `fetch`를 막습니다. 반드시 HTTP
> 서버로 띄우세요. `main`에 `web/`·`data/` 변경이 push되면 GitHub Pages로 자동
> 배포됩니다(`.github/workflows/pages.yml`).

## 실험 흐름 (CLI)

웹의 **실험 설정** 탭과 CLI는 같은 함수를 씁니다. 모든 명령은
`python3.11 -m token_bench <명령>` 형태입니다.

```
preflight → estimate → approve → enqueue → work
                                             └─ 성공한 실행마다 자동: collect + publish
```

| 명령 | 하는 일 | 모델 호출 |
|---|---|:---:|
| `inspect` | `benchmark/conditions.json`을 실행 목록으로 펼쳐 출력 | 없음 |
| `prepare` | 조건별 작업 디렉터리·최종 프롬프트·입력 snapshot 생성 | 없음 |
| `preflight` | `claude` CLI·구독 로그인·필요 도구 점검 | 없음 |
| `estimate` | 실행 계획 `plan.json`과 digest 생성 | 없음 |
| `approve` | digest를 직접 입력받아 일치할 때만 `approval.json` 생성 | 없음 |
| `enqueue` | 승인 소비 + 작업 등록 (`.token-bench/state.db`, 멱등) | 없음 |
| `status` | 등록된 작업과 상태 조회 | 없음 |
| `work` | 큐의 작업을 순서대로 실행 (`--once`, `--exit-when-empty`) | **있음** |
| `result` | 실행 하나의 정규화된 `RunResult` 조회 | 없음 |
| `collect` | 턴 단위 CSV·조건 비교·원인 진단 갱신 (`work`가 자동 호출) | 없음 |
| `publish` | 실행 요약을 `data/token-bench-results.csv`에 append (`work`가 자동 호출) | 없음 |
| `serve` | 웹용 로컬 API (`127.0.0.1` 전용) | 없음 |
| `add-condition` | 질문에 답하면서 새 절약법을 `conditions.json`에 추가 | 없음 |

공통 옵션:

- `--only base,be-brief` / `--exclude base` — 조건 고르기 (동시 사용 불가)
- `--skip-unavailable` — 설치 안 된 도구가 필요한 조건은 이유와 공식 repository 링크를 출력하고 건너뜀
- `--preset small|large|very-large` 또는 `--prompt <파일>` — 과제 프롬프트 선택 (동시 사용 불가)

<details>
<summary>터미널에서 직접 실행하는 예</summary>

```bash
python3.11 -m token_bench inspect
python3.11 -m token_bench preflight --skip-unavailable
python3.11 -m token_bench estimate --skip-unavailable --timeout-seconds 3600 --preset small
# 출력된 digest를 눈으로 확인한 뒤:
python3.11 -m token_bench approve --plan .token-bench/runs/<batch_id>/plan.json --confirm <digest>
python3.11 -m token_bench enqueue --plan .token-bench/runs/<batch_id>/plan.json \
                                  --approval .token-bench/runs/<batch_id>/approval.json
python3.11 -m token_bench work --exit-when-empty   # 여기서부터 구독 사용량 소비
```

</details>

<details>
<summary>실행 안전장치</summary>

- **승인 없이는 실행되지 않습니다.** 조건·repeat·입력·인증 방식·timeout 중 하나라도
  바뀌면 digest가 달라져 이전 승인을 재사용할 수 없습니다.
- 구독 실행 비용은 "$0"으로 표시하지 않습니다. 추가 청구 여부는 도구가 확인할 수
  없다는 안내를 항상 함께 표시합니다.
- `work`는 `claude --print --permission-mode bypassPermissions`로 실행하되, 기본은
  `--safe-mode`로 개인 스킬·플러그인·hook을 배제합니다. hook(RTK)·plugin(Caveman)
  조건이 배치에 있으면 배치 전체가 `--setting-sources project` 격리로 돕니다.
- `timeout_seconds`는 프로세스 수준에서 강제합니다.
- 실행 후 작업 디렉터리에서 `benchmark/fixture/tests/` 공개 테스트를 돌립니다. 테스트
  파일이 삭제·변조됐으면 통과해도 `passed=false`로 기록합니다.
- preflight 실패·timeout처럼 결과가 불명확하면 자동 재시도 없이 멈춥니다. 과제 테스트
  실패는 유효한 측정이므로 계속 진행합니다.
- 같은 상태 저장소에는 worker 하나만 상주할 수 있습니다(파일 락).

</details>

## 최신 결과

2026-09-16 회차, 프리셋 `small`, 조건별 1회, `claude-sonnet-5`.

| 조건 | 비용 (API-equivalent) | BASE 대비 비용 | BASE 대비 처리 토큰 | turn | 공개 테스트 |
|---|---:|---:|---:|---:|:---:|
| `base` | $1.53 | — | — | 35 | 통과 |
| `be-brief` | $1.47 | −4.2% | −4.7% | 36 | 통과 |
| `caveman-full` | $1.42 | −7.4% | −3.6% | 36 | 통과 |
| `rtk` | $1.71 | +11.7% | +6.4% | 34 | 통과 |

**이 숫자로 효과를 판단하면 안 됩니다.** 조건별 1회뿐이고 `base`도 반복하지 않아
자연 변동 폭을 모릅니다. 위 차이가 변동 폭보다 큰지 확인하려면 `base`를 먼저 여러 번
돌려야 합니다.

`headroom`은 이 회차에서 실행됐지만 제외했습니다. 모델이 과제 도중 만든 버그
(`AttributeError`, turn 29 실패 → turn 31 수정)로 turn 수가 늘었고, 이는 Headroom의
압축 동작과 무관하므로 비교 데이터로 쓰지 않았습니다.

회차가 쌓이면 웹 대시보드가 자동으로 반영합니다.

## 핵심 지표: context tax

tool result가 컨텍스트를 키우면 그 비용은 한 번으로 끝나지 않습니다. 이후 모든 턴이
그 내용을 다시 읽기 때문에 **남은 턴 수만큼 거듭 청구**됩니다.

```
result      = 컨텍스트 증가분 − 직전 턴 output   (provider 보고값의 뺄셈, 추정 아님)
context tax = result × 이후 남은 턴 수
```

예를 들어 5,000 토큰짜리 tool result 뒤에 25턴이 남았다면 125,000 토큰이 다시
청구됩니다. 합계만 보여 주는 결과표에는 이 효과가 드러나지 않습니다.

다시 청구된 컨텍스트는 초기 컨텍스트 · 모델 출력 · tool result · 버려진 컨텍스트
넷으로 나뉩니다. 넷의 합이 provider 총계와 맞지 않거나 중간에 compaction이 일어난
실행은 `measurable=0`으로 표시하고 평균에서 뺍니다.

→ [활동 단위 토큰 측정](docs/ACTIVITY-LOG.md)

## 새 절약법 추가하기

```bash
python3.11 -m token_bench add-condition
```

질문에 답하면 됩니다. injection type을 직접 고를 필요 없습니다. Python 코드는
건드리지 않습니다. → [새 절약법 추가하기](docs/ADDING-A-SKILL.md)

현재 선언된 조건:

| id | 주입 | 도구 |
|---|---|---|
| `base` | 없음 | — |
| `be-brief` | `prompt_overlay` | — |
| `headroom` | `proxy`, `env` | [Headroom](https://github.com/chopratejas/headroom) |
| `caveman-full` | `plugin_dir`, `prompt_overlay` | [Caveman](https://github.com/JuliusBrussee/caveman) |
| `rtk` | `config_ref` | [RTK](https://github.com/rtk-ai/rtk) |

→ [새 절약법 추가하기](docs/ADDING-A-SKILL.md)

## 데이터 파일

`data/`는 웹의 유일한 출처이며 Git에 커밋되는 공개 데이터입니다. 모두 append 방식이고
같은 `run_id`는 중복 기록되지 않습니다. 조건별로 파일을 나누지 않고 `condition`·
`prompt_id` 컬럼으로 구분합니다.

| 파일 | 단위 | 내용 |
|---|---|---|
| `activity-log.csv` | 턴 | 턴별 토큰, tool, context tax |
| `run-summary.csv` | 실행 | 비용, turn 수, 처리 토큰, 품질, 측정 가능 여부 |
| `comparison.csv` | 회차 × 프롬프트 × 조건 | BASE 대비 증감률 (`run-summary.csv`에서 재계산) |
| `run-diagnostics.json` | 실행 | 감지된 사건(테스트 실패·복구, 파일 재읽기). 사건이 있는 실행만 기록 |
| `token-bench-results.csv` | 실행 | `RunResult` 원본 요약 (결과 검증 탭) |

사용자 프롬프트는 로컬 경로 대신 내용 해시(`custom:<sha8>`)로만 기록합니다. 결측값은
`0`이 아니라 빈 칸입니다.

## 저장소 구조

```
benchmark/
  conditions.json   조건 선언 — 새 절약법이 추가되는 유일한 곳
  prompts/          과제 프롬프트, 프리셋, 조건별 overlay
  settings/         조건별 Claude Code 설정
  fixture/          Claude에게 구현시키는 개발 과제와 공개 테스트
token_bench/        CLI, 준비·점검·승인·큐, worker, 집계, 원인 진단, 로컬 API
web/                대시보드 (의존성 없음)
data/               공개 측정값
docs/               가이드
quickstart.sh       macOS · Linux · WSL 실행 스크립트
quickstart.ps1      Windows 실행 스크립트
.claude/skills/     Claude Code 운영 스킬
.token-bench/       로컬 실행 상태와 작업 디렉터리 (커밋하지 않음)
```

## 알려진 한계

- **조건 간 대기 시간 없음.** `work`는 작업을 연달아 실행합니다. 앞 실행의 provider
  prompt cache가 다음 실행에 영향을 줄 수 있습니다.
- **반복 수 1회가 기본.** 효과를 주장하려면 `repeat`을 늘리고 `base` 변동 폭부터 재야 합니다.
- **OS 실행 검증 범위.** 실제 실험은 macOS에서만 돌렸습니다. Linux·Windows는 CI에서
  단위 테스트와 스크립트 문법만 확인합니다.
- **품질은 공개 테스트 통과 여부만.** 숨은 테스트나 점수 채점은 없습니다.
- **원인 진단은 패턴 기반.** 테스트 실패·복구와 같은 파일 재읽기만 감지합니다.
- **turn 상한 없음.** 설치된 Claude Code CLI에 turn 수를 강제하는 플래그가 없어 받지 않습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [ACTIVITY-LOG.md](docs/ACTIVITY-LOG.md) | context tax 정의, 검증 방법, 데이터 스키마 |
| [ADDING-A-SKILL.md](docs/ADDING-A-SKILL.md) | 새 절약법 선언 방법, 아직 선언할 수 없는 조건 |
| [FULL_REPORT.md](docs/FULL_REPORT.md) | 2026-09-06 회차 상세 분석 (지난 파이프라인 기준, 원본 CSV는 제거됨) |

## License

MIT. 자세한 내용은 [`LICENSE`](LICENSE)를 확인하세요.
