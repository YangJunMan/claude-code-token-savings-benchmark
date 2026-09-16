"""clone 직후 마찰 없는 시작 경로(quickstart.sh, token-bench 스킬)를 검사한다.

여기서는 스크립트를 실제로 실행하지 않는다(백그라운드 서버를 띄우고 브라우저를
연다) — 구조와 참조 무결성만 정적으로 확인한다. 실제 기동은 이 대화에서
수동으로 검증했다.
"""

import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = REPO_ROOT / "quickstart.sh"
QUICKSTART_PS1 = REPO_ROOT / "quickstart.ps1"
SKILL = REPO_ROOT / ".claude" / "skills" / "token-bench" / "SKILL.md"


def test_quickstart_exists_and_is_executable():
    assert QUICKSTART.is_file()
    mode = QUICKSTART.stat().st_mode
    assert mode & stat.S_IXUSR, "quickstart.sh에 실행 권한이 없다."


def test_quickstart_only_uses_the_stdlib_http_server_and_token_bench():
    """pip install 없이 돌아야 한다는 요구를 코드로 고정한다."""

    text = QUICKSTART.read_text(encoding="utf-8")
    commands = [line for line in text.splitlines() if not line.strip().startswith("#")]
    assert not any("pip install" in line for line in commands)
    assert '"$PYTHON311" -m http.server' in text
    assert "token_bench serve" in text
    assert "--skip-unavailable" in text


def test_quickstart_avoids_lsof_because_linux_minimal_images_lack_it():
    """macOS/Linux 둘 다에서 추가 패키지 설치 없이 돌아야 한다.

    `lsof`는 최소 구성 Linux 배포판(예: 컨테이너 베이스 이미지)에 기본으로
    없는 경우가 흔하다. 포트 점유 확인은 대신 표준 라이브러리 socket으로 한다.
    """

    text = QUICKSTART.read_text(encoding="utf-8")
    commands = [line for line in text.splitlines() if not line.strip().startswith("#")]
    assert not any("lsof" in line for line in commands)
    assert "import socket" in text


def test_quickstart_cleans_up_background_servers_on_exit():
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "trap cleanup EXIT" in text
    assert "kill" in text


def test_quickstart_ps1_exists_for_native_windows():
    """Windows는 quickstart.sh(bash)를 못 돌리므로 PowerShell 대응이 필요하다."""

    assert QUICKSTART_PS1.is_file()
    text = QUICKSTART_PS1.read_text(encoding="utf-8")
    commands = [line for line in text.splitlines() if not line.strip().startswith("#")]
    assert not any("pip install" in line for line in commands)
    assert "token_bench" in text and "serve" in text
    assert "http.server" in text
    assert "--skip-unavailable" in text
    # Start-Job은 자식 프로세스 종료를 보장하지 않는다는 알려진 함정이 있어
    # 실제 실행 코드에는 쓰지 않는다(설명 주석에서 언급하는 것은 무방하다).
    assert not any("Start-Job" in c for c in commands)
    assert "Stop-Process" in text


def test_worker_lock_does_not_import_posix_only_fcntl_unconditionally():
    """`import fcntl`가 모듈 최상단에 있으면 Windows에서 token_bench 전체가 죽는다.

    실제로 이번 실행 검증에서 이 문제를 만났다 — worker.py가 fcntl을 무조건
    import해서, 이 모듈을 쓰는 모든 CLI 명령이 native Windows에서 즉시
    ImportError로 실패했다. 플랫폼 분기로 감싸야 한다.
    """

    text = (REPO_ROOT / "token_bench" / "worker.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    import_lines = [i for i, line in enumerate(lines) if line.strip() == "import fcntl"]
    assert import_lines, "fcntl을 아예 안 쓰게 됐다면 이 테스트도 함께 정리하라."
    for i in import_lines:
        preceding = "\n".join(lines[max(0, i - 20):i])
        assert "sys.platform" in preceding, (
            "import fcntl이 플랫폼 분기 없이 무조건 실행된다."
        )
    assert "msvcrt" in text, "Windows용 대체 잠금(msvcrt)이 없다."


def test_skill_file_exists_with_frontmatter():
    assert SKILL.is_file()
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: token-bench" in text
    assert "description:" in text


def test_skill_requires_user_confirmation_before_spending_subscription_usage():
    """스킬 문서 자체가 enqueue/work 전에 동의를 받으라고 명시해야 한다."""

    text = SKILL.read_text(encoding="utf-8")
    assert "사용자 확인" in text
    assert "token_bench enqueue" in text
    assert "token_bench work" in text
    # 확인 문구가 enqueue 명령보다 앞에 나와야, 순서상 동의가 먼저라는 의도가 드러난다.
    assert text.index("반드시 사용자 확인을 받는다") < text.index("token_bench enqueue")


def test_skill_only_references_commands_that_actually_exist():
    """스킬이 안내하는 명령이 실제 CLI 하위 명령과 어긋나지 않는지 검사한다."""

    text = SKILL.read_text(encoding="utf-8")
    main_text = (REPO_ROOT / "token_bench" / "__main__.py").read_text(encoding="utf-8")
    for verb in ["preflight", "estimate", "approve", "enqueue", "work", "status", "publish"]:
        assert f'"{verb}"' in main_text, f"CLI에 '{verb}' 하위 명령이 없다."
        assert f"token_bench {verb}" in text, f"스킬 문서가 '{verb}'를 안내하지 않는다."


def test_readme_points_to_both_entry_points():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "./quickstart.sh" in readme
    assert "quickstart.ps1" in readme
    assert "token-bench" in readme
