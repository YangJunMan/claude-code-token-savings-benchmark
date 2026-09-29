# CI/CD

이 저장소는 실험을 무인으로 돌리되 **코드 변경은 사람이 병합한다.** 자동화가
쓰기 권한을 갖는 범위와, 그 범위를 무엇이 강제하는지 적는다.

## 쓰기 권한의 3가지 등급

| 등급 | 주체 | 대상 | 경로 |
| --- | --- | --- | --- |
| 데이터 | `bench.yml` | `data/**`만 | **`data` 브랜치**에 push |
| 코드 | `self-heal.yml` | `ALLOWED_PATHS`만 | PR만, 병합은 사람 |
| 배포 | `pages.yml` | 없음(읽기) | main·data push에 반응 |

**main에는 사람이 병합한 커밋만 있다.** 측정 결과는 `data` orphan 브랜치가
소유한다 — 하루 16개의 봇 커밋이 main에 섞이면 사람이 한 작업이 히스토리에서
보이지 않는다(사용자 결정). `data/`는 main의 `.gitignore`에 있다.

코드가 자동 병합되지 않는 이유는 기술적 제약이 아니다. 잘못된 변경이 병합되면
실험이 멈추고 그 책임은 사람이 지기 때문이다(사용자 결정).

## 워크플로

### `ci.yml` — 게이트
- `push`는 main에만, 그리고 모든 `pull_request`.
- ubuntu·macos·windows 3종에서 `pytest tests/`, `node --check`, quickstart 스크립트
  구문 검사.
- 비밀·로컬 절대경로 유출 검사. API key·OAuth 토큰·Admin key의 접두사, 환경변수에
  값을 직접 대입한 형태, 개발자 홈 디렉터리 절대경로를 찾는다. 정확한 정규식은
  `ci.yml`의 `Guard against leaked secrets and local paths` 단계에 있다 — 이 문서에
  패턴을 그대로 옮기면 그 검사가 이 문서에 걸린다.
- `no-bot-push-to-main` job: `github-actions[bot]`이 main에 직접 push하면 무조건
  실패시킨다. 데이터는 `data` 브랜치로, 코드는 PR로 가므로 이 경로는 존재해서는
  안 된다.

### `bench.yml` — 무인 실험

**한 tick에 실험 하나(조건 1개)만 돌린다.** 간격은 세트가 아니라 실험 단위다
(사용자 결정). 조건 5개를 한 번에 돌리면 조건들이 몇 분 간격으로 연달아 실행돼
간격의 의미가 사라진다. 매 tick마다 표본이 가장 적은 조건을 골라 균등하게 쌓는다.

| 단계 | 프리셋 | 실험 간격 | 실험/일 | 조건당/일 | 전환 조건 |
| --- | --- | --- | --- | --- | --- |
| 1 | `small` | 90분 | 16 | 3.2 | 모든 조건이 `small`에서 성공 30건 |
| 2 | `large` | 3시간 | 8 | 1.6 | 마지막 단계 — 계속 유지 |

조건당 30건까지 `small`은 약 9.4일, `large`는 약 19일이 걸린다(실패 없을 때).

- cron은 조건 분기를 못 한다. 두 스케줄을 항상 등록해 두고
  (`0 0,3,6,9,12,15,18,21 * * *`, `30 1,4,7,10,13,16,19,22 * * *` → 00:00, 01:30,
  03:00 ... 22:30 = 90분 간격), `large` 단계에서는 `:30` tick을 런타임에 건너뛴다.
  `:00` cron만 남으면 그것이 정확히 3시간 주기다. 90분도 cron 한 줄로는 표현할 수
  없다 — 5필드 cron에 "매 90분"이 없고 90분은 1시간의 정수배도 아니다.
- 판정은 `plan` job이 한다: `python3 -m token_bench next-target`이 `run-summary.csv`에서
  프리셋별·조건별 `succeeded` 건수를 세어 `{"preset": ..., "condition_id": ...}`를
  출력한다. `run` job은 `needs.plan.outputs.run == 'true'`일 때만 돌고,
  `estimate --only "$CONDITION" --preset "$PRESET"`으로 그 실험 하나만 만든다.
  도구 설치 **전에** 건너뛸지 결정하므로 runner 시간을 낭비하지 않는다.
- 조건 선택은 해당 프리셋에서 `succeeded`가 가장 적은 조건이다. 동수면
  `conditions.json` 선언 순서. `next-target`은 하나가 아니라 **순서 전체**를 주고,
  `run` job이 `preflight`로 앞에서부터 실제로 돌 수 있는 첫 조건을 고른다.
  도구가 사라진 조건은 영구히 표본이 가장 적은 상태로 남아 매번 다시 뽑히고, 그러면
  나머지 조건의 수집이 통째로 멈춘다(2026-09-29 `headroom` 실측: 4회 연속 실패,
  그 사이 다른 조건은 한 번도 돌지 못했다). 건너뛴 조건은 `Report diagnosis drift`가
  issue로 알린다.
- 전환은 **모든 조건**이 임계를 넘어야 일어난다. 하나라도 모자라면 넘어가지 않는다 —
  조건 간 비교가 목적이므로 표본이 고르지 않은 채로 과제를 바꾸면 그 프리셋의 비교가
  미완성으로 남는다. 임계는 `collect.RUNS_PER_PRESET`, 순서는 `PRESET_SEQUENCE`.
- `workflow_dispatch`로 수동 실행 가능(이때는 `:30` 건너뛰기가 적용되지 않는다).
- `concurrency: group: bench, cancel-in-progress: false` — 앞 회차가 돌고 있으면
  대기하고, 그 사이 또 cron이 뜨면 대기 중인 쪽이 취소된다. 결과적으로 "바쁘면
  그 시간은 건너뜀"이다.
- 도구 버전을 env에 고정한다: `CLAUDE_CODE_VERSION`, `RTK_VERSION`,
  `HEADROOM_VERSION`, `CAVEMAN_SHA`. 자동 업그레이드는 없다. 조건이 요구하는
  도구를 하나라도 빠뜨리면 그 조건은 runner에서 계속 실패한다.
- **`ISOLATION: project-settings`를 고정한다.** 지정하지 않으면 격리 모드가 배치
  내용에서 유도되어, 조건 하나씩 돌리는 구조에서는 `base`가 `safe-mode`,
  `rtk`·`caveman-full`이 `project-settings`로 갈린다 — 처치 말고도 달라지는 것이
  생겨 조건 비교가 무너진다. 과거 데이터도 5조건 한 배치라 `project-settings`였다.
- `workflow_dispatch`의 `mode` 입력: `preflight`를 고르면 `estimate`까지만 하고
  멈춘다. 모델을 호출하지 않으므로 구독 한도를 쓰지 않고 secret·인증·도구 설치·
  데이터 복원·조건 선택을 모두 확인할 수 있다. 게시·커밋·진단 단계는 건너뛴다.
- 단계 분리가 중요하다. 측정 실행 단계에는 `ANTHROPIC_API_KEY`를 주지 않는다 —
  그 이름이 환경에 있으면 `claude`가 API key 경로로 붙고 `preflight.py`가 구독
  실행을 거부한다. 진단은 `Publish and diagnose` 단계에서만 키를 본다.
- `Restore data from the data branch`가 **실행 전에** 기존 CSV를 작업 트리에
  복원한다. `comparison.csv`는 전체 `run-summary.csv`에서 매번 다시 계산되고 진단
  manifest도 기존 파일에 항목을 더하므로, 빈 트리로 돌리면 그 두 파일이 이번
  회차만 담은 내용으로 덮여 과거 이력을 잃는다.
- `Commit results to the data branch`는 `if: always()` — 진단이 실패해도 측정
  결과는 커밋한다. 새 CSV를 tmp로 옮기고 트리를 정리한 뒤 `data`로 갈아타 다시
  넣는다(스테이징된 변경을 들고 브랜치를 바꾸면 충돌한다). `data` 브랜치가 없으면
  `--orphan`으로 만든다.

### 비교 기준선

한 tick에 조건 하나만 돌리므로 batch에도, 같은 날짜에도 BASE가 없는 경우가 흔하다
(BASE는 5 tick마다 = 약 7.5시간마다). 그래서 `comparison.csv`의 기준선은 batch나
날짜가 아니라 시간축에서 끌어온다: 처치 실행의 날짜까지 쌓인 BASE 중 최근
`collect.BASELINE_WINDOW`(10)건의 평균. `prompt_id`로는 계속 나눈다 — 프롬프트
크기가 다르면 토큰 수 자체가 달라 비교할 수 없다.

대가: 기준선이 한 batch가 아니라 여러 날의 BASE 평균이므로 BASE의 일간 변동이
delta에 직접 반영된다. `noise_processed_pct`·`noise_cost_pct`가 그 변동폭이다.

### `self-heal.yml` — 수정안 PR
- `workflow_run`으로 `bench` 실패에 반응. `workflow_dispatch`로 수동 실행 가능.
- 실패 로그(`gh run view --log-failed`)를 컨텍스트로 주고, 프롬프트는
  `.github/self-heal-prompt.md`에 있다.
- 에이전트는 `Read,Edit,Grep,Glob`만 받는다. 셸이 없으므로 이 단계에서 임의
  명령이 돌지 않는다.
- 실행 후 `git diff --name-only`가 `ALLOWED_PATHS`
  (`token_bench/diagnostics.py`, `.github/workflows/bench.yml`) 밖을 포함하면
  **전체를 되돌리고 실패**시킨다. 프롬프트의 지시가 아니라 이 검사가 범위를
  강제한다. `tests/`는 목록에 없다 — 에이전트가 테스트를 고쳐 통과시키는 것을
  막는다.
- `pytest tests/` 통과 후에만 PR을 연다. 열린 self-heal PR이 이미 있으면 새로
  만들지 않는다.
- 측정 로직(조건 정의, 격리 모드, `PUBLISHABLE_STATUSES`, turn 추출)은 자동 수정
  대상이 아니다. 바뀌면 과거 데이터와 비교할 수 없다.

### `pages.yml` — 배포
- 트리거는 `branches: [main, data]` + `paths: ["web/**", "data/**"]`. paths 필터를
  브랜치별로 나눠 쓸 수 없어 두 경로를 함께 적었다 — main에 `data/**`가 없고 data
  브랜치에 `web/**`가 없으므로 실제로 걸리는 것은 "main의 web 변경" 또는 "data
  브랜치의 결과 추가"뿐이다.
- `web/`은 main, 데이터는 `data` 브랜치를 `path: _data`로 따로 체크아웃해 합친다.

## 브랜치 보호 설정

main에 pull request 필수 + `ci.yml` 상태 검사 필수. 예외는 두지 않는다 — 봇이
main에 쓸 이유가 없다. `data` 브랜치에는 보호를 걸지 않는다(봇이 직접 push한다).

## 로컬에서 데이터 보기

`data/`는 main에 없다. `quickstart.sh`가 웹 서버를 띄우기 전에
`git fetch --depth=1 origin data` 후 `git archive FETCH_HEAD data | tar -x`로 풀어
둔다. 네트워크가 없거나 브랜치가 없으면 지금 있는 파일로 계속한다 — 실험 실행
자체는 이 데이터가 필요 없다.

## 1회 마이그레이션

`data/`를 main에서 떼고 `data` 브랜치로 옮긴다. 아직 수행하지 않았다.

```sh
# 1. 현재 데이터를 data orphan 브랜치로 옮긴다
git switch --orphan data
git add -f data/
git commit -m "data: 측정 결과를 data 브랜치로 분리"
git push -u origin data

# 2. main에서는 추적을 끊는다(.gitignore는 이미 반영돼 있다)
git switch main
git rm -r --cached data/
git commit -m "chore: 측정 결과를 data 브랜치로 옮긴다"
```

`git rm --cached`는 작업 트리의 파일을 지우지 않는다 — 로컬 데이터는 그대로
남는다.

## 필요한 secret

| 이름 | 쓰는 곳 | 비고 |
| --- | --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | `bench.yml` 측정 실행 | `claude setup-token`으로 발급. 구독 인증이며 `preflight`가 API key 경로를 거부하므로 필수 |
| `ANTHROPIC_API_KEY` | `bench.yml` 진단, `self-heal.yml` | 구독과 별개 청구. 유지보수가 실험용 구독 한도를 먹지 않게 한다 |

두 값 모두 GitHub Settings > Secrets에 직접 입력한다. 로컬 셸에 붙여넣으면 세션
기록에 남는다.

## 아직 검증되지 않은 것

CI에서 한 번도 돌지 않은 경로다. 첫 실행 때 확인해야 한다.

- 진단의 실제 LLM 호출(프롬프트가 파싱 가능한 JSON을 내는지).
- `bench.yml`의 `Report diagnosis drift`가 여는 issue — `gh issue list --search`의
  한글 title 매칭과 중복 방지.
- `self-heal.yml` 전체 — `--allowed-tools`만으로 비대화형 편집이 되는지,
  범위 검사가 의도대로 되돌리는지.
