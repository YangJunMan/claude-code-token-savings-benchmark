# Token Optimizer Benchmark Results

이 보고서의 비용은 provider가 반환한 API-equivalent estimated cost이며 Claude Pro 구독료에 추가 청구된 금액이 아니다.

Valid conditions: 7/7 · Invalid attempts: 1 · Valid API-equivalent cost: $4.386526 · All attempts: $4.874755
Prompt-cache policy observed: natural

## Condition measurements

| Condition | Input | Cache create | Cache read | Output | Total | Cost USD | Quality | Breakdown | Critical | Clear | Cache policy | Turns | Tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H-ON | 956 | 51,086 | 347,833 | 27,580 | 427,455 | $0.710448 | 60/100 | H40 P10 C10 D0 E0 | FAIL | PASS | natural | 10 | 31 |
| H-OFF | 956 | 44,651 | 266,231 | 20,437 | 332,275 | $0.554712 | 60/100 | H40 P10 C10 D0 E0 | FAIL | PASS | natural | 10 | 22 |
| C-FULL | 970 | 62,897 | 411,760 | 20,498 | 496,125 | $0.667712 | 20/100 | H0 P10 C10 D0 E0 | FAIL | PASS | natural | 10 | 22 |
| C-NON | 956 | 52,463 | 369,059 | 13,556 | 436,034 | $0.511630 | 10/100 | H0 P10 C0 D0 E0 | FAIL | PASS | natural | 10 | 21 |
| C-BRIEF | 984 | 56,078 | 400,362 | 16,663 | 474,087 | $0.581210 | 70/100 | H50 P10 C10 D0 E0 | FAIL | PASS | natural | 10 | 22 |
| R-ON | 956 | 58,180 | 391,741 | 19,227 | 470,104 | $0.624928 | 20/100 | H10 P10 C0 D0 E0 | FAIL | PASS | natural | 10 | 10 |
| R-OFF | 956 | 63,742 | 395,974 | 25,149 | 485,821 | $0.735886 | 60/100 | H40 P10 C10 D0 E0 | FAIL | PASS | natural | 10 | 22 |

## Paired comparisons

| Comparison | Token saving | Cost saving | Quality delta | Quality gate | Recommendation |
|---|---|---|---|---|---|
| Headroom ON vs OFF | -28.64% | -28.08% | +0 | FAIL | NO |
| Caveman full vs non | -13.78% | -30.51% | +10 | FAIL | NO |
| Caveman brief vs non | -8.73% | -13.60% | +60 | FAIL | NO |
| RTK ON vs OFF | +3.24% | +15.08% | -40 | FAIL | NO |

## Cache isolation and scheduling

| Condition | Gap from previous | Washout | First-turn cache read | Cache gate | Later-turn cache write | Later-turn cache read |
|---|---|---|---|---|---|---|
| H-ON | parallel | not required | 0 | PASS | 31299 | 347833 |
| H-OFF | parallel | not required | 0 | PASS | 25130 | 266231 |
| C-FULL | parallel | not required | 0 | PASS | 28291 | 411760 |
| C-NON | parallel | not required | 0 | PASS | 18981 | 369059 |
| C-BRIEF | parallel | not required | 0 | PASS | 22287 | 400362 |
| R-ON | parallel | not required | 0 | PASS | 24618 | 391741 |
| R-OFF | parallel | not required | 0 | PASS | 30257 | 395974 |

## Invalid attempts

- H-ON/attempt-01: max_turns; first-turn cache read=7304

## Interpretation limits

- 각 조건은 유효 관측치 1회이므로 통계적 유의성을 주장할 수 없다.
- 이 API cohort의 유효 관측치는 조건당 max_turns=10로 고정했다. 이전 Pro H-ON 탐색 실행(max_turns=28)과 직접 합산하지 않는다.
- cache_policy=natural cohort에서는 첫 turn isolation과 later-turn cache read를 분리해 기록한다. cache_policy=disabled cohort와 자연-cache 결과를 섞어 해석하지 않는다.
- Headroom proxy가 provider cache marker를 보존하거나 주입하면 환경변수만으로 provider cache 상태를 단정할 수 없으므로, usage의 cache_creation/cache_read를 우선한다.
- 모든 조건의 첫 turn cache read는 0이었지만, nonce가 전체 provider cache 계층의 모든 prefix를 무효화한다고 해석하지 않는다.
- API 병렬 실행으로 같은 시각의 service load·rate limit 경쟁이 조건 효과에 섞일 수 있다.
- Claude의 비결정성과 max_turns=10 상한은 구현 범위와 최종 응답 완성도에 영향을 줄 수 있다.
- 양의 token/cost 절감과 quality gate 통과가 동시에 확인된 비교에만 Recommendation=YES를 부여한다.
