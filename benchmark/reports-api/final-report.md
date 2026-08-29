# Token Optimizer Benchmark Results

이 보고서의 비용은 provider가 반환한 API-equivalent estimated cost이며 Claude Pro 구독료에 추가 청구된 금액이 아니다.
별도 API 연결성 probe 비용(조건 합계에 미포함): $0.099588 · probe 포함 실측 합계: $11.941479

Valid conditions: 7/7 · Invalid attempts: 0 · Total API-equivalent cost: $11.841891

## Condition measurements

| Condition | Input | Cache create | Cache read | Output | Total | Cost USD | Quality | Breakdown | Critical | Clear | Turns | Tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H-ON | 3,881 | 45,113 | 369,886 | 19,977 | 438,857 | $0.589416 | 10/100 | H0 P10 C0 D0 E0 | FAIL | PASS | 12 | 25 |
| H-OFF | 3,881 | 53,131 | 395,923 | 27,654 | 480,589 | $0.742439 | 70/100 | H50 P10 C10 D0 E0 | FAIL | PASS | 12 | 24 |
| C-FULL | 566,629 | 0 | 0 | 18,771 | 585,400 | $1.979392 | 70/100 | H50 P10 C10 D0 E0 | FAIL | PASS | 12 | 23 |
| C-NON | 602,948 | 0 | 0 | 31,288 | 634,236 | $2.276132 | 20/100 | H0 P10 C10 D0 E0 | FAIL | PASS | 12 | 23 |
| C-BRIEF | 592,992 | 0 | 0 | 26,691 | 619,683 | $2.177243 | 10/100 | H0 P10 C0 D0 E0 | FAIL | PASS | 12 | 24 |
| R-ON | 531,737 | 0 | 0 | 17,872 | 549,609 | $1.861259 | 50/100 | H30 P10 C10 D0 E0 | FAIL | RECOVERED | 12 | 24 |
| R-OFF | 611,644 | 0 | 0 | 25,540 | 637,184 | $2.216010 | 70/100 | H50 P10 C10 D0 E0 | FAIL | PASS | 12 | 24 |

## Paired comparisons

| Comparison | Token saving | Cost saving | Quality delta | Quality gate | Recommendation |
|---|---|---|---|---|---|
| Headroom ON vs OFF | +8.68% | +20.61% | -60 | FAIL | NO |
| Caveman full vs non | +7.70% | +13.04% | +50 | FAIL | NO |
| Caveman brief vs non | +2.29% | +4.34% | -10 | FAIL | NO |
| RTK ON vs OFF | +13.74% | +16.01% | -20 | FAIL | NO |

## Cache isolation and scheduling

| Condition | Gap from previous | Washout | First-turn cache read | Cache gate |
|---|---|---|---|---|
| H-ON | parallel | not required | 0 | PASS |
| H-OFF | parallel | not required | 0 | PASS |
| C-FULL | parallel | not required | 0 | PASS |
| C-NON | parallel | not required | 0 | PASS |
| C-BRIEF | parallel | not required | 0 | PASS |
| R-ON | parallel | not required | 0 | PASS |
| R-OFF | parallel | not required | 0 | PASS |

## Interpretation limits

- 각 조건은 유효 관측치 1회이므로 통계적 유의성을 주장할 수 없다.
- 이 API cohort는 $15 credit 한도 내에서 조건당 max_turns=12로 고정했다. 이전 Pro H-ON 탐색 실행(max_turns=28)과 직접 합산하지 않는다.
- Headroom 조건에서도 provider cache_creation/cache_read가 관측됐다. 따라서 Headroom 비교는 순수 no-cache 압축률이 아니라 proxy의 실제 end-to-end 관측이며, Direct/Caveman/RTK와 동일한 cache 상태가 아니다.
- 모든 조건의 첫 turn cache read는 0이었지만, nonce가 전체 provider cache 계층의 모든 prefix를 무효화한다고 해석하지 않는다.
- API 병렬 실행으로 같은 시각의 service load·rate limit 경쟁이 조건 효과에 섞일 수 있다.
- Claude의 비결정성과 12-turn 상한은 구현 범위와 최종 응답 완성도에 영향을 줄 수 있다.
- 양의 token/cost 절감과 quality gate 통과가 동시에 확인된 비교에만 Recommendation=YES를 부여한다.
