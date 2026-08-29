# Token Optimizer Benchmark Results

이 보고서의 비용은 provider가 반환한 API-equivalent estimated cost이며 Claude Pro 구독료에 추가 청구된 금액이 아니다.

Valid conditions: 1/7 · Invalid attempts: 0 · Total API-equivalent cost: $1.769618

## Condition measurements

| Condition | Input | Cache create | Cache read | Output | Total | Cost USD | Quality | Critical | Turns | Tools |
|---|---|---|---|---|---|---|---|---|---|---|
| H-ON | 58 | 145,166 | 1,188,373 | 36,328 | 1,369,925 | $1.769618 | 70/100 | FAIL | 28 | 48 |

## Paired comparisons

| Comparison | Token saving | Cost saving | Quality delta | Quality gate | Recommendation |
|---|---|---|---|---|---|

## Cache isolation and washout

| Condition | Gap from previous | 70m washout | First-turn cache read | Cache gate |
|---|---|---|---|---|
| H-ON | N/A | N/A | 0 | PASS |

## Interpretation limits

- 각 조건은 유효 관측치 1회이므로 통계적 유의성을 주장할 수 없다.
- 고정 실행 순서 때문에 시간대별 service load와 subscription quota drift가 조건 효과에 섞일 수 있다.
- Claude의 비결정성과 28-turn 상한은 구현 범위와 최종 응답 완성도에 영향을 줄 수 있다.
- 양의 token/cost 절감과 quality gate 통과가 동시에 확인된 비교에만 Recommendation=YES를 부여한다.
