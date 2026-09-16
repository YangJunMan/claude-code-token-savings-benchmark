---
name: token-bench
description: 이 저장소(claude-code-token-savings-benchmark)를 clone한 사람이 토큰 절약 실험을 돌리거나 결과를 보고 싶을 때 사용한다. "토큰 실험 켜줘", "웹 띄워줘", "실험 실행해줘", "결과 확인해줘"처럼 이 프로젝트를 조작해 달라는 요청에 반응한다.
---

# token-bench 운영 스킬

이 스킬은 **실험을 조종하는 쪽**이다. 여기서 다루는 조작(웹 띄우기, 조건
고르기, 실행 계획 승인)은 측정 대상이 아니다 — 실제로 토큰을 재는 것은
`token_bench work`가 실행하는 별도의 Claude Code 프로세스이며, 그 프로세스는
`--safe-mode` 또는 `--setting-sources project`로 이 스킬을 포함한 개인 설정을
배제한 채 돈다. 이 문서 자체는 조건 처치가 아니다.

## 우선 확인

```bash
python3.11 --version   # 없으면 사용자에게 설치를 안내하고 멈춘다(brew install python@3.11)
```

## 1. "웹 보여줘" / "실험 켜줘" — 결과를 보고 싶을 때

macOS·Linux·WSL이면 `./quickstart.sh`를, 지금 셸이 Windows PowerShell이면
`.\quickstart.ps1`을 실행한다(둘 중 어느 쪽인지는 `$PSVersionTable` 존재
여부나 사용자에게 직접 물어 판단한다).

```bash
./quickstart.sh
```

표준 라이브러리만 쓰므로 `pip install` 없이 돈다. 두 스크립트 모두:
1. `preflight --skip-unavailable`로 이 컴퓨터에서 지금 돌릴 수 있는 조건을 보여준다
2. 로컬 실험 API(`token_bench serve`, 127.0.0.1:8787)와 정적 웹 서버(127.0.0.1:8765)를 백그라운드로 띄운다
3. 브라우저에서 실험 설정 탭을 자동으로 연다

foreground로 계속 실행되며 Ctrl+C로 멈춘다(백그라운드 셸로 실행하고, 로그는
`/tmp/token-bench-*.log`를 tail해서 확인해도 된다).

## 2. "실험 실행해줘" — 조건을 골라 구독 사용량을 쓰는 실행을 만들 때

**이 단계부터는 사용자의 Claude 구독 사용량을 소비한다. 다음 순서를 반드시
지키고, 등록(enqueue) 직전에 사용자에게 확인받는다.**

```bash
python3.11 -m token_bench preflight --skip-unavailable
```
어떤 조건이 지금 돌아가는지 사용자에게 보여준다. `base`·`be-brief`는 항상
설치 없이 된다. `headroom`처럼 도구가 없는 조건은 이유와 공식 GitHub
repository 링크가 함께 나온다 — 사용자가 원하면 링크를 안내하고, 원하지
않으면 그 조건은 빼고 진행한다.

```bash
python3.11 -m token_bench estimate --only <골라둔 조건, 콤마 구분> --skip-unavailable --timeout-seconds 3600
```
출력된 `plan.json` 경로와 `digest`, `run_count`, `isolation`, 그리고
`cost_disclaimer`(구독 사용량 소비 안내)를 사용자에게 그대로 보여준다.

**여기서 반드시 사용자 확인을 받는다** — "이 계획대로 등록할까요?"라고 묻고
명시적 동의 없이는 진행하지 않는다.

```bash
python3.11 -m token_bench approve --plan <plan.json 경로> --confirm <digest>
python3.11 -m token_bench enqueue --plan <plan.json 경로> --approval <approval.json 경로>
python3.11 -m token_bench work --exit-when-empty
```

`work`가 끝나면:

```bash
python3.11 -m token_bench status
python3.11 -m token_bench publish
```

## 3. 실패를 해석하는 법

실행이 끝난 뒤 `status`가 `succeeded`가 아니면, `.token-bench/runs/<batch_id>/<condition>__r<repeat>/logs/stderr.log`와
`stdout.jsonl`의 마지막 `type: result` 이벤트를 읽고 다음 표로 사용자에게
설명한다. 짐작하지 말고 로그 문구를 확인한다.

| 로그에서 보이는 것 | 뜻 | 사용자에게 할 말 |
|---|---|---|
| `result` 이벤트의 `is_error: true`, `result`에 "session limit"/"limit" 문구 | 구독 세션 한도에 걸려 중간에 끊김 | 측정값이 아니다(`blocked`로 자동 분류됨). 한도가 풀리는 시각까지 기다렸다가 다시 `estimate`부터 반복하라고 안내 |
| `stderr.log`에 "Settings file not found" | 설정 파일 경로 문제 | 이미 수정된 버그다. 저장소가 최신인지 확인(`git pull`) |
| `stderr.log`에 "claude 프로세스를 실행할 수 없다" | `claude` CLI가 PATH에 없음 | Claude Code 설치와 로그인(`claude auth status`) 확인 |
| stdout이 비어 있음 | 프로세스가 이벤트 하나 남기지 못하고 죽음 | `blocked`로 자동 분류됨. `claude --version`으로 CLI 자체가 도는지 먼저 확인 |
| `evaluation.passed: false` | 모델이 과제 테스트를 통과 못함 | 이건 정상적인 측정값이다(품질 결과). 재시도할 필요 없음 |

## 하지 말아야 할 것

- 사용자 동의 없이 `enqueue`나 `work`를 실행하지 않는다(구독 사용량 소비).
- 조건 선언(`benchmark/conditions.json`)이나 `token_bench/` 코드를 이 스킬
  실행 중에 고치지 않는다 — 그건 별도의 개발 작업이지 실험 운영이 아니다.
- 실패한 실행을 성공했다고 보고하지 않는다. `status`/`result` 명령의 실제
  출력을 근거로만 말한다.
