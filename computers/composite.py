"""
M1 — AI Native Score (0–100, composite).

Weighted roll-up of all metric dimensions.
Maps to benchmark labels: AI Absent / AI Aware / AI Assisted / AI Augmented / AI Native.

Weights sum to exactly 1.0.  Consistency replaces some of the parallel_agents
weight — showing up daily matters as much as using multi-agent occasionally.
"""


_WEIGHTS = {
    "adoption":        0.20,
    "agent_hours":     0.25,
    "parallel_agents": 0.10,
    "depth":           0.15,
    "harness":         0.08,
    "trust":           0.08,
    "outcomes":        0.05,
    "velocity":        0.04,
    "consistency":     0.05,
}

_BENCHMARKS = [
    (86, "AI Native"),
    (71, "AI Augmented"),
    (51, "AI Assisted"),
    (26, "AI Aware"),
    (0,  "AI Absent"),
]


def _normalize_agent_hours(hours: float, target: float = 80.0) -> float:
    return min(100.0, hours / target * 100.0)


def _normalize_parallel(parallel_pct: float) -> float:
    return min(100.0, parallel_pct / 30.0 * 100.0)


def _label(score: float) -> str:
    for threshold, label in _BENCHMARKS:
        if score >= threshold:
            return label
    return "AI Absent"


def compute(
    developer_key: str,
    adoption_data: dict,
    agent_hours_data: dict,
    parallel_data: dict,
    depth_data: dict,
    harness_data: dict,
    trust_data: dict,
    outcomes_data: dict,
    velocity_data: dict,
    consistency_data: dict | None = None,
    week: str | None = None,
) -> dict:
    """Compute composite AI Native Score for one developer."""

    # Adoption (0–100)
    adoption_score = adoption_data.get("adoption_index", 0.0)

    # Agent hours (normalized to target)
    if week:
        hours = agent_hours_data.get("by_week", {}).get(week, {}).get("agent_hours", 0.0)
    else:
        hours = max(
            (v.get("agent_hours", 0.0) for v in agent_hours_data.get("by_week", {}).values()),
            default=0.0,
        )
    agent_hours_score = _normalize_agent_hours(hours)

    # Parallel agents (normalized to 30% target)
    parallel_pct = parallel_data.get("parallel_sessions_pct", 0.0)
    parallel_score = _normalize_parallel(parallel_pct)

    # Depth (already 0–100)
    depth_score = depth_data.get("avg_depth_score", 0.0)

    # Harness (already 0–100)
    harness_score = harness_data.get("harness_score", 0.0)

    # Trust (already 0–100)
    trust_score = trust_data.get("trust_index", 0.0)

    # Outcomes (goal achievement rate, 0–100)
    outcomes_score = outcomes_data.get("goal_achievement_rate") or 0.0

    # Velocity: normalize to a reasonable ceiling (500 lines/hr = 100)
    velocity = velocity_data.get("velocity_lines_per_hour", 0.0)
    velocity_score = min(100.0, velocity / 5.0)

    # Consistency (0–100) — daily habit regularity
    consistency_score = (consistency_data or {}).get("consistency_score", 0.0)

    components = {
        "adoption":        adoption_score,
        "agent_hours":     agent_hours_score,
        "parallel_agents": parallel_score,
        "depth":           depth_score,
        "harness":         harness_score,
        "trust":           trust_score,
        "outcomes":        outcomes_score,
        "velocity":        velocity_score,
        "consistency":     consistency_score,
    }

    composite = sum(components[k] * _WEIGHTS[k] for k in components)
    composite = round(min(100.0, max(0.0, composite)), 1)

    return {
        "developer_key": developer_key,
        "ai_native_score": composite,
        "label": _label(composite),
        "components": {k: round(v, 1) for k, v in components.items()},
        "weights": _WEIGHTS,
        "agent_hours_raw": round(hours, 2),
        "week": week,
    }


def team_composite(developer_scores: list[dict], equity_data: dict | None = None) -> dict:
    if not developer_scores:
        return {}
    scores = [d["ai_native_score"] for d in developer_scores]
    avg = round(sum(scores) / len(scores), 1)
    result = {
        "team_ai_native_score": avg,
        "label": _label(avg),
        "developer_count": len(scores),
        "top_score": round(max(scores), 1),
        "bottom_score": round(min(scores), 1),
        "at_ai_native":    sum(1 for s in scores if s >= 86),
        "at_ai_augmented": sum(1 for s in scores if 71 <= s < 86),
        "at_ai_assisted":  sum(1 for s in scores if 51 <= s < 71),
        "at_ai_aware":     sum(1 for s in scores if 26 <= s < 51),
        "ai_absent":       sum(1 for s in scores if s < 26),
    }
    if equity_data:
        result["gini_coefficient"]       = equity_data.get("gini_coefficient")
        result["equity_label"]           = equity_data.get("equity_label")
        result["trajectory_slope"]       = equity_data.get("trajectory_slope_per_week")
        result["trajectory_label"]       = equity_data.get("trajectory_label")
        result["hours_distribution"]     = equity_data.get("hours_distribution")
    return result
