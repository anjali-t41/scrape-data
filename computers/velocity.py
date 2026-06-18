"""
M10 — Code Velocity per AI Hour.

Lines changed per agent hour. Normalizes output across different session lengths.
"""

from collections import defaultdict


def compute(
    sessions_by_dev: dict[str, list[dict]],
    agent_hours_data: dict[str, dict],
) -> dict[str, dict]:
    """Return {developer_key: {velocity_per_hour, total_lines, by_week}}."""

    dev_lines: dict[str, dict[str, int]] = {}
    for key, sessions in sessions_by_dev.items():
        lines_by_week: dict[str, int] = defaultdict(int)
        for meta in sessions:
            week = meta.get("week") or "unknown"
            added = meta.get("lines_added") or 0
            removed = meta.get("lines_removed") or 0
            lines_by_week[week] += added + int(removed * 0.5)
        dev_lines[key] = dict(lines_by_week)

    results: dict[str, dict] = {}
    all_devs = set(dev_lines.keys()) | set(agent_hours_data.keys())

    for key in all_devs:
        lines_by_week = dev_lines.get(key, {})
        hours_by_week = {
            w: v.get("agent_hours", 0.0)
            for w, v in agent_hours_data.get(key, {}).get("by_week", {}).items()
        }

        total_lines = sum(lines_by_week.values())
        total_hours = sum(hours_by_week.values())
        overall_velocity = round(total_lines / total_hours, 1) if total_hours else 0.0

        all_weeks = set(lines_by_week.keys()) | set(hours_by_week.keys())
        by_week = {}
        for w in all_weeks:
            l = lines_by_week.get(w, 0)
            h = hours_by_week.get(w, 0.0)
            by_week[w] = {
                "lines_changed": l,
                "agent_hours": round(h, 2),
                "velocity": round(l / h, 1) if h else 0.0,
            }

        results[key] = {
            "developer_key": key,
            "velocity_lines_per_hour": overall_velocity,
            "total_lines_changed": total_lines,
            "total_agent_hours": round(total_hours, 2),
            "by_week": by_week,
        }

    return results


def team_summary(results: dict[str, dict]) -> dict:
    total_lines = sum(r["total_lines_changed"] for r in results.values())
    total_hours = sum(r["total_agent_hours"] for r in results.values())
    return {
        "team_velocity": round(total_lines / total_hours, 1) if total_hours else 0.0,
        "total_lines_changed": total_lines,
        "total_agent_hours": round(total_hours, 2),
    }
