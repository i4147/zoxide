"""Matching and ranking logic mirroring zoxide's `query` behaviour.

Rules (same spirit as upstream zoxide):
  - Each keyword must appear as a case-insensitive substring somewhere in the
    path, in order is NOT required for anywhere except the last keyword.
  - The LAST keyword must match against the final path component (basename)
    unless the flag `--all-substring`/no-basename-restriction is used.  This
    is exactly how zoxide behaves by default: it requires the last keyword to
    be found in the basename (this is what makes `z foo` jump to
    `/a/b/foo-project` and not `/a/b/foo-project/unrelated`).
  - Results are ordered by frecency score, descending.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, List, Optional

from .db import Database, Entry


def _matches(entry_path: str, keywords: List[str], require_basename_last: bool) -> bool:
    lower = entry_path.lower()
    if not keywords:
        return True

    if require_basename_last:
        *head_kw, last_kw = keywords
        basename = Path(entry_path).name.lower()
        if last_kw not in basename:
            return False
        keywords_to_check = head_kw
    else:
        keywords_to_check = keywords

    return all(kw in lower for kw in keywords_to_check)


def query(
    db: Database,
    keywords: Iterable[str],
    *,
    now: Optional[float] = None,
    exclude: Optional[str] = None,
    only_existing: bool = True,
    require_basename_last: bool = True,
    limit: Optional[int] = None,
) -> List[Entry]:
    now = time.time() if now is None else now
    kws = [k.lower() for k in keywords if k]

    candidates = []
    for e in db.entries:
        if exclude and e.path == exclude:
            continue
        if not _matches(e.path, kws, require_basename_last):
            continue
        if only_existing and not Path(e.path).is_dir():
            continue
        candidates.append(e)

    candidates.sort(key=lambda e: e.frecency(now), reverse=True)
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def best_match(db: Database, keywords: Iterable[str], **kwargs) -> Optional[Entry]:
    results = query(db, keywords, limit=1, **kwargs)
    return results[0] if results else None
