"""CLI와 Web이 공유하는 조건 선택·준비·검증·승인 계획 생성."""

from dataclasses import dataclass
from pathlib import Path

from token_bench.authorization import AuthorizationError, EstimatePlan, build_estimate, save_json
from token_bench.conditions import ConditionError, inspect, needs_customizations
from token_bench.preflight import check, split_by_availability
from token_bench.workspace import DEFAULT_TASK_PROMPT_PATH, WorkspaceError, prepare_batch


class IntakeError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedPlan:
    plan: EstimatePlan
    plan_path: Path
    skipped: tuple


def create_plan(
    conditions_path: Path,
    *,
    timeout_seconds: int,
    task_prompt_path: Path = DEFAULT_TASK_PROMPT_PATH,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    skip_unavailable: bool = False,
    isolation: str | None = None,
    model: str = "",
) -> PreparedPlan:
    skipped = []
    try:
        runs = inspect(conditions_path, include=include, exclude=exclude)
        if skip_unavailable:
            runs, skipped = split_by_availability(runs)
        if not runs:
            raise IntakeError("실행할 수 있는 조건이 없다.")
        workspaces = prepare_batch(
            runs, timeout_seconds=timeout_seconds, task_prompt_path=task_prompt_path,
        )
        reports = [check(run) for run in runs]
        problems = [
            f"[{run.condition_id}__r{run.repeat_index}] {problem}"
            for run, report in zip(runs, reports) for problem in report.problems
        ]
        if not all(report.ok for report in reports):
            raise IntakeError("preflight 실패: " + "; ".join(problems))
        isolation = isolation or (
            "project-settings"
            if any(needs_customizations(run.injections) for run in runs)
            else "safe-mode"
        )
        batch_id = workspaces[0].snapshot_path.parent.parent.name
        plan = build_estimate(
            workspaces, batch_id=batch_id, timeout_seconds=timeout_seconds,
            auth=next((r.auth for r in reports if r.auth), {}),
            isolation=isolation, model=model,
            tool_fingerprints={ws.run_id: r.tool_fingerprints for ws, r in zip(workspaces, reports)},
        )
        plan_path = workspaces[0].snapshot_path.parent.parent / "plan.json"
        save_json(plan.to_dict(), plan_path)
        return PreparedPlan(plan, plan_path, tuple(skipped))
    except (ConditionError, WorkspaceError, AuthorizationError) as exc:
        raise IntakeError(str(exc)) from exc
