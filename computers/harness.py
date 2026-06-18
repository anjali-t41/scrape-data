"""
M6 — Harness Utilization Score (0–100).

Measures adoption of Claude Code's orchestration capabilities:
  - Plan mode (plans/ files created)
  - Task agents (uses_task_agent sessions)
  - Background tasks (hasUsedBackgroundTask)
  - Workflow tool (Workflow in tool_counts)
"""

from collections import defaultdict


def compute(
    sessions_by_dev: dict[str, list[dict]],
    plans_data: dict[str, dict],
    app_state: dict[str, dict],
) -> dict[str, dict]:
    """Return {developer_key: {harness_score, components}}."""

    all_devs = set(sessions_by_dev.keys()) | set(plans_data.keys()) | set(app_state.keys())
    results: dict[str, dict] = {}

    for key in all_devs:
        sessions = sessions_by_dev.get(key, [])
        total = len(sessions)

        # Component 1: Plan Mode (0–25)
        new_plans = plans_data.get(key, {}).get("new_plans_since_last_run", 0)
        plan_score = min(25.0, new_plans * 5.0)

        # Component 2: Task Agent (0–25)
        task_sessions = sum(1 for s in sessions if s.get("uses_task_agent"))
        task_score = (task_sessions / total * 25.0) if total else 0.0

        # Component 3: Background Tasks (0–25)
        bg_score = 25.0 if app_state.get(key, {}).get("has_used_background_task") else 0.0

        # Component 4: Workflow Tool (0–25)
        workflow_sessions = sum(
            1 for s in sessions if "Workflow" in (s.get("tool_counts") or {})
        )
        workflow_score = (workflow_sessions / total * 25.0) if total else 0.0

        total_score = round(plan_score + task_score + bg_score + workflow_score, 1)

        results[key] = {
            "developer_key": key,
            "harness_score": total_score,
            "components": {
                "plan_mode": round(plan_score, 1),
                "task_agent": round(task_score, 1),
                "background_task": round(bg_score, 1),
                "workflow_tool": round(workflow_score, 1),
            },
            "plan_files_created": new_plans,
            "task_agent_sessions": task_sessions,
            "workflow_sessions": workflow_sessions,
        }

    return results
