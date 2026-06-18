"""
Parse usage-data/session-meta/*.json files across all .claude* directories.

Output: flat list of session meta dicts, each annotated with developer_key and account_type.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _account_type(claude_dir: Path) -> str:
    """
    Heuristic: directory name contains 'work' → work, 'personal' → personal,
    default .claude → primary.
    """
    name = claude_dir.name.lower()
    if "work" in name:
        return "work"
    if "personal" in name:
        return "personal"
    if name == ".claude":
        return "primary"
    return "other"


def _parse_one(path: Path, developer_key: str, claude_dir: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None

    session_id = data.get("session_id", path.stem)
    start_raw = data.get("start_time", "")
    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        week = start_dt.isocalendar()
        week_label = f"{week.year}-W{week.week:02d}"
        date_label = start_dt.date().isoformat()
    except Exception:
        start_dt = None
        week_label = None
        date_label = None

    return {
        "session_id": session_id,
        "developer_key": developer_key,
        "claude_dir": str(claude_dir),
        "account_type": _account_type(claude_dir),
        "project_path": data.get("project_path"),
        "start_time": start_raw,
        "start_dt": start_dt,
        "week": week_label,
        "date": date_label,
        "duration_minutes": data.get("duration_minutes", 0),
        "user_message_count": data.get("user_message_count", 0),
        "assistant_message_count": data.get("assistant_message_count", 0),
        "tool_counts": data.get("tool_counts", {}),
        "languages": data.get("languages", {}),
        "lines_added": data.get("lines_added", 0),
        "lines_removed": data.get("lines_removed", 0),
        "files_modified": data.get("files_modified", 0),
        "git_commits": data.get("git_commits", 0),
        "git_pushes": data.get("git_pushes", 0),
        "first_prompt": data.get("first_prompt", ""),
        "user_interruptions": data.get("user_interruptions", 0),
        "user_response_times": data.get("user_response_times", []),
        "tool_errors": data.get("tool_errors", 0),
        "uses_task_agent": data.get("uses_task_agent", False),
        "uses_mcp": data.get("uses_mcp", False),
        "uses_web_search": data.get("uses_web_search", False),
        "uses_web_fetch": data.get("uses_web_fetch", False),
        "input_tokens": data.get("input_tokens", 0),
        "output_tokens": data.get("output_tokens", 0),
    }


def collect(developer_map: list[dict], since: datetime | None = None) -> list[dict]:
    """
    Collect all session-meta records across all claude dirs in the developer_map.
    Optionally filter to sessions starting after `since`.
    """
    results = []
    seen_session_ids: set[str] = set()

    for dev in developer_map:
        key = dev["developer_key"]
        for claude_dir_str in dev["claude_dirs"]:
            claude_dir = Path(claude_dir_str)
            meta_dir = claude_dir / "usage-data" / "session-meta"
            if not meta_dir.exists():
                continue

            for f in meta_dir.glob("*.json"):
                record = _parse_one(f, key, claude_dir)
                if record is None:
                    continue
                if record["session_id"] in seen_session_ids:
                    continue
                if since and record["start_dt"] and record["start_dt"] < since:
                    continue
                seen_session_ids.add(record["session_id"])
                results.append(record)

    return results
