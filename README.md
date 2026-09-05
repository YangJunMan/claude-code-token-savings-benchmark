# Claude Code 토큰 절약 방법을 직접 비교해 봤습니다

> 검증 없이 AI로 작성한 글들이 너무 많아서 불편합니다.
> 신뢰성 있는 정보를 직접 찾아보고 직접 실험 해봅시다.

`Headroom`, `Caveman`, `RTK`, 그리고 단순한 `be brief` 지시가 실제로 토큰과 비용을
줄여 주는지 비교했습니다. 단순 질문·답변이 아니라 **코드 작성이 대부분이고 문서 작성도
포함된 개발 작업**을 Claude Sonnet 5(`medium`)에 맡겼고, 토큰과 비용뿐 아니라 완성된
코드가 같은 테스트를 통과하는지도 함께 평가했습니다.

측정값·실행 코드·채점 기준을 모두 공개합니다. 믿어 달라고 요청하는 대신 **직접 다시
계산하거나 다시 실험할 수 있게** 만들었습니다.

## 목차

- [빠른 시작](#빠른-시작)
- [기능](#기능)
- [실험 결과](#실험-결과)
- [핵심 지표: context tax](#핵심-지표-context-tax)
- [저장소 구조](#저장소-구조)
- [문서](#문서)
- [License](#license)

## 빠른 시작

```bash
git clone https://github.com/YangJunMan/claude-code-token-savings-benchmark.git
cd claude-code-token-savings-benchmark

make setup && make smoke        # 테스트 (API key 불필요)
python3 -m http.server 8765     # → http://127.0.0.1:8765/web/
```

macOS 또는 Linux, Git, Python 3.9 이상이면 됩니다.

## 기능

| | 할 수 있는 일 | API key | 비용 |
|---|---|:---:|:---:|
| 1 | 브라우저에서 턴별 토큰 소모 보기 | 불필요 | 무료 |
| 2 | 공개 측정값으로 결과표 다시 계산 | 불필요 | 무료 |
| 3 | 같은 실험 직접 재실행 | 필요 | 유료 |
| 4 | 새 절약법 추가해 실험 | 필요 | 유료 |

### 1. 브라우저에서 보기

결과표는 "얼마나 줄었나"만 답합니다. **어디서** 줄었는지 보려면:

```bash
python3 -m http.server 8765
# 브라우저에서 http://127.0.0.1:8765/web/
```

턴별 context tax, 컨텍스트 성장, 재청구된 컨텍스트의 출처, 툴별 누적 tax를 보여주고
**진행 과정 재생**으로 턴을 하나씩 따라갈 수 있습니다. 의존성도 빌드 단계도 없습니다.

> `index.html`을 더블클릭해 `file://`로 열면 브라우저가 CSV 읽기를 막습니다.
> 반드시 위 명령으로 서버를 띄우세요.

현재 들어 있는 것은 파이프라인 검증용 **파일럿 실행 1건**입니다(`run_date`가 `pilot-`로
시작). 5개 조건 전체의 턴 로그는 다음 회차에 추가됩니다.
→ [활동 단위 토큰 측정](docs/ACTIVITY-LOG.md)

### 2. 공개 측정값 다시 계산 — 무료

Claude를 호출하지 않으며 `ANTHROPIC_API_KEY`도 필요 없습니다.

```bash
make setup && make smoke        # runner·채점 로직 테스트
make report                     # 공개 CSV → 결과표 재생성
git diff --exit-code docs/GENERATED_RESULTS.md
```

마지막 명령이 아무것도 출력하지 않으면 새로 계산한 표가 공개된 표와 같다는 뜻입니다.
이 과정은 공개 측정값의 계산과 프로그램 동작을 검증하며, 비공개 원본 대화를 복원하지는
않습니다. → [재현 가이드](docs/REPRODUCTION.md)

### 3. 직접 재실험 — 유료

> Anthropic API 비용이 발생합니다. 결과만 확인하려면 위까지만 해도 됩니다.

```bash
make estimate      # 예상 비용 확인 (API 호출 없음)
make setup-paid    # Headroom 설치 — Python 3.10 이상 필요
make preflight     # 조건 선언에 필요한 도구 검사
```

전체 계획 한도는 **$15**, 작업당 상한은 **$2.50**입니다. 실행 명령과 안전장치,
`bypassPermissions` 관련 주의사항은 → [재현 가이드](docs/REPRODUCTION.md)

> `make setup`이 만든 venv가 Python 3.9라면 `make setup-paid`가 실패합니다.
> `rm -rf .venv && python3.11 -m venv .venv` 후 다시 실행하세요.

### 4. 새 절약법 추가

`benchmark/config.json`에 선언 하나를 추가하면 됩니다. **Python 수정은 없습니다.**

```json
{
  "id": "X-ON", "label": "New Skill", "optimizer": "newthing",
  "mechanism": "hook",
  "hook": { "matcher": "Bash", "command": "newthing hook" }
}
```

활성화 방식은 `proxy`(Headroom) · `plugin`(Caveman) · `overlay`(`be brief`) ·
`hook`(RTK) 네 가지입니다. 선언 하나가 처치 적용, 실행 계획, 도구 검사, 결과표 비교
항목까지 전부 도달합니다. → [새 절약법 추가하기](docs/ADDING-A-SKILL.md)

## 실험 결과

| 적용 방법 | 2회 baseline 평균 대비 비용 | 2회 baseline 평균 대비 처리 토큰 | 품질·Critical tests | 이번 실험에서의 해석 |
|---|---:|---:|---:|---|
| Headroom | **26.4% 감소** | **36.7% 감소** | 1차 98점·6/6, 2차 공개 테스트 통과 | 비용은 경계선, 턴당 context 감소는 견고 |
| `be brief` | **20.2% 감소** | **17.1% 감소** | 96점·5/6 | 설치 없이 적용하기 가장 쉬움 |
| RTK | **16.5% 감소** | **30.1% 감소** | 98점·6/6 | prompt 차이와 짧은 실행의 영향이 섞임 |
| Caveman full | **3.6% 증가** | **14.7% 증가** | 100점·6/6 | 이 작업에서는 절약되지 않음 |

모든 조건에 SQLite 기반 GPU 작업 admission service를 구현하도록 요청했고, 총 7회를
측정했습니다(Baseline·Headroom 각 2회, 나머지 각 1회).

**이 결과를 보편적인 성능 수치로 해석하면 안 됩니다.** 동일한 조건의 baseline 두 번도
비용이 **9.78%**, 처리 토큰이 **22.06%** 달랐습니다. Headroom의 실행 간 비용 편차는
25.1%였고, 나머지는 각각 한 번뿐입니다. 이 실험은 "어떤 방법을 더 반복 검증할 가치가
있는가"를 찾는 탐색적 실험에 가깝습니다.

비용은 provider가 보고한 **API-equivalent cost**입니다. 측정에 포함한 실행 비용은 약
**$11.62**, 실패 실행까지 포함한 전체는 약 **$18.33**였습니다.

가장 부담 없이 다시 확인할 만한 후보는 `be brief`였습니다. 어떤 방법이든 baseline을
먼저 반복해 자연 변동을 확인하고, 절감 폭이 그 변동보다 클 때만 효과가 있다고 판단해야
합니다.

→ 실행별 수치·해석·무효 실행·한계는 [전체 실험 보고서](docs/FULL_REPORT.md)

## 핵심 지표: context tax

tool result가 컨텍스트를 키우면 그 비용은 한 번이 아닙니다. 남은 모든 턴이 그것을 다시
읽으므로 **턴 수만큼 반복 청구**됩니다.

```
result      = 컨텍스트 증가분 − 직전 턴 output   (provider 보고값의 뺄셈, 추정 아님)
context tax = result × 이후 남은 턴 수
```

파일럿 실행에서 `Read` 15개를 한 턴에 병렬 호출한 결과 **4,861 토큰이 121,525 토큰으로
청구**됐습니다. 합계만 보는 결과표에는 이 숫자가 보이지 않습니다. Headroom과 RTK가
공격하는 지점이 정확히 여기입니다.

재청구된 컨텍스트를 초기 컨텍스트 / 모델 출력 / tool result / 버려진 컨텍스트로
분해하면 provider 총계와 정확히 일치하며, 일치하지 않는 실행은 발행하지 않습니다.

→ [활동 단위 토큰 측정](docs/ACTIVITY-LOG.md)

## 저장소 구조

```
benchmark/
  config.json     조건 선언 — 새 절약법이 추가되는 유일한 곳
  runner/         실행 격리, optimizer 활성화, 사용량 수집, scheduling
  reports/        턴 분해, 배치 수집, 결과표 생성
  fixture/        Claude에게 구현하도록 제공한 개발 과제
  grader/         agent 작업 공간 밖에서 품질을 평가하는 코드
  runs/           실행 원본 아티팩트 (gitignore)

data/             공개 측정값 — 웹과 결과표의 유일한 출처
web/              브라우저 관람 페이지 (의존성 없음)
docs/             보고서와 가이드
```

## 문서

| 문서 | 내용 |
|---|---|
| [GENERATED_RESULTS.md](docs/GENERATED_RESULTS.md) | 공개 CSV에서 다시 계산한 결과표 |
| [FULL_REPORT.md](docs/FULL_REPORT.md) | 세부 결과, 실패 실행, 해석과 한계 |
| [REPRODUCTION.md](docs/REPRODUCTION.md) | 무료 검증과 유료 재실험 절차 |
| [ACTIVITY-LOG.md](docs/ACTIVITY-LOG.md) | context tax 정의, 검증 방법, 데이터 스키마 |
| [ADDING-A-SKILL.md](docs/ADDING-A-SKILL.md) | 새 절약법 선언 방법 |

한국어와 영어의 토큰 차이는 별도 실험으로 측정했습니다. 짧은 지시문에서는 한국어가
글자당 토큰을 2~2.9배 쓰지만, **코딩 에이전트 전체**로 보면 출력의 약 80%가 코드와
식별자여서 전체 차이는 7.7%(비용 9.4%)에 그쳤고 이는 실행 편차보다 작았습니다.
비용만 보고 모든 작업을 영어로 강제할 필요는 없지만, 긴 system prompt나 장문의 문서를
매번 보내는 구조라면 영어가 유리합니다.

## License

MIT. 자세한 내용은 [`LICENSE`](LICENSE)를 확인하세요.
