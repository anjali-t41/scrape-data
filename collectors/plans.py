"""
Count plan files in plans/ directories across all .claude* dirs.

Plans are created when a developer uses Plan mode — a strong harness signal.
"""

import os
from pathlib import Path


def collect(developer_map: list[dict], since_mtime: float | None = None) -> dict[str, dict]:
    """
    Return {developer_key: {total_plans, new_plans, plan_names}}.
    new_plans counts files created after since_mtime (unix timestamp).
    """
    results: dict[str, dict] = {}

    for dev in developer_map:
        key = dev["developer_key"]
        total = 0
        new_count = 0
        names: list[str] = []

        for claude_dir_str in dev["claude_dirs"]:
            plans_dir = Path(claude_dir_str) / "plans"
            if not plans_dir.exists():
                continue

            for f in plans_dir.glob("*.md"):
                total += 1
                names.append(f.stem)
                if since_mtime and f.stat().st_mtime > since_mtime:
                    new_count += 1

        results[key] = {
            "developer_key": key,
            "total_plans": total,
            "new_plans_since_last_run": new_count,
            "plan_names": names,
        }

    return results
