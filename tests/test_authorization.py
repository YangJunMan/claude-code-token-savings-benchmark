from pathlib import Path

import pytest

from token_bench.authorization import (
    AuthorizationError,
    approve,
    build_estimate,
    load_approval,
    load_plan,
    save_json,
)
from token_bench.workspace import RunWorkspace


def _workspace(condition_id="base", repeat_index=1, content_id="abc"):
    return RunWorkspace(
        run_id=f"batch1-{condition_id}__r{repeat_index}",
        content_id=content_id,
        condition_id=condition_id,
        repeat_index=repeat_index,
        workdir=Path("/tmp/workdir"),
        snapshot_path=Path("/tmp/snapshot.json"),
    )


SUBSCRIPTION_AUTH = {
    "logged_in": True,
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "pro",
}


def test_build_estimate_never_claims_zero_cost():
    plan = build_estimate(
        [_workspace()],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    assert "$0" not in plan.cost_disclaimer
    assert "확인" in plan.cost_disclaimer
    assert plan.run_count == 1


def test_build_estimate_rejects_empty_workspace_list():
    with pytest.raises(AuthorizationError):
        build_estimate(
            [], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
        )


def test_same_inputs_produce_same_digest():
    workspaces = [_workspace()]
    plan1 = build_estimate(
        workspaces, batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    plan2 = build_estimate(
        workspaces, batch_id="batch2", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    assert plan1.digest == plan2.digest


def test_changing_content_id_changes_digest():
    plan1 = build_estimate(
        [_workspace(content_id="abc")],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    plan2 = build_estimate(
        [_workspace(content_id="xyz")],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    assert plan1.digest != plan2.digest


def test_changing_auth_method_changes_digest():
    plan1 = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    api_auth = {**SUBSCRIPTION_AUTH, "auth_method": "apiKey", "api_provider": "direct"}
    plan2 = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=api_auth, isolation="safe-mode"
    )
    assert plan1.digest != plan2.digest


def test_changing_timeout_changes_digest():
    base_plan = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    timeout_plan = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=61, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    assert base_plan.digest != timeout_plan.digest


def test_changing_tool_fingerprint_changes_digest():
    first = build_estimate(
        [_workspace()],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH,
        isolation="safe-mode",
        tool_fingerprints={"batch1-base__r1": ({"name": "tool", "version_output": "1"},)},
    )
    second = build_estimate(
        [_workspace()],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH,
        isolation="safe-mode",
        tool_fingerprints={"batch1-base__r1": ({"name": "tool", "version_output": "2"},)},
    )
    assert first.digest != second.digest


def test_approve_succeeds_with_matching_digest():
    plan = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    record = approve(plan, confirmed_digest=plan.digest)
    assert record.digest == plan.digest
    assert record.approved_at


def test_approve_rejects_mismatched_digest():
    plan = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    with pytest.raises(AuthorizationError, match="digest"):
        approve(plan, confirmed_digest="wrong-digest")


def test_changed_input_invalidates_previous_approval():
    """입력이 바뀌면 이전 승인의 digest로는 새 계획을 승인할 수 없다."""
    original_plan = build_estimate(
        [_workspace(content_id="abc")],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    approved_digest = original_plan.digest

    changed_plan = build_estimate(
        [_workspace(content_id="changed")],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    with pytest.raises(AuthorizationError):
        approve(changed_plan, confirmed_digest=approved_digest)


def test_plan_round_trips_through_json(tmp_path):
    plan = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    path = tmp_path / "plan.json"
    save_json(plan.to_dict(), path)
    loaded = load_plan(path)
    assert loaded == plan


def test_approval_round_trips_through_json(tmp_path):
    plan = build_estimate(
        [_workspace()], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    record = approve(plan, confirmed_digest=plan.digest)
    path = tmp_path / "approval.json"
    save_json(record.to_dict(), path)
    loaded = load_approval(path)
    assert loaded == record


def test_load_plan_missing_file_raises():
    with pytest.raises(AuthorizationError, match="찾을 수 없다"):
        load_plan(Path("/nonexistent/plan.json"))


def test_load_plan_invalid_json_raises(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AuthorizationError, match="JSON"):
        load_plan(path)
