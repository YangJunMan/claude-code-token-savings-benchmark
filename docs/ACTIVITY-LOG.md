# 활동 단위 토큰 측정

결과표가 말해 주는 것은 "얼마나 줄었나"뿐입니다. 이 문서는 **어디서** 줄었는지 보는
방법을 설명합니다.

## 왜 필요한가

`data/published-measurements.csv`에는 실행 하나가 한 줄, 그것도 합계만 들어 있습니다.
독자는 "Headroom이 36.7% 줄인다"는 결론까지는 볼 수 있지만, 그 절감이 어느 활동에서
나왔는지는 확인할 길이 없습니다. 근거의 해상도를 한 단계 높이는 것이 이 측정의
목적입니다.

## context tax

tool result가 컨텍스트를 키우면 그 비용은 한 번으로 끝나지 않습니다. 남은 턴이 모두 그
내용을 다시 읽기 때문에 **턴 수만큼 거듭 청구**됩니다.

```
턴 컨텍스트 = input + cache_creation + cache_read   (provider 보고값)
result      = 컨텍스트 증가분 − 직전 턴 output
context tax = result × 이후 남은 턴 수
```

`result`는 provider가 보고한 값들을 빼서 얻은 값이지 추정치가 아닙니다. 두 턴 사이에
컨텍스트를 키울 수 있는 것은 모델이 쓴 출력과 도구가 돌려준 결과뿐이므로, 앞의 것을
빼면 뒤의 것이 남습니다.

실측 예를 들면, 파일럿 실행에서 `Read` 15개를 한 턴에 몰아 호출했습니다.

```
입력   4,861 토큰
청구 121,525 토큰   (25.0배)
```

Headroom과 RTK가 노리는 지점이 바로 여기입니다.

## 결과는 호출한 턴에 붙입니다

턴 N이 호출한 도구의 결과는 턴 N+1의 컨텍스트에서 처음 관측됩니다. 그 크기를 턴 N+1에
적어 버리면 **정작 그 턴이 호출한 다른 도구의 몫으로 잘못 잡힙니다.** 그래서 관측한
값을 호출한 턴으로 되돌려 기록합니다. 마지막 턴은 뒤따르는 턴이 없어 결과 크기를 알 수
없으므로 0으로 둡니다.

## 회계가 맞는지 확인합니다

다시 청구된 컨텍스트를 네 갈래로 나눕니다.

| 항목 | 뜻 |
|---|---|
| 초기 컨텍스트 | system prompt, 도구 정의, 과제. 이후 모든 턴이 다시 읽습니다 |
| 모델 출력 | 각 턴의 출력이 대화에 쌓여 이후 턴에 실립니다 |
| tool result | 도구가 돌려준 내용 |
| 버려진 컨텍스트 | 컨텍스트가 줄어든 만큼 (음수) |

이 넷의 합은 provider가 실제로 다시 읽은 양과 **정확히 맞아떨어집니다.** 맞지 않는
실행은 발행하지 않습니다. 페이지가 "분해한 값이 실측과 같다"고 말할 수 있는 근거가
이것입니다.

## 측정 불가 판정

도중에 컨텍스트가 줄어든 실행(compaction)은 회계 자체는 균형을 유지하지만 **측정
불가**로 표시합니다. 버려진 결과는 이후 턴이 다시 읽지 않으므로 context tax가 실제보다
부풀려지는데, 무엇이 버려졌는지는 transcript에서 되살릴 수 없기 때문입니다.

`run-summary.csv`의 `measurable` 열이 이 판정을 담습니다.

## 브라우저에서 보기

발행된 페이지는 <https://yangjunman.github.io/claude-code-token-savings-benchmark/>에 있습니다. 클론한 저장소에서 직접 띄우려면:

```bash
python3 -m http.server 8765
# http://127.0.0.1:8765/web/
```

> `index.html`을 더블클릭해 `file://`로 열면 브라우저가 CSV 읽기를 막습니다.

화면은 둘입니다. **개요**는 쌓인 회차를 모두 합쳐 BASE와 조건별 평균을 견주고,
**실행 상세**는 실행 하나를 턴 단위로 풉니다.

| 실행 상세의 구성 | 보여 주는 것 |
|---|---|
| 실행 요약 | 조건·턴 수·비용·품질, 그리고 위 회계 검증 결과 |
| BASE 대비 | 같은 회차 BASE 평균과의 차이를 네 갈래로 나눈 막대 |
| 실행 리포트 | 어디서 갈렸는지, 어느 턴이 무엇을 하느라 비쌌는지 |
| 턴별 context tax | 각 턴의 도구 호출이 이후 턴들에 걸쳐 청구시킨 총량 |
| 컨텍스트 성장 | 턴이 진행되며 매 턴 다시 실리는 컨텍스트 크기 |
| 툴별 누적 tax | 어떤 도구가 컨텍스트를 가장 많이 불렸는지 |
| 턴 데이터 | 전체 턴 표 (기본은 접혀 있습니다) |

의존성도 빌드 단계도 없습니다. 페이지는 아무것도 다시 계산하지 않고, 모든 수치를 아래
CSV에서 읽어 옵니다.

## 데이터 스키마

### `data/activity-log.csv` — 턴당 한 줄

| 열 | 뜻 |
|---|---|
| `run_date` | 회차. 주 1회 실험이 쌓이면 행만 늘어납니다 |
| `run_id`, `condition` | 실행 식별자와 조건 |
| `turn` | 턴 번호 (1부터) |
| `tools` | 그 턴이 호출한 도구들 (공백 구분) |
| `targets` | 그 도구들이 무엇을 다뤘는지 (` \| ` 구분). 아래 참고 |
| `input_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `output_tokens` | provider 보고값 |
| `context_tokens` | 앞 세 입력 항목의 합 |
| `result_tokens` | 이 턴이 호출한 도구들의 결과 크기 |
| `discarded_tokens` | 설명되지 않는 감소분 (compaction) |
| `context_tax_tokens` | `result_tokens × 이후 남은 턴 수` |
| `compacted` | 이 턴에서 컨텍스트가 줄었는지 |

`context_tokens`·`context_tax_tokens`·`compacted`는 같은 행의 다른 열에서 계산되는
값입니다. 위 기준에 따라 그대로 저장합니다. 특히 `context_tax_tokens`는 그 행만으로는
구할 수 없습니다 — 실행의 총 턴 수를 알아야 합니다.
| `thinking_tokens` | `output_tokens` 중 추론에 쓴 몫 |
| `cache_1h_tokens` | cache write 중 1시간 TTL 몫 (5분 TTL보다 비쌉니다) |
| `stop_reason` | 그 턴이 끝난 이유 (`tool_use` / `end_turn`) |

### `data/comparison.csv` — 회차·조건당 한 줄

BASE 대비 차이와 그 회차의 noise floor입니다. **페이지는 이 값을 계산하지 않고 읽기만
합니다.** 같은 공식이 Python과 JavaScript에 두 벌 있으면 발행된 숫자가 서로 어긋날 수
있어서, 계산은 `benchmark/reports/comparison.py` 한 곳에만 둡니다. `reports/generate.py`의
배치 리포트도 같은 함수를 씁니다.

| 열 | 뜻 |
|---|---|
| `run_date`, `condition` | 회차와 조건 |
| `runs`, `baseline_runs` | 그 회차의 해당 조건 실행 수, BASE 실행 수 |
| `processed_delta_pct`, `cost_delta_pct`, `tax_delta_pct` | BASE 평균 대비 차이(증가가 양수) |
| `quality_delta` | 품질 점수 차이 |
| `noise_processed_pct`, `noise_cost_pct` | 그 회차 BASE 실행끼리의 변동 폭. BASE가 1회뿐이면 빈칸 |

비교는 **회차 안에서** 이뤄집니다. 회차마다 BASE가 다르므로 총계를 가로질러 평균하면
BASE만 돈 회차가 다른 회차의 기준선까지 움직입니다. 페이지는 여기 실린 회차별 차이를
평균할 뿐입니다.

### `data/run-summary.csv` — 실행당 한 줄

`cost_usd`, `quality_score`, `critical_pass`, `turns`, `measurable`, 그리고 위에서 나눈
결과(`reconcile_*`)가 들어갑니다.

**파생값을 저장하는 기준은 "계산하는 곳을 한 군데로 모은다"입니다.** 값이 다른 열에서
계산된다는 이유만으로 빼지 않습니다. 빼면 페이지가 그 공식을 다시 구현해야 하고, 그
순간 같은 숫자를 만드는 자리가 두 곳이 됩니다. 그래서 `reconcile_*`도, 실행별 토큰
합계(`processed_tokens`, `context_tax_tokens`)도 Python이 계산해 여기 적어 둡니다.
개요 화면이 턴 로그에서 필요로 하는 것은 이 두 값뿐이라, 회차가 쌓여도 개요는 가장 큰
파일에 매이지 않습니다.

원본을 남기지 않기로 했으므로, 원본에만 있던 근거도 함께 발행합니다.

| 열 | 뜻 |
|---|---|
| `model` | 그 턴들을 만든 모델. transcript가 알려 주는 값입니다 |
| `duration_seconds` | 실행에 걸린 시간 |
| `terminal_reason` | 실행이 끝난 이유 (`completed` / `max_turns`) |
| `changed_files`, `tool_calls` | 바꾼 파일 수, 도구 호출 횟수 |
| `first_turn_cache_read_tokens` | 첫 턴이 캐시에서 읽은 양. 실행 간 오염을 보는 지표 |
| `washout_gap_seconds` | 직전 실행이 끝나고 이 실행이 시작되기까지의 초. 배치 첫 실행은 빈칸 |
| `aux_model_tokens` | 보조 모델(Haiku)에 청구된 토큰 |

## `targets` — 무엇을 다룬 턴인가

턴이 얼마를 썼는지만으로는 왜 썼는지 알 수 없습니다. `targets`는 그 턴의 도구 호출이
무엇을 대상으로 했는지 담습니다.

| 도구 | 담기는 값 |
|---|---|
| `Read`, `Write`, `Edit`, `NotebookEdit` | worktree 기준 상대 경로 (`gpu_platform/store.py`) |
| `Bash` | 실행한 프로그램 이름만 (`pytest`, `find`) |
| 그 밖 | 비워 둡니다 |

**절대 경로는 담지 않습니다.** 실행은 매번 임시 worktree에서 일어나고 그 절대 경로에는
실행한 사람의 홈 디렉터리가 들어 있습니다. `Bash`는 명령줄 전체가 worktree 밖 경로를
담을 수 있어 프로그램 이름만 남깁니다. `tests/test_activity_targets.py`가 이 규칙을
지킵니다.

이 열 덕분에 페이지가 "턴 2에서 61,509 토큰을 썼다"가 아니라 "턴 2는
`gpu_platform/models.py` 외 4개를 읽어 들인 턴이고, 그 내용이 남은 29턴에 다시 실렸다"고
쓸 수 있습니다.

## 주 모델만 분해합니다

턴 분해가 담는 것은 과제를 수행한 **주 모델(Sonnet 5)** 의 턴뿐입니다. Claude Code는 그
밖에도 보조 모델(Haiku 4.5)을 잠깐씩 쓰는데, 이 호출은 대화의 턴으로 나타나지 않아
분해 대상이 아닙니다.

실측하면 실행당 약 1,900 토큰, 전체의 **0.04~0.09%** 수준입니다. 그래서 두 숫자가
갈립니다. 이 몫은 `run-summary.csv`의 `aux_model_tokens`에 실행별로 적혀 있으므로,
차이를 설명으로만 두지 않고 숫자로 확인할 수 있습니다.

| 출처 | 재는 것 |
|---|---|
| `data/activity-log.csv`의 턴 합계 | 주 모델의 턴만 |
| `docs/GENERATED_RESULTS.md`의 처리 토큰 | provider가 보고한 모든 모델의 합 |

둘 다 맞지만 대상이 다릅니다. 조건 간 비교에서는 이 몫이 모든 조건에 비슷하게 실려
소수점 첫째 자리에서만 차이가 납니다.

## 원본 아티팩트

`benchmark/runs/<회차>/<실행>/attempt-NN/`에 transcript와 diff, 채점 결과가 남습니다.
용량이 크고 개인정보와 로컬 경로가 섞여 있을 수 있어 저장소에는 커밋하지 않습니다.
공개하는 것은 위 세 CSV뿐이고, 페이지의 모든 수치는 이 셋으로 되짚을 수 있습니다.

**원본은 백업하지 않습니다.** 회차마다 8MB 넘게 쌓이는 데다 그대로는 읽기도 어렵고,
절대 경로와 대화 전문이 들어 있어 공개할 수도 없습니다. 대신 토큰과 결과에 관한 값은
남김없이 위 CSV로 옮겨 두었습니다 — 턴별 추론 토큰과 cache TTL 구분, 실행별 모델·소요
시간·washout 간격·보조 모델 사용량까지.

그 대가는 분명합니다. **나중에 새 열이 필요해지면 과거 회차는 채울 수 없습니다.** 열을
추가해도 이미 발행된 행이 사라지지는 않고 빈 값으로 남지만, 그 값을 뽑을 원본이 없습니다.
새 회차부터 채워집니다.
