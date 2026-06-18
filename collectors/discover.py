"""
Discover all .claude* directories on the machine and build a developer identity map.

Output schema:
  {
    "developer_key": str,       # SHA-256(email) or SHA-256(hostname) — stable ID
    "name":          str | None,
    "email":         str | None,
    "claude_dirs":   [str, ...] # all .claude* dirs belonging to this developer
  }
"""

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()


def _git_identity(cwd: str | None = None) -> tuple[str | None, str | None]:
    """Return (name, email) from git config in cwd, or global git config."""
    name = email = None
    for field, key in [("name", "user.name"), ("email", "user.email")]:
        try:
            val = subprocess.check_output(
                ["git", "config", key],
                cwd=cwd or ".",
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()
            if field == "name":
                name = val or None
            else:
                email = val or None
        except Exception:
            pass
    return name, email


def _read_claude_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _developer_key_from_dir(claude_dir: Path) -> tuple[str, str | None, str | None]:
    """
    Derive developer_key for a given .claude* directory.
    Priority: git config email → hostname fallback.
    Returns (developer_key, name, email).
    """
    # Try git identity from within any project directory in this claude dir
    projects_dir = claude_dir / "projects"
    name = email = None
    if projects_dir.exists():
        for project_subdir in projects_dir.iterdir():
            if project_subdir.is_dir():
                # Reconstruct filesystem path from encoded dir name
                # e.g. -home-kalpaj-Documents-Think41-foo → /home/kalpaj/Documents/Think41/foo
                candidate = "/" + str(project_subdir.name).replace("-", "/", 1).lstrip("/")
                n, e = _git_identity(candidate if Path(candidate).exists() else None)
                if e:
                    name, email = n, e
                    break

    if not email:
        name, email = _git_identity()

    if email:
        return _sha256(email), name, email

    hostname = socket.gethostname()
    return _sha256(hostname + str(claude_dir)), name, None


def find_claude_dirs(home: Path | None = None) -> list[Path]:
    """Return all .claude* directories under the user's home directory."""
    base = home or Path.home()
    dirs = []
    for entry in base.iterdir():
        if entry.name.startswith(".claude") and entry.is_dir():
            dirs.append(entry)
    return sorted(dirs)


def build_developer_map(home: Path | None = None) -> list[dict]:
    """
    Build a list of developer identity records, one per unique developer_key.
    Merges multiple .claude* dirs that belong to the same developer.
    """
    claude_dirs = find_claude_dirs(home)
    grouped: dict[str, dict] = {}

    for d in claude_dirs:
        key, name, email = _developer_key_from_dir(d)
        if key not in grouped:
            grouped[key] = {
                "developer_key": key,
                "name": name,
                "email": email,
                "claude_dirs": [],
            }
        grouped[key]["claude_dirs"].append(str(d))
        # Fill in name/email if missing
        if not grouped[key]["name"] and name:
            grouped[key]["name"] = name
        if not grouped[key]["email"] and email:
            grouped[key]["email"] = email

    return list(grouped.values())


if __name__ == "__main__":
    import json as _json
    for dev in build_developer_map():
        print(_json.dumps(dev, indent=2))
