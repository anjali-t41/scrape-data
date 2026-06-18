"""
Parse usage-data/facets/*.json files — AI-analyzed session outcomes.

Output: dict keyed by session_id.
"""

import json
from pathlib import Path


def collect(developer_map: list[dict]) -> dict[str, dict]:
    """Return {session_id: facets_dict} across all claude dirs."""
    results: dict[str, dict] = {}

    for dev in developer_map:
        for claude_dir_str in dev["claude_dirs"]:
            claude_dir = Path(claude_dir_str)
            facets_dir = claude_dir / "usage-data" / "facets"
            if not facets_dir.exists():
                continue

            for f in facets_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                except Exception:
                    continue

                session_id = data.get("session_id", f.stem)
                if session_id in results:
                    continue

                results[session_id] = {
                    "session_id": session_id,
                    "underlying_goal": data.get("underlying_goal"),
                    "goal_categories": data.get("goal_categories", {}),
                    "outcome": data.get("outcome"),
                    "session_type": data.get("session_type"),
                    "claude_helpfulness": data.get("claude_helpfulness"),
                    "friction_counts": data.get("friction_counts", {}),
                    "friction_detail": data.get("friction_detail", ""),
                    "primary_success": data.get("primary_success"),
                    "brief_summary": data.get("brief_summary"),
                    "developer_key": dev["developer_key"],
                }

    return results
