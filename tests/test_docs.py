"""README에 나온 사용법 예시가 실제로 동작하는지 CI에서 검사한다."""

import re
import subprocess
import sys
from pathlib import Path

from token_bench.conditions import load_conditions

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fenced_bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)


def test_readme_inspect_example_runs():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = _fenced_bash_blocks(readme)
    inspect_lines = [
        line
        for block in blocks
        for line in block.splitlines()
        if "-m token_bench inspect" in line
    ]
    assert inspect_lines, "README에 'python3.11 -m token_bench inspect' 예시가 있어야 한다."

    command = inspect_lines[0].strip()
    args = command.split()
    # README의 python3.11을 현재 테스트를 실행 중인 인터프리터로 치환한다.
    assert args[1] == "-m"
    args = [sys.executable, *args[1:]]

    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"condition_id": "base"' in result.stdout


def test_local_doc_links_resolve():
    """README와 docs의 상대 링크가 실제 파일을 가리키는지 검사한다.

    삭제된 문서를 가리키는 링크가 남아 있으면 클론한 사람이 404를 만난다.
    """

    broken: list[str] = []
    for source in [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]:
        text = source.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = (source.parent / target.split("#", 1)[0]).resolve()
            if not path.exists():
                broken.append(f"{source.relative_to(REPO_ROOT)} -> {target}")
    assert not broken, broken


def test_adding_skill_example_is_a_valid_registry(tmp_path):
    guide = (REPO_ROOT / "docs" / "ADDING-A-SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"```json\n(.*?)```", guide, flags=re.DOTALL)
    assert match, "추가 가이드에 완전한 JSON registry 예시가 있어야 한다."
    registry = tmp_path / "conditions.json"
    registry.write_text(match.group(1), encoding="utf-8")

    conditions = load_conditions(registry)
    assert any(condition.id == "my-skill" for condition in conditions)


def test_readme_points_to_canonical_skill_guide():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "[새 절약법 추가하기](docs/ADDING-A-SKILL.md)" in readme

    guide = (REPO_ROOT / "docs" / "ADDING-A-SKILL.md").read_text(encoding="utf-8")
    assert '"repository_url"' in guide
    assert "pip install" not in guide
    assert "curl " not in guide
