"""
Incremental state and output store.

Tracks last-run timestamps and processed session IDs so batch runs only
process new data. Writes final metric output as JSON.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_STORE_DIR = Path.home() / ".claude-metrics"
_STATE_FILE = "last_run.json"
_OUTPUT_FILE = "metrics.json"


class MetricsStore:
    def __init__(self, store_dir: Path | None = None):
        self.dir = store_dir or _DEFAULT_STORE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._state: dict = self._load_state()

    # ── State management ──────────────────────────────────────────────────

    def _load_state(self) -> dict:
        p = self.dir / _STATE_FILE
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {
            "last_daily": None,
            "last_weekly": None,
            "processed_sessions": [],
        }

    def _save_state(self) -> None:
        p = self.dir / _STATE_FILE
        p.write_text(json.dumps(self._state, indent=2))

    def last_run_dt(self, run_type: str = "weekly") -> datetime | None:
        """Return last run datetime for 'daily' or 'weekly'."""
        key = f"last_{run_type}"
        raw = self._state.get(key)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def processed_sessions(self) -> set[str]:
        return set(self._state.get("processed_sessions", []))

    def mark_sessions_processed(self, session_ids: list[str]) -> None:
        existing = set(self._state.get("processed_sessions", []))
        existing.update(session_ids)
        # Cap to last 10k to avoid unbounded growth
        self._state["processed_sessions"] = list(existing)[-10_000:]

    def mark_run_complete(self, run_type: str = "weekly") -> None:
        self._state[f"last_{run_type}"] = datetime.now(tz=timezone.utc).isoformat()
        self._save_state()

    # ── Output ────────────────────────────────────────────────────────────

    def write_output(self, payload: dict, output_path: Path | None = None) -> Path:
        """Write metrics JSON output. Returns the path written."""
        path = output_path or (self.dir / _OUTPUT_FILE)
        path.write_text(json.dumps(payload, indent=2, default=str))
        return path

    def read_output(self) -> dict:
        p = self.dir / _OUTPUT_FILE
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {}

    # ── Historical append ─────────────────────────────────────────────────

    def append_weekly_snapshot(self, payload: dict) -> None:
        """Append weekly snapshot to a rolling JSONL history file."""
        history_path = self.dir / "history.jsonl"
        with open(history_path, "a") as f:
            f.write(json.dumps(payload, default=str) + "\n")

    def read_weekly_history(self, last_n: int = 12) -> list[dict]:
        """Return up to last_n weekly snapshots, oldest-first."""
        history_path = self.dir / "history.jsonl"
        if not history_path.exists():
            return []
        rows = []
        for line in history_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        return rows[-last_n:]
