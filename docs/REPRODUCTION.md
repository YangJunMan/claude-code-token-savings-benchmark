# 재현 가이드

이 저장소는 두 가지 경로를 제공합니다. **무료 검증**은 Claude를 호출하지 않고 공개
측정값과 프로그램 동작을 확인합니다. **유료 재실험**은 같은 개발 과제를 다시 수행시키며
Anthropic API 비용이 발생합니다. 유료 경로는 의도적으로 한 번의 명령으로 시작되지
않도록 만들었습니다.

## 지원 환경

| 항목 | 요구 사항 |
|---|---|
| 운영체제 | macOS, Linux |
| Python | 3.9 이상 (무료 검증) · 3.10 이상 (Headroom 설치 시) |
| 도구 | Git, Claude Code 2.1.x |

### Windows

**유료 재실험은 Windows에서 실행되지 않습니다.** `benchmark/runner/public_cli.py`의
preflight가 POSIX가 아닌 환경을 명시적으로 거부합니다.

```
unsupported_os: macOS/Linux POSIX required
```

무료 검증(테스트와 결과표 재계산)은 Python 표준 라이브러리만 사용하므로 Windows에서도
동작할 가능성이 높지만 **검증하지 않았습니다.** 이 저장소의 CI는 Ubuntu에서만 돌아갑니다.
`make`도 Windows에 기본 설치돼 있지 않아 명령을 직접 풀어 써야 합니다.

```powershell
python -m venv .venv
.venv\Scripts\python -m unittest discover -s tests
python scripts\render_published_report.py
```

**권장: WSL2를 사용하세요.** WSL 안에서는 Linux 절차를 그대로 따르면 되고, 유료 경로도
동작합니다.

## 무료 검증

Claude를 호출하지 않으며 `ANTHROPIC_API_KEY`도 필요 없습니다.

```bash
git clone https://github.com/YangJunMan/claude-code-token-savings-benchmark.git
cd claude-code-token-savings-benchmark
make setup
make smoke
make report
git diff --exit-code docs/GENERATED_RESULTS.md
```

`make report`는 커밋된 정제 집계 CSV에서 공개 결과표를 다시 계산합니다. 마지막 명령이
아무것도 출력하지 않으면 새로 계산한 표가 저장소의 표와 같다는 뜻입니다.

이 과정은 **비공개 Claude transcript를 복원하지 않습니다.** transcript에는 로컬 경로,
세션 식별자, prompt 내용이 포함될 수 있어 의도적으로 제외했습니다.

## 실험 설계

- **모델**: Claude Sonnet 5, effort `medium`, 영어 prompt
- **작업**: SQLite 기반 GPU 작업 admission service 구현. 코드가 대부분이고 문서 작성 포함
- **실행 구성**: baseline 2회, 그다음 Headroom 2회, Caveman full · `be brief` · RTK 각 1회
- **캐시**: 한 실행 안에서는 prompt caching을 허용합니다. 실행마다 고유 system nonce와
  고유 sentinel MCP tool 이름을 부여해 실행 간 캐시 재사용을 최소화합니다
- **격리**: 모든 실행은 fixture의 새 복사본에서 시작합니다. held-out grader 테스트는
  agent 작업 디렉터리 밖에 둡니다
- **품질 기준**: 기능 테스트와 구현·문서 rubric

반복 횟수는 `benchmark/config.json`의 각 조건 `repeat` 값으로 선언됩니다. baseline을
반복하는 이유는 **실행 간 자연 변동을 먼저 측정해야 절감률을 해석할 수 있기 때문**입니다.

이것은 1회성 탐색 실험입니다. 동일한 baseline 두 번도 비용이 9.78%, 처리 토큰이 22.06%
달랐으므로, 작은 차이를 인과 효과로 해석하면 안 됩니다.

## 유료 재실험

### 1. 도구 설치

각 도구의 공식 안내를 먼저 확인한 뒤 설치하세요.

```bash
make setup-paid                                    # Headroom (Python 3.10 이상 필요)
brew install rtk-ai/tap/rtk                        # macOS. Linux는 RTK 저장소 참고
claude plugin marketplace add JuliusBrussee/caveman
claude plugin install caveman@caveman
make preflight
```

> `make setup`이 만든 venv가 Python 3.9라면 `make setup-paid`가 실패합니다.
> `rm -rf .venv && python3.11 -m venv .venv` 후 다시 실행하세요.

- Headroom: <https://github.com/headroomlabs-ai/headroom/blob/main/wiki/getting-started.md>
- Caveman: <https://github.com/ryailabs/caveman/blob/main/INSTALL.md>
- RTK: <https://github.com/rtk-ai/rtk>

`make preflight`는 **조건 선언에서 필요한 도구를 유도해** 검사합니다. `benchmark/config.json`에
새 조건을 추가하면 그 도구도 자동으로 검사 대상이 됩니다. 기본 위치가 아닌 곳에 설치했다면
각 조건 선언의 `env_override`에 해당하는 환경 변수(예: `HEADROOM_BIN`, `CAVEMAN_PLUGIN_DIR`)를
설정하세요.

preflight는 모델 접근을 시험하지 않습니다. 유료 요청이 되기 때문입니다. 실행 파일과 경로의
존재만 확인하므로 첫 유료 실행 전에 각 도구의 버전과 활성화 상태를 직접 확인하세요.

### 2. 예상 비용 확인

API key 없이 실행됩니다.

```bash
make estimate
```

공개 재현 계획은 baseline과 Headroom을 각 2회, 나머지 세 조건을 1회씩 총 7개 작업을
**순차** 실행합니다. 반복 조건이 있어야 그 조건의 백분율을 해석할 수 있기 때문입니다.

과거 실험 비용은 다음과 같았습니다.

| 구분 | 포함된 실행 | 무효 실행 포함 |
|---|---:|---:|
| 최초 6개 작업 | 약 $10.05 | 약 $16.77 |
| Headroom 2차 실행 추가 후 | 약 $11.62 | 약 $18.33 |

가격, 모델 동작, 재시도, 도구 버전은 달라질 수 있습니다. estimator가 보여주는 값은 실제
청구액 보장이 아니라 **보수적인 계획 상한**입니다.

### 3. 실행

아래 조건이 모두 충족되지 않으면 실행되지 않습니다.

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

안전장치:

- `--confirm-paid-run`이 없으면 실행하지 않습니다
- 예산이 `make estimate`의 보수적 상한에 미치지 못하면 거부합니다
- `ANTHROPIC_API_KEY`가 없으면 OAuth로 우회하지 않고 중단합니다
- `--run-root`는 비어 있어야 합니다. 기존 증거를 덮어쓰지 않습니다
- 작업은 병렬이 아니라 순차로 실행합니다
- 누적 예상 비용이 전체 예산을 넘기 전에 다음 작업을 중단하며, 각 Claude 프로세스에도
  `$2.50` 상한을 전달합니다

`--run-root`와 `--report-dir`에는 매번 새 이름을 쓰세요.

### 4. 결과 수집

실행이 끝나면 각 실행의 증거는 `--run-root` 아래에, 상태·비용·품질 요약은
`--report-dir/reproduction-summary.json`에 저장됩니다.

턴 단위 토큰 로그를 만들려면 수집기를 실행합니다.

```bash
python3 -c "
from benchmark.reports.collect import collect_batch
from pathlib import Path
print(collect_batch(Path('benchmark/runs/reproduction-001'),
                    Path('data/activity-log.csv'), Path('data/run-summary.csv')))
"
```

같은 배치를 두 번 수집해도 행이 중복되지 않습니다. 자세한 내용은
[활동 단위 토큰 측정](ACTIVITY-LOG.md)을 참고하세요.

## 보안 경계

자동화 과정은 Claude Code를 `--permission-mode bypassPermissions`로 실행합니다. 코딩
과제가 새 fixture를 대화형 확인 없이 수정하고 테스트할 수 있게 하기 위해서입니다.

**이것은 OS sandbox가 아닙니다.** tool subprocess가 API credential을 상속하거나 fixture
밖의 경로와 네트워크에 접근할 수 있습니다. optimizer의 활성화 방식도 버전에 따라 다를 수
있습니다.

- `benchmark/runner/claude.py`를 직접 확인하세요
- 도구 버전을 고정하세요
- 돈을 쓰기 전에 활성화 여부를 확인하는 probe를 돌리세요
- **신뢰할 수 없는 prompt나 저장소를 API key가 설정된 환경에서 실행하지 마세요**

이 저장소의 어떤 CI workflow도 유료 모델을 호출하지 않습니다.

## 결과가 정확히 재현되지 않는 이유

이 저장소의 harness는 **결함 수정본**입니다. 공개된 수치를 생산한 실행들은 수정 과정
중에 나왔기 때문에 지금 이 트리로 재실험하면 같은 숫자가 그대로 나오지는 않습니다.
재실험을 막던 결함은 모두 고쳐져 있습니다. 자세한 목록은
[전체 실험 보고서](FULL_REPORT.md)의 한계 절을 참고하세요.
