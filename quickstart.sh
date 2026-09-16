#!/usr/bin/env bash
# clone 직후 한 줄로 웹을 띄운다. 표준 라이브러리만 쓰므로 pip install이
# 필요 없다 — token_bench와 정적 웹 서버 모두 Python 내장 http.server 위에서
# 돈다. Headroom·RTK·Caveman처럼 별도 설치가 필요한 조건은 preflight가
# 알아서 건너뛰고 설치법을 알려준다(--skip-unavailable).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

WEB_PORT="${WEB_PORT:-8765}"
API_PORT="${API_PORT:-8787}"

find_python311() {
  for candidate in python3.11 /opt/homebrew/opt/python@3.11/bin/python3.11 /usr/local/opt/python@3.11/bin/python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON311="$(find_python311 || true)"
if [ -z "$PYTHON311" ]; then
  echo "Python 3.11을 찾지 못했습니다." >&2
  echo "  macOS:  brew install python@3.11" >&2
  echo "  Linux:  사용 중인 배포판의 패키지 관리자로 python3.11을 설치하세요." >&2
  exit 1
fi

echo "== 조건 가용성 확인 (모델 호출 없음) =="
"$PYTHON311" -m token_bench preflight --skip-unavailable || true

# macOS와 Linux 둘 다에서 추가 도구 없이 돌아야 하므로 포트 점유 확인도
# lsof/ss 같은 배포판마다 있고 없고가 갈리는 명령 대신 Python 표준
# 라이브러리(socket)로 한다.
port_in_use() {
  "$PYTHON311" - "$1" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

PIDS=()
cleanup() {
  echo
  echo "서버를 정리합니다."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

if port_in_use "$API_PORT"; then
  echo "== 로컬 실험 API는 이미 :${API_PORT}에서 실행 중입니다 =="
else
  echo "== 로컬 실험 API 시작 (127.0.0.1:${API_PORT}, 모델 호출 없음) =="
  "$PYTHON311" -m token_bench serve --port "$API_PORT" >/tmp/token-bench-api.log 2>&1 &
  PIDS+=("$!")
fi

if port_in_use "$WEB_PORT"; then
  echo "== 웹은 이미 :${WEB_PORT}에서 실행 중입니다 =="
else
  echo "== 웹 서버 시작 (127.0.0.1:${WEB_PORT}) =="
  "$PYTHON311" -m http.server "$WEB_PORT" >/tmp/token-bench-web.log 2>&1 &
  PIDS+=("$!")
fi

URL="http://127.0.0.1:${WEB_PORT}/web/#settings"
sleep 1
echo
echo "== 준비 완료: ${URL} =="
if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
else
  echo "브라우저에서 위 주소를 직접 여세요."
fi

echo "이 창을 열어 둔 채로 두면 서버가 유지됩니다. 끝내려면 Ctrl+C."
wait
