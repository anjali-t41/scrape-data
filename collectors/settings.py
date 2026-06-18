"""
Parse settings.json across all .claude* directories.

Extracts: configured hooks, permission modes, MCP servers, enabled plugins.
"""

import json
from pathlib import Path


def collect(developer_map: list[dict]) -> dict[str, dict]:
    """Return {developer_key: settings_summary}."""
    results: dict[str, dict] = {}

    for dev in developer_map:
        key = dev["developer_key"]
        hook_events: set[str] = set()
        has_mcp = False
        has_status_line = False
        enabled_plugins: set[str] = set()
        permission_rules: list[dict] = []

        for claude_dir_str in dev["claude_dirs"]:
            for settings_file in [
                Path(claude_dir_str) / "settings.json",
                Path(claude_dir_str) / "remote-settings.json",
            ]:
                if not settings_file.exists():
                    continue
                try:
                    data = json.loads(settings_file.read_text())
                except Exception:
                    continue

                # Hooks configured
                for event in data.get("hooks", {}).keys():
                    hook_events.add(event)

                # MCP servers
                if data.get("mcpServers"):
                    has_mcp = True

                # Status line
                if data.get("statusLine"):
                    has_status_line = True

                # Enabled plugins
                for plugin_key in data.get("enabledPlugins", {}).keys():
                    enabled_plugins.add(plugin_key)

                # Permission allow/deny rules
                for allow in data.get("permissions", {}).get("allow", []):
                    permission_rules.append({"type": "allow", "rule": allow})
                for deny in data.get("permissions", {}).get("deny", []):
                    permission_rules.append({"type": "deny", "rule": deny})

        results[key] = {
            "developer_key": key,
            "configured_hook_events": sorted(hook_events),
            "hook_count": len(hook_events),
            "has_mcp_configured": has_mcp,
            "has_status_line": has_status_line,
            "enabled_plugins": sorted(enabled_plugins),
            "permission_rules": permission_rules,
        }

    return results
