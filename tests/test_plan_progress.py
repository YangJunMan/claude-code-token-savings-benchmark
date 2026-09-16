"""docs/IMPLEMENTATION-PLAN*.md의 진행 상태 표가 실제 코드 상태와 어긋나지 않는지 검사한다.

이 테스트는 계획 문서 상태 표 자체를 파싱하므로, 새 마일스톤이 계획에 추가되면
아래 MILESTONE_OWNERSHIP도 함께 갱신해야 한다.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN = REPO_ROOT / "archive" / "docs" / "IMPLEMENTATION-PLAN.md"
MAIN_MODULE = REPO_ROOT / "token_bench" / "__main__.py"

STATUS_RANK = {"완료": 2, "진행 중": 1, "대기": 0}

# 각 마일스톤이 처음 만드는 신규 파일(세 계획 문서의 "신규:" 목록)과,
# 처음 도입하는 CLI 하위 명령.
MILESTONE_OWNERSHIP: dict[str, tuple[list[str], list[str]]] = {
    "M1": (
        [
            "token_bench/__init__.py",
            "token_bench/__main__.py",
            "token_bench/conditions.py",
            "benchmark/conditions.json",
        ],
        ["inspect"],
    ),
    "M2": (["token_bench/workspace.py"], ["prepare"]),
    "M3": (["token_bench/preflight.py", "token_bench/claude_code.py"], ["preflight"]),
    "M4": (["token_bench/authorization.py"], ["estimate", "approve"]),
    "M5": (["token_bench/job_store.py"], ["enqueue", "status"]),
    "M6": (["token_bench/worker.py"], ["work"]),
    "M7": (["token_bench/results.py"], ["result"]),
    "M8": (["token_bench/evaluation.py"], []),
    "M9": ([], []),
    "M10": (["token_bench/api_auth.py"], []),
    "M11": ([], []),
    "M12": (["token_bench/publish.py"], ["publish"]),
    "M13": (["web/index.html", "web/app.js", "web/style.css"], []),
    "M14": ([], []),
    "M15": (["token_bench/webapi.py"], ["serve"]),
    # M19에서 run.html/run.js가 index.html의 탭과 settings.js로 흡수됐다.
    "M16": (["web/settings.js"], []),
    "M17": ([], []),
    "M18": (
        ["benchmark/prompts/preset-large.md", "benchmark/prompts/preset-very-large.md"],
        [],
    ),
    "M19": ([], []),
    "M20": ([], []),
    "M21": ([], []),
    "M22": ([], []),
    "M23": ([], []),
    "M24": ([], []),
    "M25": ([], []),
    "M26": (["token_bench/tooling.py"], []),
}

# M10·M11(3단계, API)은 API 잔액 부족으로 차단되어 있고, 사용자 지시로
# M12부터(4~5단계) 그 완료를 기다리지 않고 진행한다(IMPLEMENTATION-PLAN.md의
# "진행 순서에 대한 예외" 참고). 그래서 "완료 접두사 -> 진행 중 0~1개 ->
# 나머지 대기" 규칙은 전체 표가 아니라 각 트랙 안에서만 검사한다.
DEPENDENCY_TRACKS: list[list[str]] = [
    ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11"],
    [
        "M12", "M13", "M14", "M15", "M16", "M17", "M18", "M19",
        "M22", "M23", "M24", "M25", "M26",
    ],
    # M20(세 조건 재실행)과 M21(턴 단위 분해)은 서로도, 다른 마일스톤과도
    # 의존하지 않는 독립 항목이라 각자 한 트랙으로 둔다. 둘이 대기 중이어도
    # 뒤이은 작업(M22)이 진행될 수 있다.
    ["M20"],
    ["M21"],
]


def _parse_progress_table() -> list[tuple[str, str]]:
    text = PLAN.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\|\s*(M\d+)\s*\|.*\|\s*(대기|진행 중|완료)\s*\|.*\|\s*$",
        text,
        flags=re.MULTILINE,
    )
    assert rows, "진행 상태 표를 찾지 못했다."
    return rows


def test_progress_table_covers_all_known_milestones_in_order():
    rows = _parse_progress_table()
    ids = [milestone_id for milestone_id, _ in rows]
    assert ids == list(MILESTONE_OWNERSHIP.keys())


def test_at_most_one_milestone_in_progress():
    rows = _parse_progress_table()
    in_progress = [mid for mid, status in rows if status == "진행 중"]
    assert len(in_progress) <= 1, f"동시에 '진행 중'인 단계: {in_progress}"


def test_status_sequence_is_completed_prefix_then_at_most_one_in_progress_then_waiting():
    """의존 트랙마다 '완료 접두사 -> 진행 중 0~1개 -> 나머지 대기' 순서를 검사한다.

    트랙을 나누는 이유는 DEPENDENCY_TRACKS의 주석을 참고하라.
    """

    status_by_id = dict(_parse_progress_table())

    for track in DEPENDENCY_TRACKS:
        ranks = [STATUS_RANK[status_by_id[mid]] for mid in track]

        first_non_complete = next(
            (i for i, rank in enumerate(ranks) if rank != STATUS_RANK["완료"]),
            len(ranks),
        )
        prefix = ranks[:first_non_complete]
        rest = ranks[first_non_complete:]

        assert all(rank == STATUS_RANK["완료"] for rank in prefix), (
            f"{track}: 완료가 아닌 단계 이후에 다시 완료가 나타날 수 없다."
        )
        assert STATUS_RANK["완료"] not in rest, (
            f"{track}: 완료가 아닌 단계 뒤에 완료 단계가 있다."
        )
        assert rest.count(STATUS_RANK["진행 중"]) <= 1
        if rest and rest[0] == STATUS_RANK["진행 중"]:
            assert all(rank == STATUS_RANK["대기"] for rank in rest[1:]), (
                f"{track}: '진행 중' 다음에는 모두 '대기'여야 한다."
            )
        else:
            assert all(rank == STATUS_RANK["대기"] for rank in rest)


def test_waiting_milestones_have_no_files_and_no_cli_exposure():
    rows = dict(_parse_progress_table())
    main_text = MAIN_MODULE.read_text(encoding="utf-8") if MAIN_MODULE.exists() else ""

    for milestone_id, status in rows.items():
        if status != "대기":
            continue
        files, verbs = MILESTONE_OWNERSHIP[milestone_id]
        for rel_path in files:
            assert not (REPO_ROOT / rel_path).exists(), (
                f"{milestone_id}는 '대기' 상태인데 {rel_path}가 이미 존재한다."
            )
        for verb in verbs:
            pattern = rf"add_parser\(\s*[\"']{re.escape(verb)}[\"']"
            assert re.search(pattern, main_text) is None, (
                f"{milestone_id}는 '대기' 상태인데 CLI에 '{verb}' 명령이 노출되어 있다."
            )
