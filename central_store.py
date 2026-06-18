"""
Central store for raw collected data.

Supports two backends — detected automatically from the connection string:
  SQLite   : pass a Path  e.g. Path("/shared/central.db")
  PostgreSQL: pass a URL  e.g. "postgresql://user:pass@host:5432/dbname"

The public interface (push / pull_raw / pushed_session_ids / stats / close)
is identical for both backends, so push.py and batch_runner.py are unchanged.

PostgreSQL uses a dedicated 'scrape_data' schema with properly typed columns.
SQLite uses a flat layout with JSON blobs (simpler for local use).

Environment variable shortcut:
  POSTGRES_URL=postgresql://...  python push.py --central $POSTGRES_URL
"""

import json
import os
from datetime import datetime, date, timezone
from pathlib import Path


def _dumps(obj) -> str:
    def _default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(f"Not JSON serializable: {type(o).__name__}")
    return json.dumps(obj, default=_default)


def CentralStore(db_path=None):
    """
    Factory — returns the right backend based on db_path type / value.

    db_path can be:
      - None                   → SQLite at ~/.claude-metrics/central.db
      - pathlib.Path           → SQLite at that path
      - str starting postgres  → PostgreSQL
      - str starting file://   → SQLite
      - other str              → treat as SQLite file path
    """
    if db_path is None:
        return _SQLiteStore(Path.home() / ".claude-metrics" / "central.db")

    if isinstance(db_path, Path):
        return _SQLiteStore(db_path)

    s = str(db_path)
    if s.startswith("postgresql://") or s.startswith("postgres://"):
        return _PostgresStore(s)
    if s.startswith("file://"):
        return _SQLiteStore(Path(s[7:]))

    # Any other string is treated as a file path
    return _SQLiteStore(Path(s))


# ── SQLite shared SQL (ANSI-compatible) ───────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS session_metas (
    session_id    TEXT PRIMARY KEY,
    developer_key TEXT NOT NULL,
    week          TEXT,
    date          TEXT,
    pushed_at     TEXT NOT NULL,
    data          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turn_events (
    session_id    TEXT PRIMARY KEY,
    developer_key TEXT NOT NULL,
    pushed_at     TEXT NOT NULL,
    data          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facets (
    session_id    TEXT PRIMARY KEY,
    developer_key TEXT,
    pushed_at     TEXT NOT NULL,
    data          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    developer_key TEXT PRIMARY KEY,
    pushed_at     TEXT NOT NULL,
    data          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id            TEXT PRIMARY KEY,
    developer_key TEXT NOT NULL,
    pushed_at     TEXT NOT NULL,
    data          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS developers (
    developer_key TEXT PRIMARY KEY,
    name          TEXT,
    email         TEXT,
    claude_dirs   TEXT,
    pushed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sm_dev  ON session_metas(developer_key);
CREATE INDEX IF NOT EXISTS idx_sm_week ON session_metas(week);
CREATE INDEX IF NOT EXISTS idx_sm_date ON session_metas(date);
CREATE INDEX IF NOT EXISTS idx_te_dev  ON turn_events(developer_key)
"""


# ── PostgreSQL scrape_data schema DDL ─────────────────────────────────────────

_PG_CREATE = """
CREATE SCHEMA IF NOT EXISTS scrape_data;

CREATE TABLE IF NOT EXISTS scrape_data.session_metas (
    session_id              TEXT PRIMARY KEY,
    developer_key           TEXT NOT NULL,
    claude_dir              TEXT,
    account_type            TEXT,
    project_path            TEXT,
    start_time              TIMESTAMPTZ,
    week                    TEXT,
    date                    DATE,
    duration_minutes        INTEGER,
    user_message_count      INTEGER,
    assistant_message_count INTEGER,
    lines_added             INTEGER DEFAULT 0,
    lines_removed           INTEGER DEFAULT 0,
    files_modified          INTEGER DEFAULT 0,
    git_commits             INTEGER DEFAULT 0,
    git_pushes              INTEGER DEFAULT 0,
    first_prompt            TEXT,
    user_interruptions      INTEGER DEFAULT 0,
    tool_errors             INTEGER DEFAULT 0,
    uses_task_agent         BOOLEAN DEFAULT FALSE,
    uses_mcp                BOOLEAN DEFAULT FALSE,
    uses_web_search         BOOLEAN DEFAULT FALSE,
    uses_web_fetch          BOOLEAN DEFAULT FALSE,
    input_tokens            INTEGER DEFAULT 0,
    output_tokens           INTEGER DEFAULT 0,
    tool_counts             JSONB DEFAULT '{}',
    languages               JSONB DEFAULT '{}',
    user_response_times     JSONB DEFAULT '[]',
    pushed_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_data.turn_events (
    id                      BIGSERIAL,
    session_id              TEXT NOT NULL,
    developer_key           TEXT NOT NULL,
    event_type              TEXT NOT NULL DEFAULT 'turn',
    user_ts                 TIMESTAMPTZ,
    assistant_ts            TIMESTAMPTZ,
    agent_ms                NUMERIC(12,1),
    is_sidechain            BOOLEAN DEFAULT FALSE,
    permission_mode         TEXT,
    tool_uses               JSONB DEFAULT '[]',
    agent_colors_in_session INTEGER DEFAULT 0,
    command                 TEXT,
    prompt_text             TEXT,
    pushed_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, id)
);

ALTER TABLE scrape_data.turn_events ADD COLUMN IF NOT EXISTS prompt_text TEXT;

CREATE TABLE IF NOT EXISTS scrape_data.facets (
    session_id          TEXT PRIMARY KEY,
    developer_key       TEXT,
    underlying_goal     TEXT,
    goal_categories     JSONB DEFAULT '{}',
    outcome             TEXT,
    session_type        TEXT,
    claude_helpfulness  TEXT,
    friction_counts     JSONB DEFAULT '{}',
    friction_detail     TEXT,
    primary_success     TEXT,
    brief_summary       TEXT,
    pushed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_data.app_state (
    developer_key            TEXT PRIMARY KEY,
    total_startups           INTEGER DEFAULT 0,
    has_used_background_task BOOLEAN DEFAULT FALSE,
    install_methods          JSONB DEFAULT '[]',
    accounts                 JSONB DEFAULT '[]',
    pushed_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_data.plans (
    developer_key            TEXT PRIMARY KEY,
    total_plans              INTEGER DEFAULT 0,
    new_plans_since_last_run INTEGER DEFAULT 0,
    plan_names               JSONB DEFAULT '[]',
    pushed_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE scrape_data.session_metas ADD COLUMN IF NOT EXISTS ai_title    TEXT;
ALTER TABLE scrape_data.session_metas ADD COLUMN IF NOT EXISTS agent_names JSONB DEFAULT '[]';

CREATE TABLE IF NOT EXISTS scrape_data.agent_tasks (
    id               BIGSERIAL PRIMARY KEY,
    session_id       TEXT NOT NULL,
    developer_key    TEXT NOT NULL,
    task_id          TEXT,
    agent_name       TEXT,
    task_description TEXT,
    status           TEXT,
    enqueued_at      TIMESTAMPTZ,
    week             TEXT,
    pushed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sm_dev   ON scrape_data.session_metas(developer_key);
CREATE INDEX IF NOT EXISTS idx_sm_week  ON scrape_data.session_metas(week);
CREATE INDEX IF NOT EXISTS idx_sm_date  ON scrape_data.session_metas(date);
CREATE INDEX IF NOT EXISTS idx_te_sid   ON scrape_data.turn_events(session_id);
CREATE INDEX IF NOT EXISTS idx_te_dev   ON scrape_data.turn_events(developer_key);
CREATE INDEX IF NOT EXISTS idx_te_etype ON scrape_data.turn_events(event_type);
CREATE INDEX IF NOT EXISTS idx_at_sid   ON scrape_data.agent_tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_at_dev   ON scrape_data.agent_tasks(developer_key);
CREATE INDEX IF NOT EXISTS idx_at_week  ON scrape_data.agent_tasks(week);
CREATE INDEX IF NOT EXISTS idx_at_name  ON scrape_data.agent_tasks(agent_name);

CREATE TABLE IF NOT EXISTS scrape_data.developers (
    developer_key TEXT PRIMARY KEY,
    name          TEXT,
    email         TEXT,
    claude_dirs   JSONB DEFAULT '[]',
    pushed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_SM_COLS = [
    "session_id", "developer_key", "claude_dir", "account_type", "project_path",
    "start_time", "week", "date", "duration_minutes", "user_message_count",
    "assistant_message_count", "lines_added", "lines_removed", "files_modified",
    "git_commits", "git_pushes", "first_prompt", "user_interruptions", "tool_errors",
    "uses_task_agent", "uses_mcp", "uses_web_search", "uses_web_fetch",
    "input_tokens", "output_tokens", "tool_counts", "languages", "user_response_times",
    "ai_title", "agent_names",
]

_TE_COLS = [
    "session_id", "developer_key", "event_type", "user_ts", "assistant_ts",
    "agent_ms", "is_sidechain", "permission_mode", "tool_uses",
    "agent_colors_in_session", "command", "prompt_text",
]

_F_COLS = [
    "session_id", "developer_key", "underlying_goal", "goal_categories",
    "outcome", "session_type", "claude_helpfulness", "friction_counts",
    "friction_detail", "primary_success", "brief_summary",
]


class _BaseStore:
    """Shared push / pull / stats logic for SQLite — backends supply _execute / _commit / _fetchall."""

    def push(self, raw: dict) -> dict:
        now = datetime.now(tz=timezone.utc).isoformat()
        inserted = {"session_metas": 0, "turn_events": 0, "facets": 0, "app_state": 0, "plans": 0}

        for meta in raw.get("session_metas", []):
            sid = meta.get("session_id")
            if not sid:
                continue
            n = self._upsert_ignore(
                "INSERT INTO session_metas (session_id, developer_key, week, date, pushed_at, data) "
                "VALUES ({p},{p},{p},{p},{p},{p})",
                (sid, meta.get("developer_key", ""), meta.get("week"), meta.get("date"), now, _dumps(meta)),
            )
            inserted["session_metas"] += n

        turns_by_session: dict[str, list] = {}
        for t in raw.get("turn_events", []):
            turns_by_session.setdefault(t.get("session_id", ""), []).append(t)

        for sid, turns in turns_by_session.items():
            dev_key = turns[0].get("developer_key", "") if turns else ""
            n = self._upsert_ignore(
                "INSERT INTO turn_events (session_id, developer_key, pushed_at, data) "
                "VALUES ({p},{p},{p},{p})",
                (sid, dev_key, now, _dumps(turns)),
            )
            inserted["turn_events"] += n

        for sid, f in raw.get("facets", {}).items():
            n = self._upsert_ignore(
                "INSERT INTO facets (session_id, developer_key, pushed_at, data) "
                "VALUES ({p},{p},{p},{p})",
                (sid, f.get("developer_key", ""), now, _dumps(f)),
            )
            inserted["facets"] += n

        for dev_key, state in raw.get("app_state", {}).items():
            n = self._upsert_replace(
                "app_state",
                {"developer_key": dev_key, "pushed_at": now, "data": _dumps(state)},
                conflict_col="developer_key",
            )
            inserted["app_state"] += n

        for dev_key, plan_info in raw.get("plans", {}).items():
            n = self._upsert_replace(
                "plans",
                {"id": dev_key, "developer_key": dev_key, "pushed_at": now, "data": _dumps(plan_info)},
                conflict_col="id",
            )
            inserted["plans"] += n

        self._commit()
        return inserted

    def upsert_developers(self, developer_map: list[dict]) -> int:
        import json as _json
        now = datetime.now(tz=timezone.utc).isoformat()
        count = 0
        for dev in developer_map:
            key = dev.get("developer_key")
            if not key:
                continue
            n = self._upsert_replace(
                "developers",
                {
                    "developer_key": key,
                    "name":          dev.get("name"),
                    "email":         dev.get("email"),
                    "claude_dirs":   _json.dumps(dev.get("claude_dirs", [])),
                    "pushed_at":     now,
                },
                conflict_col="developer_key",
            )
            count += n
        self._commit()
        return count

    def pushed_session_ids(self) -> set[str]:
        rows = self._fetchall("SELECT session_id FROM session_metas")
        return {r[0] for r in rows}

    def pushed_agent_session_ids(self) -> set[str]:
        return set()  # SQLite has no agent_tasks table — collect all sessions

    def pull_raw(self, since: datetime | None = None) -> dict:
        since_date = since.date().isoformat() if since else None

        if since_date:
            rows = self._fetchall(
                "SELECT data FROM session_metas WHERE date >= {p} OR date IS NULL",
                (since_date,),
            )
        else:
            rows = self._fetchall("SELECT data FROM session_metas")
        session_metas = [json.loads(r[0]) for r in rows]

        in_scope = {m["session_id"] for m in session_metas}
        turn_events: list[dict] = []
        facets: dict[str, dict] = {}

        if in_scope:
            ph = ",".join(["{p}"] * len(in_scope))
            args = tuple(in_scope)

            for r in self._fetchall(f"SELECT data FROM turn_events WHERE session_id IN ({ph})", args):
                turn_events.extend(json.loads(r[0]))

            for r in self._fetchall(f"SELECT session_id, data FROM facets WHERE session_id IN ({ph})", args):
                facets[r[0]] = json.loads(r[1])

        rows = self._fetchall("SELECT developer_key, data FROM app_state")
        app_state = {r[0]: json.loads(r[1]) for r in rows}

        rows = self._fetchall("SELECT developer_key, data FROM plans")
        plans = {r[0]: json.loads(r[1]) for r in rows}

        return {
            "session_metas": session_metas,
            "turn_events":   turn_events,
            "facets":        facets,
            "app_state":     app_state,
            "plans":         plans,
        }

    def stats(self) -> dict:
        return {
            "session_metas": self._fetchall("SELECT COUNT(*) FROM session_metas")[0][0],
            "turn_events":   self._fetchall("SELECT COUNT(*) FROM turn_events")[0][0],
            "facets":        self._fetchall("SELECT COUNT(*) FROM facets")[0][0],
            "app_state":     self._fetchall("SELECT COUNT(*) FROM app_state")[0][0],
            "plans":         self._fetchall("SELECT COUNT(*) FROM plans")[0][0],
            "developers":    self._fetchall(
                "SELECT COUNT(DISTINCT developer_key) FROM session_metas"
            )[0][0],
        }


# ── SQLite backend ────────────────────────────────────────────────────────────

class _SQLiteStore(_BaseStore):
    def __init__(self, db_path: Path):
        import sqlite3
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        for stmt in _CREATE_TABLES.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)
        self._conn.commit()

    def _fmt(self, sql: str) -> str:
        return sql.replace("{p}", "?")

    def _execute(self, sql: str, params=()):
        return self._conn.execute(self._fmt(sql), params)

    def _fetchall(self, sql: str, params=()):
        return self._execute(sql, params).fetchall()

    def _commit(self):
        self._conn.commit()

    def _upsert_ignore(self, sql: str, params) -> int:
        sql = "INSERT OR IGNORE " + sql.removeprefix("INSERT ").replace("{p}", "?")
        cur = self._conn.execute(sql, params)
        return cur.rowcount

    def _upsert_replace(self, table: str, row: dict, conflict_col: str) -> int:
        cols = ", ".join(row.keys())
        vals = tuple(row.values())
        ph   = ", ".join(["?"] * len(vals))
        cur  = self._conn.execute(
            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({ph})", vals
        )
        return cur.rowcount

    def close(self):
        self._conn.close()

    def stats(self) -> dict:
        return {**super().stats(), "backend": "sqlite", "db_path": str(self.db_path)}


# ── PostgreSQL backend (scrape_data schema) ───────────────────────────────────

class _PostgresStore:
    """
    PostgreSQL backend writing into the 'scrape_data' schema.
    All tables have properly typed columns instead of JSON blobs.
    """

    def __init__(self, url: str):
        try:
            import psycopg2
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL support. "
                "Install it with: pip install psycopg2-binary"
            )
        self._url = url
        self._conn = psycopg2.connect(url)
        self._conn.autocommit = False
        cur = self._conn.cursor()
        for stmt in _PG_CREATE.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        self._conn.commit()

    # ── Low-level helpers ─────────────────────────────────────────────────────

    def _execute(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def _fetchall(self, sql: str, params=()):
        return self._execute(sql, params).fetchall()

    def _commit(self):
        self._conn.commit()

    # ── push ──────────────────────────────────────────────────────────────────

    def push(self, raw: dict) -> dict:
        from psycopg2.extras import Json

        now = datetime.now(tz=timezone.utc)
        inserted = {"session_metas": 0, "turn_events": 0, "facets": 0, "app_state": 0, "plans": 0, "agent_tasks": 0}
        cur = self._conn.cursor()

        # session_metas — one row per session, skip duplicates
        for meta in raw.get("session_metas", []):
            sid = meta.get("session_id")
            if not sid:
                continue
            cur.execute(
                """
                INSERT INTO scrape_data.session_metas (
                    session_id, developer_key, claude_dir, account_type, project_path,
                    start_time, week, date, duration_minutes,
                    user_message_count, assistant_message_count,
                    lines_added, lines_removed, files_modified, git_commits, git_pushes,
                    first_prompt, user_interruptions, tool_errors,
                    uses_task_agent, uses_mcp, uses_web_search, uses_web_fetch,
                    input_tokens, output_tokens,
                    tool_counts, languages, user_response_times, pushed_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                ) ON CONFLICT (session_id) DO NOTHING
                """,
                (
                    sid,
                    meta.get("developer_key", ""),
                    meta.get("claude_dir"),
                    meta.get("account_type"),
                    meta.get("project_path"),
                    meta.get("start_time"),
                    meta.get("week"),
                    meta.get("date"),
                    meta.get("duration_minutes"),
                    meta.get("user_message_count"),
                    meta.get("assistant_message_count"),
                    meta.get("lines_added", 0),
                    meta.get("lines_removed", 0),
                    meta.get("files_modified", 0),
                    meta.get("git_commits", 0),
                    meta.get("git_pushes", 0),
                    meta.get("first_prompt"),
                    meta.get("user_interruptions", 0),
                    meta.get("tool_errors", 0),
                    bool(meta.get("uses_task_agent", False)),
                    bool(meta.get("uses_mcp", False)),
                    bool(meta.get("uses_web_search", False)),
                    bool(meta.get("uses_web_fetch", False)),
                    meta.get("input_tokens", 0),
                    meta.get("output_tokens", 0),
                    Json(meta.get("tool_counts") or {}),
                    Json(meta.get("languages") or {}),
                    Json(meta.get("user_response_times") or []),
                    now,
                ),
            )
            inserted["session_metas"] += cur.rowcount

        # turn_events — skip sessions already stored (session-level dedup)
        existing_te = self._existing_turn_sessions(cur)
        for t in raw.get("turn_events", []):
            sid = t.get("session_id", "")
            if sid in existing_te:
                continue
            event_type = t.get("event_type", "turn")
            if event_type == "skill":
                cur.execute(
                    """
                    INSERT INTO scrape_data.turn_events (
                        session_id, developer_key, event_type,
                        user_ts, is_sidechain, agent_colors_in_session, command, pushed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        sid,
                        t.get("developer_key", ""),
                        "skill",
                        t.get("ts"),
                        bool(t.get("is_sidechain", False)),
                        t.get("agent_colors_in_session", 0),
                        t.get("command"),
                        now,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO scrape_data.turn_events (
                        session_id, developer_key, event_type,
                        user_ts, assistant_ts, agent_ms,
                        is_sidechain, permission_mode,
                        tool_uses, agent_colors_in_session, prompt_text, pushed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        sid,
                        t.get("developer_key", ""),
                        "turn",
                        t.get("user_ts"),
                        t.get("assistant_ts"),
                        t.get("agent_ms"),
                        bool(t.get("is_sidechain", False)),
                        t.get("permission_mode"),
                        Json(t.get("tool_uses") or []),
                        t.get("agent_colors_in_session", 0),
                        t.get("prompt_text") or None,
                        now,
                    ),
                )
            inserted["turn_events"] += 1

        # facets — one row per session, skip duplicates
        for sid, f in raw.get("facets", {}).items():
            cur.execute(
                """
                INSERT INTO scrape_data.facets (
                    session_id, developer_key, underlying_goal, goal_categories,
                    outcome, session_type, claude_helpfulness,
                    friction_counts, friction_detail, primary_success, brief_summary, pushed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (session_id) DO NOTHING
                """,
                (
                    sid,
                    f.get("developer_key"),
                    f.get("underlying_goal"),
                    Json(f.get("goal_categories") or {}),
                    f.get("outcome"),
                    f.get("session_type"),
                    f.get("claude_helpfulness"),
                    Json(f.get("friction_counts") or {}),
                    f.get("friction_detail"),
                    f.get("primary_success"),
                    f.get("brief_summary"),
                    now,
                ),
            )
            inserted["facets"] += cur.rowcount

        # app_state — upsert (latest state wins)
        for dev_key, state in raw.get("app_state", {}).items():
            cur.execute(
                """
                INSERT INTO scrape_data.app_state (
                    developer_key, total_startups, has_used_background_task,
                    install_methods, accounts, pushed_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (developer_key) DO UPDATE SET
                    total_startups           = EXCLUDED.total_startups,
                    has_used_background_task = EXCLUDED.has_used_background_task,
                    install_methods          = EXCLUDED.install_methods,
                    accounts                 = EXCLUDED.accounts,
                    pushed_at                = EXCLUDED.pushed_at
                """,
                (
                    dev_key,
                    state.get("total_startups", 0),
                    bool(state.get("has_used_background_task", False)),
                    Json(state.get("install_methods") or []),
                    Json(state.get("accounts") or []),
                    now,
                ),
            )
            inserted["app_state"] += 1

        # plans — upsert (latest state wins)
        for dev_key, plan_info in raw.get("plans", {}).items():
            cur.execute(
                """
                INSERT INTO scrape_data.plans (
                    developer_key, total_plans, new_plans_since_last_run, plan_names, pushed_at
                ) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (developer_key) DO UPDATE SET
                    total_plans              = EXCLUDED.total_plans,
                    new_plans_since_last_run = EXCLUDED.new_plans_since_last_run,
                    plan_names               = EXCLUDED.plan_names,
                    pushed_at                = EXCLUDED.pushed_at
                """,
                (
                    dev_key,
                    plan_info.get("total_plans", 0),
                    plan_info.get("new_plans_since_last_run", 0),
                    Json(plan_info.get("plan_names") or []),
                    now,
                ),
            )
            inserted["plans"] += 1

        # agent_tasks — update session_metas with ai_title/agent_names, insert task rows
        existing_at = self._existing_agent_sessions(cur)
        for session_id, at_data in raw.get("agent_tasks", {}).items():
            ai_title    = at_data.get("ai_title")
            agent_names = at_data.get("agent_names") or []
            dev_key     = at_data.get("developer_key", "")

            # Backfill ai_title and agent_names onto session_metas (COALESCE preserves existing value)
            if ai_title or agent_names:
                cur.execute(
                    """
                    UPDATE scrape_data.session_metas
                       SET ai_title    = COALESCE(ai_title, %s),
                           agent_names = %s
                     WHERE session_id = %s
                    """,
                    (ai_title, Json(agent_names), session_id),
                )

            if session_id in existing_at:
                continue
            for task in at_data.get("tasks", []):
                cur.execute(
                    """
                    INSERT INTO scrape_data.agent_tasks (
                        session_id, developer_key, task_id, agent_name,
                        task_description, status, enqueued_at, week, pushed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        session_id,
                        dev_key,
                        task.get("task_id"),
                        task.get("agent_name"),
                        task.get("task_description"),
                        task.get("status"),
                        task.get("enqueued_at"),
                        task.get("week"),
                        now,
                    ),
                )
                inserted["agent_tasks"] += 1

        self._conn.commit()
        return inserted

    def _existing_agent_sessions(self, cur=None) -> set[str]:
        if cur is None:
            cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT session_id FROM scrape_data.agent_tasks")
        return {r[0] for r in cur.fetchall()}

    def _existing_turn_sessions(self, cur=None) -> set[str]:
        if cur is None:
            cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT session_id FROM scrape_data.turn_events")
        return {r[0] for r in cur.fetchall()}

    # ── pushed_session_ids ────────────────────────────────────────────────────

    def pushed_session_ids(self) -> set[str]:
        rows = self._fetchall("SELECT session_id FROM scrape_data.session_metas")
        return {r[0] for r in rows}

    def pushed_agent_session_ids(self) -> set[str]:
        """Session IDs already in agent_tasks — used for incremental agent collection."""
        rows = self._fetchall("SELECT DISTINCT session_id FROM scrape_data.agent_tasks")
        return {r[0] for r in rows}

    # ── pull_raw ──────────────────────────────────────────────────────────────

    def pull_raw(self, since: datetime | None = None) -> dict:
        since_date = since.date().isoformat() if since else None
        sm_select = (
            "SELECT " + ", ".join(_SM_COLS) +
            " FROM scrape_data.session_metas"
        )

        if since_date:
            rows = self._fetchall(
                sm_select + " WHERE date >= %s OR date IS NULL", (since_date,)
            )
        else:
            rows = self._fetchall(sm_select)

        session_metas = []
        for row in rows:
            d = dict(zip(_SM_COLS, row))
            # TIMESTAMPTZ comes back as aware datetime — convert to ISO string
            st = d.get("start_time")
            if st and hasattr(st, "isoformat"):
                d["start_time"] = st.isoformat()
            # DATE comes back as date object — convert to string
            dt = d.get("date")
            if dt and hasattr(dt, "isoformat"):
                d["date"] = dt.isoformat()
            session_metas.append(d)

        in_scope = {m["session_id"] for m in session_metas}
        turn_events: list[dict] = []
        facets: dict[str, dict] = {}

        if in_scope:
            ph = ",".join(["%s"] * len(in_scope))
            args = tuple(in_scope)

            te_select = (
                "SELECT " + ", ".join(_TE_COLS) +
                f" FROM scrape_data.turn_events WHERE session_id IN ({ph})"
            )
            for row in self._fetchall(te_select, args):
                d = dict(zip(_TE_COLS, row))
                event_type = d.pop("event_type")
                command    = d.pop("command")
                if event_type == "skill":
                    ts_val = d.get("user_ts")
                    turn_events.append({
                        "session_id":              d["session_id"],
                        "developer_key":           d["developer_key"],
                        "event_type":              "skill",
                        "command":                 command,
                        "ts":                      ts_val.isoformat() if hasattr(ts_val, "isoformat") else ts_val,
                        "is_sidechain":            d.get("is_sidechain", False),
                        "agent_colors_in_session": d.get("agent_colors_in_session", 0),
                    })
                else:
                    for k in ("user_ts", "assistant_ts"):
                        v = d.get(k)
                        if v and hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    # NUMERIC comes back as Decimal — computers expect float
                    if d.get("agent_ms") is not None:
                        d["agent_ms"] = float(d["agent_ms"])
                    turn_events.append(d)

            f_select = (
                "SELECT " + ", ".join(_F_COLS) +
                f" FROM scrape_data.facets WHERE session_id IN ({ph})"
            )
            for row in self._fetchall(f_select, args):
                d = dict(zip(_F_COLS, row))
                facets[d["session_id"]] = d

        # app_state — all rows
        app_state: dict[str, dict] = {}
        for row in self._fetchall(
            "SELECT developer_key, total_startups, has_used_background_task, "
            "install_methods, accounts FROM scrape_data.app_state"
        ):
            app_state[row[0]] = {
                "developer_key":           row[0],
                "total_startups":          row[1],
                "has_used_background_task": row[2],
                "install_methods":         row[3],
                "accounts":                row[4],
            }

        # plans — all rows
        plans: dict[str, dict] = {}
        for row in self._fetchall(
            "SELECT developer_key, total_plans, new_plans_since_last_run, plan_names "
            "FROM scrape_data.plans"
        ):
            plans[row[0]] = {
                "developer_key":            row[0],
                "total_plans":              row[1],
                "new_plans_since_last_run": row[2],
                "plan_names":               row[3],
            }

        # agent_tasks — keyed by session_id
        agent_tasks_result: dict[str, list] = {}
        if in_scope:
            at_rows = self._fetchall(
                f"SELECT session_id, task_id, agent_name, task_description, status, enqueued_at "
                f"FROM scrape_data.agent_tasks WHERE session_id IN ({ph})",
                args,
            )
            for row in at_rows:
                enq = row[5]
                agent_tasks_result.setdefault(row[0], []).append({
                    "task_id":          row[1],
                    "agent_name":       row[2],
                    "task_description": row[3],
                    "status":           row[4],
                    "enqueued_at":      enq.isoformat() if hasattr(enq, "isoformat") else enq,
                })

        return {
            "session_metas": session_metas,
            "turn_events":   turn_events,
            "facets":        facets,
            "app_state":     app_state,
            "plans":         plans,
            "agent_tasks":   agent_tasks_result,
        }

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "session_metas": self._fetchall("SELECT COUNT(*) FROM scrape_data.session_metas")[0][0],
            "turn_events":   self._fetchall("SELECT COUNT(*) FROM scrape_data.turn_events")[0][0],
            "facets":        self._fetchall("SELECT COUNT(*) FROM scrape_data.facets")[0][0],
            "app_state":     self._fetchall("SELECT COUNT(*) FROM scrape_data.app_state")[0][0],
            "plans":         self._fetchall("SELECT COUNT(*) FROM scrape_data.plans")[0][0],
            "agent_tasks":   self._fetchall("SELECT COUNT(*) FROM scrape_data.agent_tasks")[0][0],
            "developers":    self._fetchall(
                "SELECT COUNT(DISTINCT developer_key) FROM scrape_data.session_metas"
            )[0][0],
            "backend": "postgresql",
        }

    def upsert_developers(self, developer_map: list[dict]) -> int:
        from psycopg2.extras import Json
        now = datetime.now(tz=timezone.utc)
        cur = self._conn.cursor()
        count = 0
        for dev in developer_map:
            key = dev.get("developer_key")
            if not key:
                continue
            cur.execute(
                """
                INSERT INTO scrape_data.developers (developer_key, name, email, claude_dirs, pushed_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (developer_key) DO UPDATE
                    SET name        = COALESCE(EXCLUDED.name, scrape_data.developers.name),
                        email       = COALESCE(EXCLUDED.email, scrape_data.developers.email),
                        claude_dirs = EXCLUDED.claude_dirs,
                        pushed_at   = EXCLUDED.pushed_at
                """,
                (key, dev.get("name"), dev.get("email"), Json(dev.get("claude_dirs", [])), now),
            )
            count += cur.rowcount
        self._conn.commit()
        return count

    def close(self):
        self._conn.close()
