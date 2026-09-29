이 저장소의 예정된 벤치마크 실행(`.github/workflows/bench.yml`)이 실패했다.
`context.log`에 실패 로그가 있다. 원인을 읽고 최소한의 수정을 적용하라.

수정해도 되는 파일은 이 둘뿐이다.

- `token_bench/diagnostics.py`
- `.github/workflows/bench.yml`

다른 파일은 수정하지 마라. 특히 `tests/` 아래를 고쳐서 테스트를 통과시키려 하지
마라. 위 두 파일로 고칠 수 없는 원인이면 아무것도 수정하지 말고 무엇이 필요한지만
설명하라. 수정하지 않는 것이 잘못된 수정보다 낫다 — 사람이 그 설명을 읽는다.

허용되는 수정은 운영 파라미터뿐이다.

- 진단 모델 alias가 은퇴함 → `DEFAULT_MODEL` 또는 `MODEL_PREFERENCE`를 살아 있는
  Sonnet 계열로 조정
- 고정한 도구 버전(`CLAUDE_CODE_VERSION`·`RTK_VERSION`·`CAVEMAN_SHA`)을 더 이상
  받을 수 없음 → 받을 수 있는 값으로 조정

측정 로직은 바꾸지 마라. 조건 정의, 격리 모드, 게시 대상 상태(`PUBLISHABLE_STATUSES`),
turn 추출은 실험의 정의이며 여기서 손대면 과거 데이터와 비교할 수 없게 된다.

진단 모델은 항상 `sonnet` alias(최신 Sonnet)와 `--effort low`다(사용자 결정). 다른
계열로 바꾸거나 effort를 올리지 마라. Sonnet이 하나도 남지 않았다면, 그 사실을
설명하고 수정은 하지 마라.
