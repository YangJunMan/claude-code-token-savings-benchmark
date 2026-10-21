# 측정 종료 보고서 — 2026-10-21

모델 업데이트 속도와 구독 토큰 부족으로 추가 측정을 종료한다. 기존 측정값과 실행 진단은 보존한다. 이 결정은 특정 절약법의 효과가 입증됐다는 뜻이 아니다.

## 보존 범위

페이지에 보존하는 전체 실험은 **151건**이다. 현행 구독 파이프라인 131건과 Git 이력에서 복원한 과거 파이프라인 20건을 합한 기록 수이며, 평가 결과를 하나의 평균으로 합친 숫자가 아니다.

### 현행 파이프라인

측정 원본의 기준은 [`data` 커밋 `9a0fbc6`](https://github.com/YangJunMan/claude-code-token-savings-benchmark/tree/9a0fbc67da8efb25192976189971ce060e937aa7/data)이다. 기록된 실행 날짜는 2026-09-16~2026-10-18이다.

| 파일 | 보존한 내용 |
|---|---|
| `token-bench-results.csv` | 실행 결과 131행: succeeded 130, timeout 1 |
| `run-summary.csv` | 실행 요약 131행: measurable 129, 제외 2 |
| `activity-log.csv` | 턴별 기록 5,666행 |
| `comparison.csv` | 모델·프리셋별 BASE와 비교한 집계 82행 |
| `run-diagnostics.json` | 실행별 진단 44건 |

로컬 결과 24건·진단 14건·턴별 기록은 모두 원격 데이터에 포함돼 있었다. 별도 고유 행을 추가할 필요가 없어 로컬 `data/`를 위 커밋의 5개 파일과 일치시켰다. 과거 로컬 `comparison.csv`는 기존 7행의 값이 달랐으므로 이어 붙이지 않았다. 최신 `run-summary.csv`로 비교표를 재생성해 원격의 82행과 일치함을 확인했다.

갱신 전·후 데이터와 SHA-256 manifest, 로컬 `state.db` 사본은 `.token-bench/archives/20261021-171552/`에 보관했다. 이 경로와 `data/`는 Git 추적 제외 대상이다. 공개 데이터의 재현 기준은 위 원격 커밋이다. 로컬 DB에는 `running` 1건이 있으나 이것만으로 실제 프로세스 실행을 뜻하지는 않는다. DB 상태는 수정하지 않았다. 보존 데이터만으로 전체 실행의 원본 transcript나 작업 디렉터리를 복구할 수 있다고 주장하지 않는다.

### 과거 파이프라인 복원

[`6ddb64b`의 원본](https://github.com/YangJunMan/claude-code-token-savings-benchmark/tree/6ddb64bca356bedb07d5b2013fa5fc896e816631/data)에서 4개 CSV를 바이트 그대로 복원해 [`benchmark/history/legacy-2026-09-13/`](../benchmark/history/legacy-2026-09-13/README.md)에 보관했다. 파일별 SHA-256과 출처 revision은 해당 `manifest.json`에 있다.

실행 요약 20건·턴 673행·비교표 12행을 복원했다. 2026-09-05 pilot, 09-06, 09-08, 09-13 회차를 포함한다. 추가 `published-measurements.csv` 7행은 이 중 09-06 회차의 원본이므로 실행 수에 중복으로 더하지 않는다. 과거 `run_id`는 날짜마다 재사용됐으므로 `(run_date, run_id)`로 구분한다.

Pages artifact에서만 회차별 `legacy:<run_date>` 프롬프트 그룹과 `pipeline=legacy`를 추가한다. 현행은 `pipeline=subscription`으로 표시하며, 과거 점수와 현행 공개 테스트 통과율을 섞지 않는다. 통합 턴 기록은 6,339행, 진단은 기존 현행 44건이다. 원본은 artifact의 `data/subscription/`·`data/legacy/`에도 별도로 남긴다.

## 현행 파이프라인 관측 결과

모델은 전부 `claude-sonnet-5`로 기록됐다. Claude Code 버전은 `2.1.267` 24건, `2.1.283` 107건이다. 아래는 프리셋·조건별 **실행당 단순 평균**이며, `measurable=1`이고 공개 테스트 평가값이 있는 행만 사용했다. 비용은 구독 추가 청구액이 아닌 API 환산 추정치다. 날짜별 BASE 대비 값을 평균하는 웹 비교표와 집계 방식이 다르다.

| 프리셋 | 조건 | 전체 실행 | 평균에 포함 | 평균 비용 (USD) | 평균 처리 토큰 |
|---|---|---:|---:|---:|---:|
| small | BASE | 26 | 26 | 1.9130 | 3,911,800 |
| small | BE_BRIEF | 25 | 25 | 1.5638 | 3,055,297 |
| small | CAVEMAN-FULL | 25 | 25 | 1.5714 | 3,178,759 |
| small | HEADROOM | 25 | 24 | 1.8692 | 3,861,699 |
| small | RTK | 26 | 25 | 1.9964 | 4,334,640 |
| large | BASE | 1 | 1 | 2.7732 | 5,718,754 |
| large | BE_BRIEF | 1 | 1 | 1.8428 | 3,723,676 |
| large | CAVEMAN-FULL | 1 | 1 | 2.5621 | 5,749,787 |
| large | HEADROOM | 1 | 1 | 2.8232 | 6,050,345 |
| large | RTK | 0 | 0 | — | — |

이 표에서 small의 BE_BRIEF·CAVEMAN-FULL 평균은 BASE보다 낮았다. 그러나 CLI 버전·실행 시점이 섞여 있고 무작위 배정이나 통계적 유의성 검증을 수행하지 않았으므로 절약법 자체의 인과 효과나 일반적인 우열로 해석하지 않는다. large는 조건별 1회 이하라 효과 판단에 사용하지 않는다.

성공 130건은 모두 공개 테스트 통과로 기록됐다. 이 중 HEADROOM 1건은 `measurable=0`이라 평균에서 제외했다. RTK timeout 1건도 제외했다. timeout 실행의 공개 테스트가 통과했더라도 실행 완료를 뜻하지 않는다. 공개 테스트 통과는 숨은 요구사항이나 운영 품질 검증을 대신하지 않는다.

`run-diagnostics.json`은 실행 중 감지한 사건과 요약을 담는다. 별도 agent가 효과를 확정한 결론으로 취급하지 않는다. 과거 held-out 평가를 사용한 [2026-09-06 보고서](FULL_REPORT.md)는 평가 체계가 달라 이 표의 평균에 합산하지 않았다.

## 자동 실행과 코드 리뷰

GitHub의 `bench`와 `self-heal`을 `disabled_manually`로 전환했다. `ci`와 `pages`는 유지한다. 이는 저장소의 workflow 설정 상태이며, YAML의 schedule 자체를 삭제한 것은 아니다. 재활성화하면 자동 측정·수정이 다시 시작될 수 있다.

모델 축 구현은 PR #32로 이미 `main`에 병합됐다. 별도로 남아 있던 미커밋 runner 분리 작업은 유지했다.

- 실제 snapshot 검증에서는 누락되거나 UTF-8이 손상된 `prompt.md`를 `WorkspaceError`로 변환한다. runner는 이를 `config-error`로 종결하고 orphan 재등록을 막는다.
- 앞선 리뷰의 “prompt 누락 시 running 잔존”은 snapshot 검증을 대체한 재현에서 나온 오판이었다. 실제 준비·검증·DB 경로를 사용하는 회귀 테스트로 정정했다. 이를 이유로 운영 코드를 추가 변경하지 않았다.
- 새 테스트는 prompt 누락·UTF-8 손상 시 terminal 상태와 orphan 재등록 방지를 확인한다. 모델 호출은 하지 않는다.

최종 검증은 Python 3.11 전체 테스트 `292 passed, 1 skipped`, `git diff --check` 통과다. 보존한 5개 파일의 전후 checksum, 로컬 파일과 고정 원격 커밋의 바이트 일치, 비교표 82행 재생성 일치, 문서의 로컬 링크를 확인했다. 실제 모델 호출과 추가 측정은 수행하지 않았다. 검증은 로컬 변경본 기준이며 원격 CI·배포 결과가 아니다.

## 아키텍처와 전체 기록 표시

아키텍처 리뷰의 네 항목은 공통 transcript 해석, 실행 계획 생성, ledger 게시, queue 실행 모듈로 반영했다. 인터페이스·복구 범위는 [CI/CD 문서](CI-CD.md#아키텍처-리뷰-반영--2026-10-21)에 기록했다.

개요 페이지에 성공·timeout·평균 제외 실행을 모두 표시하는 실험 기록 표와 기존 진단을 추가했다. 턴 로그가 없는 실행도 요약에 있으면 목록에 남긴다. 모델·프롬프트를 선택해 같은 조합끼리 비교할 수 있으며, 여러 조합의 delta와 noise floor를 하나로 합치지 않는다. 기존 진단은 재호출하지 않는다.

작업 전 공개 Pages에는 24건만 배포돼 있었고 마지막 Pages 실행은 2026-09-28이었다. `data`는 workflow가 없는 orphan 브랜치이며 봇 push도 다른 workflow를 시작하지 않아 측정 증가분이 배포로 이어지지 않았다. Pages에 main의 `bench` 성공 완료를 받는 `workflow_run`과 명시적 main/data checkout, artifact 참조 무결성 검증을 추가했다. 원격 배포 검증은 push 후 별도로 수행해야 한다.

## 재현

고정된 원본은 다음과 같이 추출할 수 있다. GitHub 저장소 접근이 필요하다.

```bash
git fetch origin data
git show 9a0fbc67da8efb25192976189971ce060e937aa7:data/run-summary.csv > /tmp/token-bench-final-summary.csv
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests/ -q
```

평균 재계산은 `run-summary.csv`에서 `(model, prompt_id, condition)`으로 나누고 `measurable == "1"` 및 `quality_score != ""`인 행의 `cost_usd`, `processed_tokens`를 산술 평균한다. 비교표는 `token_bench.collect._rebuild_comparison(summary_path, comparison_path)`으로 임시 파일에 재생성할 수 있다. `collect` 전체 실행은 진단 경로를 포함하므로 단순한 비교표 검증에 사용하지 않았다.
