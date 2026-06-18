"""
Parse ~/.claude*/.claude.json root-level app state files.

Provides: numStartups, hasUsedBackgroundTask, installMethod, feature flags.
"""

import json
from pathlib import Path


def collect(developer_map: list[dict]) -> dict[str, dict]:
    """Return {developer_key: aggregated_app_state}."""
    results: dict[str, dict] = {}

    for dev in developer_map:
        key = dev["developer_key"]
        agg = {
            "developer_key": key,
            "total_startups": 0,
            "has_used_background_task": False,
            "install_methods": set(),
            "accounts": [],
        }

        for claude_dir_str in dev["claude_dirs"]:
            claude_dir = Path(claude_dir_str)
            claude_json = claude_dir / ".claude.json"
            if not claude_json.exists():
                continue
            try:
                data = json.loads(claude_json.read_text())
            except Exception:
                continue

            startups = data.get("numStartups", 0)
            agg["total_startups"] += startups
            if data.get("hasUsedBackgroundTask"):
                agg["has_used_background_task"] = True
            method = data.get("installMethod")
            if method:
                agg["install_methods"].add(method)

            agg["accounts"].append({
                "dir": str(claude_dir),
                "startups": startups,
                "has_background_task": bool(data.get("hasUsedBackgroundTask")),
            })

        agg["install_methods"] = list(agg["install_methods"])
        results[key] = agg

    return results


