"""
Parse agent-name, queue-operation, and ai-title messages from session JSONL files.

Provides per-session:
  - ai_title       : AI-generated session title (last seen value)
  - agent_names    : unique agent names seen (from agent-name messages)
  - tasks          : list of agent task records (from queue-operation enqueue messages)

Each task record contains:
  task_id, agent_name, task_description, status, enqueued_at, week
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


_SUMMARY_RE     = re.compile(r'Agent "([^"]+)"')
_TASK_ID_RE     = re.compile(r'<task-id>([^<]+)</task-id>')
_STATUS_RE      = re.compile(r'<status>([^<]+)</status>')
_SUMMARY_TAG_RE = re.compile(r'<summary>(.*?)</summary>', re.DOTALL)


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _week_label(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _parse_queue_content(content: str) -> dict:
    """Extract task_id, agent_name, task_description, status from <task-notification> content."""
    task_id = ""
    status  = ""
    agent_name = ""
    task_description = ""

    m = _TASK_ID_RE.search(content)
    if m:
        task_id = m.group(1).strip()

    m = _STATUS_RE.search(content)
    if m:
        status = m.group(1).strip()

    m = _SUMMARY_TAG_RE.search(content)
    if m:
        summary_text = m.group(1).strip()
        am = _SUMMARY_RE.search(summary_text)
        if am:
            label = am.group(1)
            if ": " in label:
                agent_name, task_description = label.split(": ", 1)
            else:
                agent_name = label

    return {
        "task_id":          task_id or None,
        "agent_name":       agent_name or None,
        "task_description": task_description or None,
        "status":           status or None,
    }


def _process_jsonl(path: Path, developer_key: str) -> dict:
    """
    Parse one session JSONL.
    Returns {session_id, developer_key, ai_title, agent_names, tasks} or {}.
    """
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return {}

    session_id = path.stem
    ai_title: str | None = None
    agent_names_seen: list[str] = []
    tasks: list[dict] = []

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

        if mtype == "ai-title":
            title = msg.get("aiTitle", "").strip()
            if title:
                ai_title = title  # keep latest

        elif mtype == "agent-name":
            name = msg.get("agentName", "").strip()
            if name and name not in agent_names_seen:
                agent_names_seen.append(name)

        elif mtype == "queue-operation" and msg.get("operation") == "enqueue":
            content = msg.get("content", "")
            if not content:
                continue
            parsed = _parse_queue_content(content)
            ts_raw = msg.get("timestamp", "")
            ts_dt  = _parse_iso(ts_raw)
            parsed.update({
                "enqueued_at": ts_raw or None,
                "week":        _week_label(ts_dt) if ts_dt else None,
            })
            if parsed.get("agent_name") or parsed.get("task_id"):
                tasks.append(parsed)

    # Include agent-name-only entries not already captured by queue-operation records
    task_names = {t["agent_name"] for t in tasks if t.get("agent_name")}
    for name in agent_names_seen:
        if name not in task_names:
            tasks.append({
                "task_id":          None,
                "agent_name":       name,
                "task_description": None,
                "status":           None,
                "enqueued_at":      None,
                "week":             None,
            })

    if not ai_title and not agent_names_seen and not tasks:
        return {}

    return {
        "session_id":    session_id,
        "developer_key": developer_key,
        "ai_title":      ai_title,
        "agent_names":   agent_names_seen,
        "tasks":         tasks,
    }


def collect(
    developer_map: list[dict],
    processed_sessions: set[str] | None = None,
    since: datetime | None = None,
) -> dict[str, dict]:
    """
    Parse JSONL files for agent metadata across all claude dirs.

    processed_sessions: session_ids already stored — skip for incremental push.
    Returns {session_id: {session_id, developer_key, ai_title, agent_names, tasks}}.
    """
    processed_sessions = processed_sessions or set()
    results: dict[str, dict] = {}

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
                    data = _process_jsonl(jsonl_file, key)
                    if data:
                        results[session_id] = data

    return results
