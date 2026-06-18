"""
M3 — Agent Hours per Person per Week.

Agent hours = time Claude was actively processing per developer per week.
Derived from: user_ts → assistant_ts gap per turn in session JSONL.
Fallback: session_duration - sum(user_response_times) from session-meta.
"""

from collections import defaultdict


TARGET_HOURS = 80.0
STUCK_THRESHOLD = 20.0


def compute(
    turn_events: list[dict],
    sessions_by_dev: dict[str, list[dict]],
) -> dict[str, dict]:
    """
    Return {developer_key: {week: {agent_hours, session_count, status}}}

    turn_events  : from collectors/sessions.py (primary source)
    sessions_by_dev: pre-grouped session metas, used as fallback when JSONL missing
    """
    # Primary: sum agent_ms from turn events
    primary: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    covered: dict[str, set] = defaultdict(set)

    for event in turn_events:
        if "agent_ms" not in event or event.get("event_type") == "skill":
            continue
        agent_ms = event.get("agent_ms")
        if not agent_ms or agent_ms <= 0:
            continue
        key = event["developer_key"]
        week = _week_from_ts(event.get("user_ts", ""))
        if week:
            primary[key][week] += agent_ms / 3600_000
            covered[key].add(event["session_id"])

    # Fallback: sessions not covered by JSONL parsing
    fallback: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for key, sessions in sessions_by_dev.items():
        covered_sids = covered.get(key, set())
        for meta in sessions:
            if meta["session_id"] in covered_sids:
                continue
            week = meta.get("week")
            if not week:
                continue
            duration_s = (meta.get("duration_minutes") or 0) * 60
            user_idle_s = sum(meta.get("user_response_times") or [])
            fallback[key][week] += max(0.0, duration_s - user_idle_s) / 3600

    # Merge
    all_devs: set[str] = set(primary.keys()) | set(fallback.keys())
    all_weeks: set[str] = set()
    for d in all_devs:
        all_weeks.update(primary.get(d, {}).keys())
        all_weeks.update(fallback.get(d, {}).keys())

    results: dict[str, dict] = {}
    for key in all_devs:
        weeks: dict[str, dict] = {}
        for week in all_weeks:
            hours = primary.get(key, {}).get(week, 0.0) + fallback.get(key, {}).get(week, 0.0)
            hours = round(hours, 2)
            weeks[week] = {
                "agent_hours": hours,
                "status": _status(hours),
            }
        results[key] = {"developer_key": key, "by_week": weeks}

    return results


def _week_from_ts(ts: str) -> str | None:
    if not ts:
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    except Exception:
        return None


def _status(hours: float) -> str:
    if hours >= TARGET_HOURS:
        return "ai_native"
    if hours >= 40:
        return "on_track"
    if hours >= STUCK_THRESHOLD:
        return "underutilized"
    return "stuck"


def team_summary(results: dict[str, dict], week: str) -> dict:
    hours_list = [
        results[k]["by_week"].get(week, {}).get("agent_hours", 0.0)
        for k in results
    ]
    if not hours_list:
        return {}
    avg = round(sum(hours_list) / len(hours_list), 2)
    return {
        "week": week,
        "avg_agent_hours": avg,
        "total_agent_hours": round(sum(hours_list), 2),
        "developers_at_target": sum(1 for h in hours_list if h >= TARGET_HOURS),
        "developers_stuck": sum(1 for h in hours_list if h < STUCK_THRESHOLD),
        "status": _status(avg),
    }
