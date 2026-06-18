"""
Parse session JSONL files across all .claude* directories.

Extracts per-turn events needed for:
  - Agent hours (M3): user_ts → assistant_ts gap per turn
  - Parallel agents (M4): isSidechain, agentColor per message
  - Skills (M7): system/local_command messages with slash commands
  - Trust (M8): permissionMode per message

Output: list of turn event dicts.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


_SKILL_RE = re.compile(r"<command-name>(/[^<]+)</command-name>")


def _extract_user_text(msg: dict) -> str:
    """Extract plain text from a user message's content field."""
    content = msg.get("message", {}).get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _extract_command(content: str) -> str | None:
    m = _SKILL_RE.search(content)
    return m.group(1) if m else None


def _process_jsonl(path: Path, developer_key: str) -> list[dict]:
    """Parse one session JSONL file. Returns turn events."""
    events = []
    pending_user: dict | None = None
    session_id = None
    agent_colors: set[str] = set()

    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue

        mtype = msg.get("type", "")
        session_id = session_id or msg.get("sessionId", path.stem)

        # Track agent colors (each color = distinct parallel agent stream)
        if mtype == "agent-color":
            color = msg.get("agentColor")
            if color:
                agent_colors.add(color)
            continue

        ts_raw = msg.get("timestamp")
        ts = _parse_iso(ts_raw) if ts_raw else None
        is_sidechain = bool(msg.get("isSidechain", False))
        permission_mode = msg.get("permissionMode")

        if mtype == "user":
            pending_user = {
                "ts": ts,
                "permission_mode": permission_mode,
                "is_sidechain": is_sidechain,
                "prompt_text": _extract_user_text(msg),
            }

        elif mtype == "assistant" and pending_user is not None:
            user_ts = pending_user["ts"]
            agent_ms = None
            if user_ts and ts:
                diff = (ts - user_ts).total_seconds() * 1000
                # Sanity: ignore negative gaps or gaps > 10 minutes (idle time)
                if 0 < diff < 600_000:
                    agent_ms = round(diff, 1)

            # Extract tool use counts from assistant message content
            tool_uses = []
            content_blocks = msg.get("message", {}).get("content", [])
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses.append(block.get("name", ""))

            events.append({
                "session_id":    session_id,
                "developer_key": developer_key,
                "user_ts":       user_ts.isoformat() if user_ts else None,
                "assistant_ts":  ts.isoformat() if ts else None,
                "agent_ms":      agent_ms,
                "is_sidechain":  pending_user["is_sidechain"] or is_sidechain,
                "permission_mode": pending_user["permission_mode"] or permission_mode,
                "tool_uses":     tool_uses,
                "prompt_text":   pending_user["prompt_text"],
            })
            pending_user = None

        elif mtype == "system":
            subtype = msg.get("subtype", "")
            content = msg.get("content", "")
            if subtype == "local_command" and isinstance(content, str):
                command = _extract_command(content)
                if command:
                    events.append({
                        "session_id": session_id,
                        "developer_key": developer_key,
                        "event_type": "skill",
                        "command": command,
                        "ts": ts.isoformat() if ts else None,
                        "is_sidechain": is_sidechain,
                    })

    # Attach agent_colors count to all events from this session
    for e in events:
        e.setdefault("agent_colors_in_session", len(agent_colors))

    return events


def collect(
    developer_map: list[dict],
    processed_sessions: set[str] | None = None,
    since: datetime | None = None,
) -> list[dict]:
    """
    Parse JSONL session files across all claude dirs.
    Skips session_ids already in processed_sessions (incremental).
    """
    processed_sessions = processed_sessions or set()
    all_events = []

    for dev in developer_map:
        key = dev["developer_key"]
        for claude_dir_str in dev["claude_dirs"]:
            claude_dir = Path(claude_dir_str)
            projects_dir = claude_dir / "projects"
            if not projects_dir.exists():
                continue

            for project_dir in projects_dir.iterdir():
                if not project_dir.is_dir():
                    continue
                for jsonl_file in project_dir.glob("*.jsonl"):
                    session_id = jsonl_file.stem
                    if session_id in processed_sessions:
                        continue
                    if since:
                        mtime = datetime.fromtimestamp(
                            jsonl_file.stat().st_mtime, tz=timezone.utc
                        )
                        if mtime < since:
                            continue
                    events = _process_jsonl(jsonl_file, key)
                    all_events.extend(events)

    return all_events
