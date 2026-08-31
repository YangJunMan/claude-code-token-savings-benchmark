# Claude Code 토큰 절약 방법을 직접 비교해 봤습니다

## 검증 없이 AI로 작성한 글들이 너무 많아서 불편합니다. 신뢰성 있는 정보를 직접 찾아보고 직접 실험 해봅시다

Claude Code에서 `Headroom`, `Caveman`, `RTK`, 그리고 단순한 `be brief` 지시가 실제로 토큰과 비용을 줄여 주는지 비교한 실험입니다.

단순 질문·답변 대신 **코드 작성이 대부분이고 문서 작성도 포함된 개발 작업**을 Claude Sonnet 5(`medium`)에 맡겼습니다. 토큰 사용량과 API 환산 비용만 비교하지 않고, 완성된 코드가 같은 테스트를 통과하는지도 함께 평가했습니다.

이 저장소에서는 다음 두 가지를 할 수 있습니다.

1. **무료 검증:** 제가 측정한 측정값으로 결과표를 다시 만들고 runner 테스트를 실행합니다. 
2. **유료 재실험:** 같은 개발 과제를 Claude Code에 다시 수행시킵니다. Anthropic API 비용이 발생하므로 동의해야만 실행됩니다.

## 저장소 둘러보기

처음 확인할 때는 아래 순서가 가장 이해하기 쉽습니다.

1. [`docs/GENERATED_RESULTS.md`](docs/GENERATED_RESULTS.md) — 공개 CSV에서 다시 계산한 결과표
2. [`docs/FULL_REPORT.md`](docs/FULL_REPORT.md) — 세부 결과, 실패 실행, 해석과 한계
3. [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) — 무료 검증과 유료 재실험 절차
4. [`benchmark/fixture`](benchmark/fixture) — Claude에게 구현하도록 제공한 개발 과제
5. [`benchmark/grader`](benchmark/grader) — agent 작업 공간 밖에서 품질을 평가하는 코드
6. [`benchmark/runner`](benchmark/runner) — 실행 격리, optimizer 활성화, 사용량 수집과 scheduling
7. [`data/published-measurements.csv`](data/published-measurements.csv) — 공개 가능한 정제 측정값의 기준 파일

측정 결과와 공개 도구의 관계는 다음과 같습니다.

| 구분 | 할 수 있는 일 |
|---|---|
| 공개 측정값 | 실제 실험에서 얻은 관측값을 확인합니다. |
| 무료 검증 | 정제된 CSV에서 결과표를 다시 계산하고 runner를 테스트합니다. |
| 유료 재실험 | 같은 질문을 순차 실행과 비용 제한을 보강한 새 프로토콜로 다시 실험합니다. |

유료 재실험은 과거 실행을 그대로 재생하는 것이 아니며, 새 결과를 기존 측정값에 자동으로 합산하지 않습니다.

## 먼저 실험 결론부터

| 적용 방법 | 2회 baseline 평균 대비 비용 | 2회 baseline 평균 대비 처리 토큰 | 품질·Critical tests | 이번 실험에서의 해석 |
|---|---:|---:|---:|---|
| Headroom | **26.4% 감소** | **36.7% 감소** | 1차 98점·6/6, 2차 공개 테스트 통과 | 비용은 경계선, 턴당 context 감소는 견고 |
| `be brief` | **20.2% 감소** | **17.1% 감소** | 96점·5/6 | 설치 없이 적용하기 가장 쉬움 |
| RTK | **16.5% 감소** | **30.1% 감소** | 98점·6/6 | prompt 차이와 짧은 실행의 영향이 섞임 |
| Caveman full | **3.6% 증가** | **14.7% 증가** | 100점·6/6 | 이 작업에서는 절약되지 않음 |

Baseline과 Headroom은 각각 `n=2`, 나머지 절약 방법은 `n=1`입니다. Headroom 2차 실행은 공개 테스트는 통과했지만 held-out grader로 채점하지 않았으므로, 98점·Critical tests 6/6은 1차 실행에만 해당합니다. 품질 점수는 이 개발 과제에 맞춘 기능·필수 파일·문서·근거 rubric의 결과이지, 범용 code-quality 지표가 아닙니다.

여기서 비용은 provider가 보고한 **API-equivalent cost**입니다. 일반 입력, cache 생성, cache 읽기, 출력을 모두 포함합니다. 처리 토큰은 이 네 범주의 합이지만, 범주마다 단가가 다르므로 처리 토큰 수 자체가 청구 금액은 아닙니다.

이 결과를 보편적인 성능 수치로 해석하면 안 됩니다. 동일한 조건의 baseline 두 번도 비용이 **9.78%**, 처리 토큰이 **22.06%** 달랐습니다. Headroom은 두 번 반복했지만 실행 간 비용 편차가 25.1%였고, 나머지 절약 방법은 각각 한 번뿐입니다. 이 실험은 “어떤 방법을 더 반복 검증할 가치가 있는가”를 찾는 탐색적 실험에 가깝습니다.

### 각 방법에서 기대한 절약 방식

- **Headroom:** model에 전달되는 긴 context를 proxy에서 줄입니다.
- **Caveman:** agent의 설명과 행동을 더 간결하게 유도합니다.
- **`be brief`:** plugin 없이 짧은 지시만으로 간결성 효과를 비교합니다.
- **RTK:** shell command의 긴 출력을 줄여 다시 model에 들어가는 context를 줄입니다.

자세한 수치와 한계는 [전체 실험 보고서](docs/FULL_REPORT.md)에서 확인할 수 있습니다.

## 무엇을 비교했나요?

모든 조건에 SQLite 기반 GPU 작업 admission service를 구현하도록 요청했습니다. 주요 작업은 다음과 같습니다.

- Python 애플리케이션과 테스트 작성
- GPU 작업의 admission·queue·상태 관리 구현
- Kubernetes와 CI 파일 작성
- 운영 문서 작성

측정에 포함한 실행은 총 7회입니다. Baseline과 Headroom을 각각 2회, 나머지 절약 방법을 각각 1회 실행했습니다.

| 실행 ID | 조건 | 의미 |
|---|---|---|
| `BASE-01` | Baseline | 아무 절약 방법도 적용하지 않은 첫 번째 기준 실행 |
| `BASE-02` | Baseline | 자연 변동을 확인하기 위한 두 번째 기준 실행 |
| `H-ON-01`, `H-ON-02` | Headroom | Headroom proxy의 기본 `cache` mode 적용 |
| `C-FULL` | Caveman full | Caveman의 full-mode 지시 적용 |
| `C-BRIEF` | `be brief` | plugin 없이 짧게 답하라는 지시만 추가 |
| `R-ON` | RTK | Bash 호출에 RTK `PreToolUse` hook 적용 |

### 조건을 최대한 같게 만든 방법

- 모델은 Claude Sonnet 5, effort는 `medium`, prompt 언어와 핵심 과제는 영어로 통일했습니다.
- 모든 실행은 동일한 fixture의 새 복사본에서 시작했습니다.
- 정답을 미리 보고 맞추지 못하도록 추가 grader test를 작업 디렉터리 밖에 두었습니다.
- 한 실행 안에서는 Claude의 prompt cache가 자연스럽게 작동하도록 허용했습니다.
- 실행 사이에는 고유 nonce와 sentinel MCP tool 이름을 사용해 이전 실행의 cache가 섞일 가능성을 줄였습니다.
- 기능 테스트, 필수 파일, 문서, 최종 응답의 근거를 같은 rubric으로 평가했습니다.

완전히 같지 않았던 부분도 있습니다. 실험 과정에서 prompt variant가 두 개 사용됐고, Headroom과 RTK에는 초기 실행의 과도한 반복을 유발한 1,000줄 제한이 빠졌습니다. 따라서 두 조건의 감소분을 해당 도구만의 효과로 분리할 수 없습니다.

## 가장 쉬운 검증 방법 — 무료

이 단계는 Claude를 호출하지 않으며 `ANTHROPIC_API_KEY`도 필요하지 않습니다. macOS 또는 Linux, Git, Python 3.9 이상만 준비하면 됩니다.

### 1. 저장소 내려받기

```bash
git clone https://github.com/YangJunMan/claude-code-token-savings-benchmark.git
cd claude-code-token-savings-benchmark
```

### 2. 테스트 실행하기

```bash
make setup
make smoke
```

정상이라면 전체 unit test가 통과하고 마지막에 `OK`가 표시됩니다. 이 테스트는 다음을 확인합니다.

- 실행 조건과 비용 제한이 올바르게 적용되는지
- 실행별 디렉터리와 cache 격리값이 분리되는지
- 측정값 집계와 품질 평가가 예상대로 동작하는지
- 기본 명령이 실수로 유료 benchmark를 시작하지 않는지

문제가 생기면 먼저 아래 두 명령의 결과를 확인하세요.

```bash
python3 --version
git --version
```

Python이 3.9보다 낮거나 `python3` 명령을 찾지 못하면 테스트를 실행할 수 없습니다.

### 3. 공개 결과 다시 계산하기

```bash
make report
git diff --exit-code docs/GENERATED_RESULTS.md
```

`make report`는 [`data/published-measurements.csv`](data/published-measurements.csv)를 읽어 [`docs/GENERATED_RESULTS.md`](docs/GENERATED_RESULTS.md)를 다시 만듭니다. 두 번째 명령이 아무 내용도 출력하지 않고 종료되면, 새로 계산한 표가 저장소에 공개된 표와 같다는 뜻입니다.

이 과정은 **공개 측정값의 계산과 프로그램 동작을 검증**합니다. 비공개 원본 대화나 모든 provider event를 복원하는 과정은 아닙니다.

## Claude Code로 직접 재실험하기 — 유료, 선택 사항

> 여기부터는 Anthropic API 비용이 발생합니다. 결과만 확인하려면 위의 무료 검증까지만 수행해도 됩니다.

실행 환경과 도구 설치 방법은 운영체제 및 도구 버전에 따라 달라질 수 있으므로, 먼저 [재현 가이드](docs/REPRODUCTION.md)를 읽어 주세요.

### 1. 예상 실행 조건과 최대 비용 확인

```bash
make estimate
```

이 명령은 API를 호출하지 않습니다. 공개 재현용 `REPRODUCTION_PLAN`은 여섯 작업을 최대 50 turn씩 순차 실행합니다. 과거 실행을 기준으로 잡은 보수적인 전체 계획 한도는 **$15**, 작업당 상한은 **$2.50**입니다. 이는 실제 청구액 보장이 아니라 실행 전 계획값입니다. 저장소의 기존 7-condition `benchmark/config.json`과는 별도 경로입니다.

### 2. 필요한 도구 확인

먼저 무료 검증의 `make setup`을 수행한 뒤 [재현 가이드](docs/REPRODUCTION.md)에 따라 Headroom, Caveman, RTK를 설치합니다. 그다음 아래 명령을 실행합니다.

```bash
make preflight
```

검사가 실패하면 출력에 표시된 도구나 경로를 먼저 해결해야 합니다. `make preflight`는 유료 모델 호출을 하지 않지만, 현재는 실행 파일과 필수 경로의 존재 여부만 검사합니다. 지원 flag와 plugin의 실제 활성화까지 보장하지 않으므로 첫 유료 실행 전에 version과 설치 상태를 직접 확인해야 합니다.

### 3. 새 실행 디렉터리와 명시적 동의로 시작

```bash
printf 'Anthropic API key: '
read -rs ANTHROPIC_API_KEY
printf '\n'
export ANTHROPIC_API_KEY

python3 -m benchmark.runner.public_cli benchmark \
  --confirm-paid-run \
  --max-budget-usd 18 \
  --run-root benchmark/runs/reproduction-001 \
  --report-dir benchmark/reports/reproduction-001
```

안전장치는 다음과 같습니다.

- `--confirm-paid-run`이 없으면 실행하지 않습니다.
- `ANTHROPIC_API_KEY`가 없으면 OAuth로 우회하지 않고 중단합니다.
- 기존 run 증거를 덮어쓰지 않도록 빈 `--run-root`만 허용합니다.
- 작업은 병렬이 아니라 순차로 실행합니다.
- 예상 누적 비용이 전체 한도를 넘기 전에 다음 작업을 중단합니다.
- 각 Claude Code process에도 `$2.50` 상한을 전달합니다.

`--run-root`와 `--report-dir`에는 매번 새로운 이름을 사용하세요. 현재 `--report-dir`는 기존 디렉터리의 `reproduction-summary.json`을 덮어쓸 수 있습니다. 실행이 끝나면 각 run의 증거는 `--run-root` 아래에, 실행 상태·비용·품질 요약은 `--report-dir/reproduction-summary.json`에 저장됩니다. 공개 결과와 같은 비교표까지 자동 생성하지는 않습니다.

주의할 점도 있습니다. 자동화 과정은 Claude Code의 `bypassPermissions`를 사용하므로 **OS sandbox가 아닙니다**. tool subprocess가 API credential을 상속하거나 fixture 밖의 경로와 network에 접근할 수 있습니다. 신뢰할 수 없는 prompt나 repository에는 사용하지 마세요. 이 저장소의 CI는 유료 명령을 실행하지 않습니다.

## 결과를 어떻게 해석했나요?

### Headroom

첫 실행만 보면 비용이 35.6% 감소했지만, 두 번째 실행을 포함한 평균은 **26.4% 감소**로 내려갔습니다. H-ON 두 실행의 비용 편차도 25.1%여서 총비용은 경계선 지표입니다. 반면 턴당 context는 41.4% 감소했고 H-ON 내부 편차는 10.6%였습니다. H-ON 두 값과 baseline 두 값의 범위도 겹치지 않았습니다. Headroom이 안정적으로 줄인 것은 전체 비용보다 요청마다 다시 읽는 context 크기였습니다. 다만 prompt의 1,000줄 제한이 baseline과 달랐으므로 순수 Headroom 효과로 완전히 분리할 수는 없습니다.

### `be brief`

plugin 설치 없이 prompt에 짧게 답하라는 지시만 추가했습니다. 품질 점수는 baseline과 같았고 비용은 20.2% 낮았습니다. 이번 실험만 놓고 보면 가장 간단하게 적용해 볼 수 있는 방법입니다.

### RTK

집계상 비용과 토큰은 감소했지만, hook이 실제로 바꾼 Bash command는 7개 중 1개였습니다. 실행이 더 적은 turn에 끝났고 prompt 제한도 baseline과 달라서 **관찰된 절감 전체를 RTK의 효과라고 단정할 수 없습니다**.

### Caveman full

응답 문장은 짧아졌지만, 코드 작업에서는 prose가 전체 사용량에서 차지하는 비중이 작았습니다. turn과 context가 늘면서 최종 토큰과 비용도 증가했습니다. 즉, 절약 도구는 이름만 보고 항상 켜기보다 작업 성격에 맞는지 확인해야 합니다.

## 이 실험에서 확인할 수 있는 것

이 저장소는 높은 절감률 하나를 홍보하기보다 다음 과정을 공개하는 데 목적이 있습니다.

- 기준 실행도 반복해 자연 변동을 먼저 측정한 과정
- 토큰·비용뿐 아니라 결과물 품질까지 같이 평가한 방법
- 실패한 실행 비용도 전체 실험 비용에서 숨기지 않은 기록
- 원인을 분리하기 어려운 결과를 강한 결론으로 포장하지 않은 판단
- API key 없이 확인할 수 있는 데이터·테스트와 유료 실행을 분리한 설계

측정에 포함한 실행 비용은 약 **$11.62**였고, 제외된 실패 실행까지 포함한 전체 실험 비용은 약 **$18.33**였습니다.

## 한계와 공개 범위

- Headroom은 2회, 나머지 treatment는 1회라 통계적 유의성이나 신뢰구간을 제시할 수 없습니다.
- Headroom 2차 실행은 공개 테스트만 통과했으며 held-out grader 점수는 없습니다.
- 실험 과정에서 prompt variant 두 개가 사용됐습니다. Headroom과 RTK에는 baseline의 1,000줄 제한이 빠져 있어 treatment 효과를 완전히 분리하지 못했습니다.
- **이 저장소의 harness는 결함 수정본입니다.** 공개 수치를 생산한 실행들은 수정 과정 중에 나왔기 때문에, 지금 이 트리로 재실험하면 같은 숫자가 그대로 재현되지는 않습니다. 다만 재실험을 막던 결함들은 모두 고쳐져 있습니다. 고친 내용은 hidden test 채점을 stdout 파싱 대신 JSON 결과로 받고 5회 다수결로 flaky를 안정화한 것, `max_turns`로 잘리거나 파일을 하나도 바꾸지 않은 실행을 무효로 처리한 것, untracked 신규 파일을 diff와 채점에 포함한 것, 중복이던 세 대조군을 `BASE` 하나로 합치고 baseline과 H-ON을 반복 실행하도록 한 것, prompt의 턴 예산을 실행 설정에서 주입해 불일치를 없앤 것입니다.
- 서비스 부하, model·tool version, 재시도 여부에 따라 결과가 달라질 수 있습니다.
- 개인정보와 local path 등이 포함될 수 있어 원본 transcript는 공개하지 않았습니다.
- 공개 CSV로 결과표는 재계산할 수 있지만, 모든 API event를 독립적으로 감사할 수는 없습니다.

따라서 이 결과는 “Headroom은 비용을 항상 26.4% 절약한다”는 주장이 아닙니다. 현재 더 견고한 관찰은 **턴당 context 41.4% 감소**이며, 비용 절감률은 turn 수 변동에 따라 달라졌습니다. 같은 작업을 더 반복하고 절감 폭이 baseline 변동보다 큰지를 확인해야 더 강한 결론을 낼 수 있습니다.

## 실용적인 결론

이번 실험에서 가장 부담 없이 다시 확인할 수 있는 후보는 `be brief`였습니다. 어떤 방법이든 baseline을 먼저 반복해 자연 변동을 확인하고, 절감 폭이 그 변동보다 클 때만 효과가 있다고 판단해야 합니다. Headroom, RTK, Caveman은 항상 켜기보다 실제 workload에서 해당 mechanism이 충분히 작동하는지 측정한 뒤 선택하는 편이 안전합니다.

모델 선택은 이 저장소의 비교 대상이 아닙니다. 한국어·영어 차이는 별도 실험으로 측정했으며 요약은 다음과 같습니다.

지시문과 주석처럼 짧고 압축하기 어려운 텍스트에서는 한국어가 확실히 더 많은 토큰을 사용했습니다. 한국어 텍스트의 글자당 토큰도 영어의 약 2~2.9배였습니다. 그러나 **코딩 에이전트 전체**에서는 차이가 적었습니다. 출력의 약 80%가 코드·식별자·도구 인자처럼 언어와 관계없는 내용이었기 때문입니다. 전체 출력 차이는 7.7%, 비용 차이는 9.4%였고 둘 다 실행 편차보다 작았습니다. 문서 작성 실험에서도 비슷했습니다. 한국어는 글자당 토큰을 약 2.4배 사용했지만 같은 내용을 영어의 절반 이하 글자로 표현했고, 두 효과가 서로 상쇄돼 문서 전체 토큰 차이는 5~14%에 그쳤습니다. 실행 편차보다는 작았습니다.

> 한국어가 글자당 토큰을 더 많이 쓰는 것은 맞지만, 코딩 에이전트 전체 비용이 2~3배 늘어나는 것은 아닙니다.

그래서 비용만 보고 모든 작업을 영어로 강제할 필요는 없지만, **긴 system prompt**나 **장문의 문서**를 매번 보내는 구조라면 **영어가 유리**합니다.

License: MIT. 자세한 내용은 [`LICENSE`](LICENSE)를 확인하세요.
