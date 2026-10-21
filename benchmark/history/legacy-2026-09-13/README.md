# 과거 파이프라인 측정 원본

파이프라인 교체 전 마지막 snapshot `6ddb64bca356bedb07d5b2013fa5fc896e816631`의 `data/`에서 4개 CSV를 바이트 그대로 복원했다. `manifest.json`은 파일별 SHA-256과 출처 revision을 기록한다.

실행 요약 20건에는 pilot-2026-09-05, 2026-09-06, 2026-09-08, 2026-09-13 회차가 들어 있다. `published-measurements.csv` 7행은 요약에 포함된 2026-09-06 회차의 추가 원본이며 별도 실행으로 중복 집계하지 않는다.

과거 점수와 현행 공개 테스트 통과율은 다른 평가 방식이다. Pages artifact를 만들 때만 회차마다 `legacy:<run_date>` 프롬프트 그룹과 `pipeline=legacy`를 붙여 표시하며, 현행 측정과 비교 평균을 합치지 않는다. 원본 CSV에 없던 측정값은 생성하지 않는다. 동일한 run_id가 여러 날짜에 재사용되므로 실행 키는 `(run_date, run_id)`다.
