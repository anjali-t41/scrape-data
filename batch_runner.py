#!/usr/bin/env python3
"""
Batch runner — orchestrates full metric computation pipeline.

Single-machine mode (default):
  python batch_runner.py --since 7d --report

Distributed mode — read from central store instead of local files:
  python batch_runner.py --from-store /shared/central.db --since 7d --report

All-weeks mode (score every week found in the data):
  python batch_runner.py --from-store $POSTGRES_URL --since 90d --all-weeks --report

Other options:
  --output /tmp/out.json   custom output path
  --team-size 15           total developer count for adoption %
  --week 2026-W25          score a specific ISO week
  --daily                  fast daily update (no JSONL parsing, single-machine only)
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collectors import discover, session_meta, sessions, facets, app_state, plans, plugins, settings, agent_tasks
from computers import (
    adoption, agent_hours, parallel_agents, depth,
    harness, skills, trust, outcomes, velocity, composite,
    consistency, equity,
)
from metrics_store import MetricsStore
from central_store import CentralStore


def _parse_since(since_str: str) -> datetime:
    since_str = since_str.strip()
    if since_str.endswith("d"):
        days = int(since_str[:-1])
        return datetime.now(tz=timezone.utc) - timedelta(days=days)
    return datetime.fromisoformat(since_str).replace(tzinfo=timezone.utc)


def _current_week() -> str:
    now = datetime.now(tz=timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _collect(developer_map: list[dict], since: datetime, store: MetricsStore, daily_only: bool) -> dict:
    """Collect all raw data in one pass. Every computer draws from this dict."""
    since_mtime = store.last_run_dt("weekly")
    since_mtime = since_mtime.timestamp() if since_mtime else None

    print("[batch] Collecting session metadata...")
    raw_session_metas = session_meta.collect(developer_map, since=since)
    print(f"[batch]   {len(raw_session_metas)} sessions in period")

    print("[batch] Collecting facets, app state, plans, plugins, settings...")
    raw_facets    = facets.collect(developer_map)
    raw_app_state = app_state.collect(developer_map)
    raw_plans     = plans.collect(developer_map, since_mtime=since_mtime)
    plugins.collect(developer_map)
    settings.collect(developer_map)

    raw_turn_events: list[dict] = []
    raw_agent_tasks: dict = {}
    if not daily_only:
        print("[batch] Parsing session transcripts (JSONL)...")
        processed = store.processed_sessions()
        raw_turn_events = sessions.collect(developer_map, processed_sessions=processed, since=since)
        raw_agent_tasks = agent_tasks.collect(developer_map, processed_sessions=processed, since=since)
        print(f"[batch]   {len(raw_turn_events)} turn events, "
              f"{sum(len(v.get('tasks',[])) for v in raw_agent_tasks.values())} agent tasks extracted")
        store.mark_sessions_processed(list({e["session_id"] for e in raw_turn_events}))

    return {
        "session_metas": raw_session_metas,
        "turn_events":   raw_turn_events,
        "facets":        raw_facets,
        "app_state":     raw_app_state,
        "plans":         raw_plans,
        "agent_tasks":   raw_agent_tasks,
    }


def _compute(raw: dict, team_size: int | None, week: str, store: MetricsStore) -> tuple[dict, dict]:
    """
    Run all computers once. Returns (metrics, sessions_by_dev).

    Indexes are built here — one pass per source list — so no computer
    re-iterates the full session_metas or turn_events list on its own.
    """
    from collections import defaultdict

    sm = raw["session_metas"]
    te = raw["turn_events"]

    # ── One pass over session_metas ───────────────────────────────────────
    sessions_by_dev: dict = defaultdict(list)
    meta_by_sid: dict = {}
    for m in sm:
        sessions_by_dev[m["developer_key"]].append(m)
        meta_by_sid[m["session_id"]] = m

    # ── One pass over turn_events ─────────────────────────────────────────
    turns_by_session: dict = defaultdict(list)
    skill_events: list = []
    for t in te:
        turns_by_session[t.get("session_id", "")].append(t)
        if t.get("event_type") == "skill":
            skill_events.append(t)

    # ── All computers receive pre-built indexes, not raw lists ────────────
    hours = agent_hours.compute(te, sessions_by_dev)

    metrics = {
        "adoption":        adoption.compute(sessions_by_dev, total_developers=team_size),
        "agent_hours":     hours,
        "parallel_agents": parallel_agents.compute(te, meta_by_sid, raw.get("agent_tasks", {})),
        "depth":           depth.compute(sessions_by_dev),
        "harness":         harness.compute(sessions_by_dev, raw["plans"], raw["app_state"]),
        "skills":          skills.compute(skill_events),
        "trust":           trust.compute(sessions_by_dev, turns_by_session),
        "outcomes":        outcomes.compute(raw["facets"], meta_by_sid),
        "velocity":        velocity.compute(sessions_by_dev, hours),
        "consistency":     consistency.compute(sessions_by_dev),
        "equity":          equity.compute(
                               developer_scores=[],
                               agent_hours_results=hours,
                               week=week,
                               weekly_history=store.read_weekly_history(),
                           ),
    }
    return metrics, dict(sessions_by_dev)


def _all_weeks_in_data(session_metas: list) -> list[str]:
    """Return sorted list of distinct ISO weeks present in session_metas."""
    weeks: set[str] = set()
    for s in session_metas:
        ts = s.get("start_time")
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                iso = dt.isocalendar()
                weeks.add(f"{iso.year}-W{iso.week:02d}")
            except Exception:
                pass
    return sorted(weeks)


def _pull_raw(since: datetime, store: MetricsStore, daily_only: bool, central_db) -> tuple[dict, dict]:
    """Return (raw, dev_name_map). Shared by run() and run_all_weeks()."""
    if central_db:
        print(f"[batch] Reading from central store: {central_db}")
        print(f"[batch] Period: since {since.date().isoformat()}")
        cs = CentralStore(central_db)
        raw = cs.pull_raw(since=since)
        cs.close()
        print(f"[batch]   {len(raw['session_metas'])} sessions, "
              f"{len(raw['turn_events'])} turn events from store")
        return raw, {}
    else:
        print(f"[batch] Starting {'daily' if daily_only else 'weekly'} run")
        print(f"[batch] Period: since {since.date().isoformat()}")
        developer_map = discover.build_developer_map()
        print(f"[batch]   Found {len(developer_map)} developer(s)")
        raw = _collect(developer_map, since, store, daily_only)
        dev_name_map = {d["developer_key"]: d.get("name") or d["developer_key"][:12]
                        for d in developer_map}
        return raw, dev_name_map


def _score_week(week: str, metrics: dict, sessions_by_dev: dict, dev_name_map: dict, store: MetricsStore) -> dict:
    """Compute per-developer and team composite scores for one ISO week."""
    developer_scores = []
    for key in sessions_by_dev:
        score = composite.compute(
            developer_key    = key,
            adoption_data    = metrics["adoption"]["developers"].get(key, {}),
            agent_hours_data = metrics["agent_hours"].get(key, {}),
            parallel_data    = metrics["parallel_agents"].get(key, {}),
            depth_data       = metrics["depth"].get(key, {}),
            harness_data     = metrics["harness"].get(key, {}),
            trust_data       = metrics["trust"].get(key, {}),
            outcomes_data    = metrics["outcomes"].get(key, {}),
            velocity_data    = metrics["velocity"].get(key, {}),
            consistency_data = metrics["consistency"].get(key, {}),
            week             = week,
        )
        score["name"]               = dev_name_map.get(key, key[:12])
        score["agent_hours_week"]   = metrics["agent_hours"].get(key, {}).get("by_week", {}).get(week, {}).get("agent_hours", 0.0)
        score["agent_hours_status"] = metrics["agent_hours"].get(key, {}).get("by_week", {}).get(week, {}).get("status", "unknown")
        developer_scores.append(score)

    equity_data = equity.compute(
        developer_scores    = developer_scores,
        agent_hours_results = metrics["agent_hours"],
        week                = week,
        weekly_history      = store.read_weekly_history(),
    )
    team_score = composite.team_composite(developer_scores, equity_data=equity_data)

    return {
        "week": week,
        "team": {
            **team_score,
            "adoption":    metrics["adoption"]["team"],
            "agent_hours": agent_hours.team_summary(metrics["agent_hours"], week),
            "velocity":    velocity.team_summary(metrics["velocity"]),
            "skills":      skills.team_summary(metrics["skills"], week),
        },
        "developers": sorted(developer_scores, key=lambda d: d["ai_native_score"], reverse=True),
    }


def run(
    since: datetime,
    team_size: int | None,
    target_week: str | None,
    output_path: Path | None,
    daily_only: bool,
    store: MetricsStore,
    central_db: Path | None = None,
) -> dict:
    raw, dev_name_map = _pull_raw(since, store, daily_only, central_db)
    if target_week:
        week = target_week
    else:
        weeks_found = _all_weeks_in_data(raw["session_metas"])
        week = weeks_found[-1] if weeks_found else _current_week()
        print(f"[batch] No --week specified; using most recent week with data: {week}")

    metrics, sessions_by_dev = _compute(raw, team_size, week, store)
    weekly_payload = _score_week(week, metrics, sessions_by_dev, dev_name_map, store)

    payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "period_since": since.isoformat(),
        **weekly_payload,
        "raw": {
            "session_count": len(raw["session_metas"]),
            "turn_events":   len(raw["turn_events"]),
            "facet_count":   len(raw["facets"]),
        },
    }

    out_path = store.write_output(payload, output_path)
    store.append_weekly_snapshot({"week": week, "team_score": payload["team"].get("team_ai_native_score")})
    store.mark_run_complete("daily" if daily_only else "weekly")

    print(f"[batch] Done. Output → {out_path}")
    print(f"[batch] Team AI Native Score: {payload['team'].get('team_ai_native_score')} ({payload['team'].get('label')})")
    return payload


def run_all_weeks(
    since: datetime,
    team_size: int | None,
    output_path: Path | None,
    store: MetricsStore,
    central_db: Path | None = None,
) -> list[dict]:
    """Compute metrics for every distinct week present in the pulled data."""
    raw, dev_name_map = _pull_raw(since, store, daily_only=False, central_db=central_db)

    weeks = _all_weeks_in_data(raw["session_metas"])
    if not weeks:
        print("[batch] No sessions found in the specified period.")
        return []

    print(f"[batch] Found {len(weeks)} week(s): {', '.join(weeks)}")

    # Run computers once — they produce by_week breakdowns internally
    metrics, sessions_by_dev = _compute(raw, team_size, weeks[-1], store)

    week_payloads: list[dict] = []
    for week in weeks:
        wp = _score_week(week, metrics, sessions_by_dev, dev_name_map, store)
        week_payloads.append(wp)
        store.append_weekly_snapshot({"week": week, "team_score": wp["team"].get("team_ai_native_score")})
        print(f"[batch]   {week}: score {wp['team'].get('team_ai_native_score')} ({wp['team'].get('label')})")

    full_output = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "period_since": since.isoformat(),
        "weeks": week_payloads,
        "raw": {
            "session_count": len(raw["session_metas"]),
            "turn_events":   len(raw["turn_events"]),
            "facet_count":   len(raw["facets"]),
        },
    }

    out_path = store.write_output(full_output, output_path)
    store.mark_run_complete("weekly")
    print(f"[batch] Done. Output → {out_path}")
    return week_payloads


def print_report(payload: dict) -> None:
    team = payload.get("team", {})
    devs = payload.get("developers", [])
    week = payload.get("week", "")

    print()
    print("=" * 62)
    print(f"  AI NATIVENESS REPORT — {week}")
    print("=" * 62)
    print(f"  AI Native Score     {team.get('team_ai_native_score'):>6}  {team.get('label','')}")
    print(f"  Team Adoption       {team.get('adoption',{}).get('adoption_index',0):>5}%  ({team.get('adoption',{}).get('active_developers','?')}/{team.get('adoption',{}).get('total_developers','?')} devs active)")
    print(f"  Avg Agent Hours/Dev {team.get('agent_hours',{}).get('avg_agent_hours',0):>6.1f}  (target: 80 hrs/week)")
    print(f"  Team Velocity       {team.get('velocity',{}).get('team_velocity',0):>6.0f}  lines / agent hour")
    print(f"  Skill Invocations   {team.get('skills',{}).get('total_invocations',0):>6}")
    print()
    print(f"  {'Developer':<20} {'Score':>6} {'AgentHrs':>9} {'Status':<15}")
    print("  " + "-" * 54)
    for d in devs:
        flag = " ← needs attention" if d.get("agent_hours_status") == "stuck" else ""
        print(f"  {str(d.get('name','?')):<20} {d['ai_native_score']:>6.1f} {d.get('agent_hours_week',0):>8.1f}h  {d.get('agent_hours_status',''):<15}{flag}")
    print("=" * 62)
    print()


def print_all_weeks_report(week_payloads: list[dict]) -> None:
    if not week_payloads:
        print("\n[batch] No data to report.\n")
        return

    print()
    print("=" * 62)
    print("  AI NATIVENESS REPORT — ALL WEEKS")
    print("=" * 62)
    print(f"  {'Week':<12} {'Score':>6}  {'Label':<15} {'AvgAgentHrs':>12}")
    print("  " + "-" * 50)
    for wp in week_payloads:
        team = wp.get("team", {})
        print(
            f"  {wp.get('week',''):<12} "
            f"{team.get('team_ai_native_score', 0.0):>6.1f}  "
            f"{team.get('label', ''):<15} "
            f"{team.get('agent_hours', {}).get('avg_agent_hours', 0.0):>11.1f}h"
        )
    print("=" * 62)
    print()

    for wp in week_payloads:
        print_report(wp)


def main():
    parser = argparse.ArgumentParser(description="AI Nativeness Metrics Batch Runner")
    parser.add_argument("--since", default=None,
                        help="Period to analyse, e.g. 7d, 30d (default: 7d; 365d when --all-weeks)")
    parser.add_argument("--week", default=None, help="ISO week to score, e.g. 2026-W25")
    parser.add_argument("--all-weeks", action="store_true",
                        help="Score every week found in the data (overrides --week)")
    parser.add_argument("--team-size", type=int, default=None, help="Total developer count for adoption pct")
    parser.add_argument("--output", type=Path, default=None, help="Custom output JSON path")
    parser.add_argument("--store-dir", type=Path, default=None, help="Metrics store directory")
    parser.add_argument("--daily", action="store_true", help="Fast daily run (skip JSONL parsing, single-machine only)")
    parser.add_argument("--report", action="store_true", help="Print human-readable report after run")
    parser.add_argument("--from-store", default=None, metavar="DB_PATH_OR_URL",
                        help="Read from central store: SQLite path or PostgreSQL URL. "
                             "Also reads POSTGRES_URL env var.")
    args = parser.parse_args()

    import os
    default_since = "365d" if args.all_weeks else "7d"
    since      = _parse_since(args.since or default_since)
    store      = MetricsStore(store_dir=args.store_dir)
    central_db = args.from_store or os.environ.get("POSTGRES_URL")

    if args.all_weeks:
        week_payloads = run_all_weeks(
            since=since,
            team_size=args.team_size,
            output_path=args.output,
            store=store,
            central_db=central_db,
        )
        if args.report:
            print_all_weeks_report(week_payloads)
    else:
        payload = run(
            since=since,
            team_size=args.team_size,
            target_week=args.week,
            output_path=args.output,
            daily_only=args.daily,
            store=store,
            central_db=central_db,
        )
        if args.report:
            print_report(payload)


if __name__ == "__main__":
    main()
