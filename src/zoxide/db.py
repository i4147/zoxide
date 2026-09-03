"""Database layer: stores (path, rank, last_accessed) entries with a
frecency (frequency + recency) score, using the same aging algorithm as the
original Rust `zoxide`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY

# When the sum of all ranks exceeds this, every rank is scaled down by
# AGE_FACTOR and entries that fall below 1.0 are dropped. This keeps the
# database bounded without ever needing a hard entry-count limit.
MAX_AGE = 10_000.0
AGE_FACTOR = 0.9

DB_VERSION = 1


def _default_data_dir() -> Path:
    if env := os.environ.get("_ZO_DATA_DIR"):
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "zoxide"


def db_path() -> Path:
    return _default_data_dir() / "db.json"


@dataclass
class Entry:
    path: str
    rank: float
    last_accessed: float

    def frecency(self, now: float) -> float:
        """Score combining visit frequency (rank) and recency."""
        age = now - self.last_accessed
        if age < HOUR:
            multiplier = 4.0
        elif age < DAY:
            multiplier = 2.0
        elif age < WEEK:
            multiplier = 0.5
        else:
            multiplier = 0.25
        return self.rank * multiplier


class Database:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or db_path()
        self.entries: List[Entry] = []
        self._dirty = False
        self._load()

    # -- persistence ---------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            self.entries = []
            return
        try:
            raw = json.loads(self.path.read_text())
            self.entries = [
                Entry(path=e["path"], rank=float(e["rank"]), last_accessed=float(e["last_accessed"]))
                for e in raw.get("entries", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Corrupt DB: start fresh rather than crashing the shell hook.
            self.entries = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": DB_VERSION, "entries": [asdict(e) for e in self.entries]}
        tmp = self.path.with_name(self.path.name + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.path)
        self._dirty = False

    # -- mutation --------------------------------------------------------
    def add(self, path: str, now: Optional[float] = None, weight: float = 1.0) -> None:
        now = time.time() if now is None else now
        norm = _normalize(path)
        for e in self.entries:
            if e.path == norm:
                e.rank += weight
                e.last_accessed = now
                break
        else:
            self.entries.append(Entry(path=norm, rank=weight, last_accessed=now))

        total_rank = sum(e.rank for e in self.entries)
        if total_rank > MAX_AGE:
            for e in self.entries:
                e.rank *= AGE_FACTOR
            self.entries = [e for e in self.entries if e.rank >= 1.0]

        self.save()

    def remove(self, path: str) -> bool:
        norm = _normalize(path)
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.path != norm]
        removed = len(self.entries) != before
        if removed:
            self.save()
        return removed

    def set_score(self, path: str, rank: float) -> bool:
        norm = _normalize(path)
        for e in self.entries:
            if e.path == norm:
                e.rank = rank
                self.save()
                return True
        return False

    def prune_missing(self) -> int:
        """Remove entries whose directory no longer exists. Returns count removed."""
        before = len(self.entries)
        self.entries = [e for e in self.entries if Path(e.path).is_dir()]
        removed = before - len(self.entries)
        if removed:
            self.save()
        return removed


def _normalize(path: str) -> str:
    p = os.path.expanduser(path)
    p = os.path.abspath(p) if not os.path.isabs(p) else p
    # Strip trailing slash (except root).
    if len(p) > 1 and p.endswith(("/", os.sep)):
        p = p.rstrip("/").rstrip(os.sep)
    return p
