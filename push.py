#!/usr/bin/env python3
"""
Per-machine push script.

Runs on each developer's machine. Collects raw data from local ~/.claude* dirs
and pushes it to the central SQLite store. Does NOT compute any metrics.

Usage:
  python push.py --central /shared/drive/central.db
  python push.py --central /shared/drive/central.db --since 7d
  python push.py --central /shared/drive/central.db --dry-run
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collectors import discover, session_meta, sessions, facets, app_state, plans, plugins, settings, agent_tasks
from central_store import CentralStore


def _parse_since(s: str) -> datetime:
    s = s.strip()
    if s.endswith("d"):
        return datetime.now(tz=timezone.utc) - timedelta(days=int(s[:-1]))
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def push(central_db, since: datetime, dry_run: bool) -> None:
    store = CentralStore(central_db)

    print(f"[push] Connecting to central store: {central_db}")
    print(f"[push] Period: since {since.date().isoformat()}")
    print(f"[push] Current store: {store.stats()}")

    # Discover local .claude* dirs
    developer_map = discover.build_developer_map()
    print(f"[push] Found {len(developer_map)} local developer account(s)")

    # Already-pushed sessions — skip them for incremental push
    already_pushed = store.pushed_session_ids()
    print(f"[push] {len(already_pushed)} sessions already in store (will skip)")

    # Collect raw data locally
    print("[push] Collecting session metadata...")
    raw_session_metas = session_meta.collect(developer_map, since=since)
    new_metas = [m for m in raw_session_metas if m["session_id"] not in already_pushed]
    print(f"[push]   {len(raw_session_metas)} total sessions, {len(new_metas)} new")

    print("[push] Parsing JSONL transcripts for new sessions...")
    raw_turn_events = sessions.collect(
        developer_map,
        processed_sessions=already_pushed,
        since=since,
    )
    print(f"[push]   {len(raw_turn_events)} turn events")

    print("[push] Collecting facets, app state, plans, agent tasks...")
    raw_facets       = facets.collect(developer_map)
    raw_app_state    = app_state.collect(developer_map)
    raw_plans        = plans.collect(developer_map)
    already_at       = store.pushed_agent_session_ids()
    raw_agent_tasks  = agent_tasks.collect(developer_map, processed_sessions=already_at, since=since)
    plugins.collect(developer_map)
    settings.collect(developer_map)

    task_count = sum(len(v.get("tasks", [])) for v in raw_agent_tasks.values())
    print(f"[push]   {len(raw_agent_tasks)} sessions with agent activity, {task_count} tasks")

    raw = {
        "session_metas": new_metas,
        "turn_events":   raw_turn_events,
        "facets":        raw_facets,
        "app_state":     raw_app_state,
        "plans":         raw_plans,
        "agent_tasks":   raw_agent_tasks,
    }

    if dry_run:
        print(f"[push] DRY RUN — would push:")
        print(f"  session_metas : {len(new_metas)}")
        print(f"  turn_events   : {len(raw_turn_events)}")
        print(f"  facets        : {len(raw_facets)}")
        print(f"  app_state     : {len(raw_app_state)}")
        print(f"  plans         : {len(raw_plans)}")
        store.close()
        return

    inserted = store.push(raw)
    store.close()

    print("[push] Done.")
    print(f"  session_metas inserted : {inserted['session_metas']}")
    print(f"  turn_events inserted   : {inserted['turn_events']}")
    print(f"  facets inserted        : {inserted['facets']}")
    print(f"  app_state upserted     : {inserted['app_state']}")
    print(f"  plans upserted         : {inserted['plans']}")
    print(f"  agent_tasks inserted   : {inserted['agent_tasks']}")


def main():
    parser = argparse.ArgumentParser(description="Push local Claude data to central store")
    parser.add_argument("--central", default=None,
                        help="SQLite path or PostgreSQL URL. "
                             "Defaults to POSTGRES_URL env var if set, else local SQLite.")
    parser.add_argument("--since", default="7d",
                        help="Collect sessions since this period (default: 7d)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be pushed without writing")
    args = parser.parse_args()

    target = args.central or os.environ.get("POSTGRES_URL")
    if not target:
        print("Error: provide --central <path/url> or set POSTGRES_URL env var")
        raise SystemExit(1)

    push(
        central_db=target,
        since=_parse_since(args.since),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
