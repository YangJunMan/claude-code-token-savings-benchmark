"""테스트에서 쓰는 가짜 CLI(claude 등)를 OS에 맞게 만든다.

Windows는 shebang(`#!/bin/sh`)을 해석하지 않고, 확장자 없는 파일은 직접
실행하면 `WinError 193`을 내며, `shutil.which`도 PATHEXT(.exe/.bat/.cmd 등)가
붙은 파일만 찾는다. POSIX 쉘 스크립트 하나로는 세 OS를 다 커버할 수 없어서,
동작 로직은 파이썬 한 벌로 쓰고 그걸 부르는 launcher만 OS별로 만든다.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path


def write_fake_cli(directory: Path, name: str, python_body: str) -> Path:
    """`directory`에 `name`으로 실행 가능한 가짜 CLI를 만들어 그 경로를 반환한다.

    `python_body`는 완전한 파이썬 스크립트 소스다 — `sys.argv`로 인자를 받고
    stdout/stderr/exit code로 동작을 흉내낸다. PATH에 두거나 경로를 직접
    넘겨 호출한다(Windows에서는 `.bat`, 그 외에는 확장자 없음 — 실제 `claude`
    CLI가 두 플랫폼에서 이런 모양으로 설치되는 것과 같다).
    """

    directory.mkdir(parents=True, exist_ok=True)
    impl_path = directory / f"_{name}_impl.py"
    impl_path.write_text(python_body, encoding="utf-8")

    if sys.platform == "win32":
        launcher = directory / f"{name}.bat"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{impl_path}" %*\r\n', encoding="utf-8"
        )
        return launcher

    launcher = directory / name
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl_path}" "$@"\n', encoding="utf-8"
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher
