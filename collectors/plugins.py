"""
Parse installed_plugins.json across all .claude* directories.
"""

import json
from pathlib import Path


def collect(developer_map: list[dict]) -> dict[str, dict]:
    """Return {developer_key: {plugins: [...], plugin_count: int}}."""
    results: dict[str, dict] = {}

    for dev in developer_map:
        key = dev["developer_key"]
        all_plugins: dict[str, dict] = {}

        for claude_dir_str in dev["claude_dirs"]:
            plugins_json = Path(claude_dir_str) / "plugins" / "installed_plugins.json"
            if not plugins_json.exists():
                continue
            try:
                data = json.loads(plugins_json.read_text())
            except Exception:
                continue

            for plugin_key, entries in data.get("plugins", {}).items():
                if plugin_key not in all_plugins and entries:
                    entry = entries[0]
                    all_plugins[plugin_key] = {
                        "key": plugin_key,
                        "scope": entry.get("scope"),
                        "version": entry.get("version") or entry.get("gitCommitSha", "")[:8],
                        "installed_at": entry.get("installedAt"),
                        "last_updated": entry.get("lastUpdated"),
                    }

        results[key] = {
            "developer_key": key,
            "plugins": list(all_plugins.values()),
            "plugin_count": len(all_plugins),
        }

    return results
