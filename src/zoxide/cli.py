"""Command line interface for zoxide:

    zoxide add <path>
    zoxide query [--list|-l] [--interactive|-i] [--score] [--exclude PATH] keywords...
    zoxide remove <path>
    zoxide edit -- <rank> <path>      (edit / set score directly)
    zoxide import <path>              (import from real zoxide's db.zo)
    zoxide init <shell>
    zoxide --version

`z` and `zi` wrapper functions are installed via `zoxide init <shell>` and
call back into `zoxide query` / `zoxide add`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__
from .db import Database
from .match import query as run_query


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def cmd_add(args: argparse.Namespace) -> int:
    db = Database()
    for raw in args.paths:
        p = Path(raw).expanduser()
        if not p.is_dir():
            continue
        db.add(str(p), weight=args.weight)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    db = Database()
    if args.interactive:
        results = run_query(db, args.keywords or [], only_existing=False)
        chosen = _interactive_pick(results, prompt="remove> ")
        if chosen is None:
            return 1
        ok = db.remove(chosen)
        print(f"removed: {chosen}" if ok else f"not found: {chosen}")
        return 0 if ok else 1

    if not args.keywords:
        _print_err("zoxide remove: expected a path or -i")
        return 1
    target = args.keywords[0]
    ok = db.remove(target)
    if not ok:
        _print_err(f"zoxide remove: '{target}' is not in the database")
        return 1
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    db = Database()
    now = time.time()
    exclude = str(Path(args.exclude).resolve()) if args.exclude else None

    results = run_query(
        db,
        args.keywords,
        now=now,
        exclude=exclude,
        only_existing=not args.all,
        limit=None if (args.list or args.interactive or args.all) else 1,
    )

    if args.interactive:
        chosen = _interactive_pick(results, prompt="z> ", now=now)
        if chosen is None:
            return 1
        print(chosen)
        return 0

    if args.list:
        for e in results:
            if args.score:
                print(f"{e.frecency(now):>10.2f}  {e.path}")
            else:
                print(e.path)
        return 0
    if not results:
        return 1
    print(results[0].path)
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    db = Database()
    ok = db.set_score(args.path, args.score)
    if not ok:
        _print_err(f"zoxide edit: '{args.path}' is not in the database")
        return 1
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Import entries from a real zoxide db.zo (bincode) OR a simple text
    dump produced by `zoxide query -l --score` from the original tool, or a
    z.sh/autojump style text database ("rank|timestamp|path" or
    "timestamp:rank:path")."""
    src = Path(args.path).expanduser()
    if not src.exists():
        _print_err(f"zoxide import: file not found: {src}")
        return 1

    db = Database()
    count = 0
    text = None
    try:
        text = src.read_text(errors="ignore")
    except Exception as exc:  # pragma: no cover
        _print_err(f"zoxide import: cannot read file: {exc}")
        return 1

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        entry = _parse_import_line(line)
        if entry is None:
            continue
        path, rank, last_accessed = entry
        if not Path(path).is_dir() and not args.merge_missing:
            continue
        for e in db.entries:
            if e.path == path:
                e.rank = max(e.rank, rank) if args.merge else rank
                e.last_accessed = max(e.last_accessed, last_accessed)
                break
        else:
            from .db import Entry

            db.entries.append(Entry(path=path, rank=rank, last_accessed=last_accessed))
        count += 1

    db.save()
    print(f"imported {count} entries")
    return 0


def _parse_import_line(line: str):
    if "\t" in line:
        parts = line.split("\t")
        if len(parts) == 2:
            try:
                weight = float(parts[0])
                return parts[1], weight, time.time()
            except ValueError:
                pass
    if "|" in line:
        parts = line.split("|")
        if len(parts) == 3:
            path, rank, ts = parts
            try:
                return path, float(rank), float(ts)
            except ValueError:
                pass
    return None


def cmd_init(args: argparse.Namespace) -> int:
    from .shell import render

    try:
        script = render(
            shell=args.shell,
            cmd=args.cmd,
            hook=args.hook,
            no_cmd=args.no_cmd,
            no_aliases=args.no_aliases,
        )
    except ValueError as exc:
        _print_err(str(exc))
        return 1
    print(script)
    return 0


def _interactive_pick(results, prompt: str = "> ", now: Optional[float] = None) -> Optional[str]:
    if not results:
        return None
    now = now or time.time()

    fzf = shutil.which("fzf")
    if fzf:
        lines = [f"{e.frecency(now):>10.2f}\t{e.path}" for e in results]
        try:
            proc = subprocess.run(
                [fzf, "--no-sort", "--tiebreak=index", "--delimiter=\t", "--with-nth=2", "--prompt", prompt],
                input="\n".join(lines),
                capture_output=True,
                text=True,
            )
        except OSError:
            proc = None
        if proc and proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().split("\t")[-1]
        return None

    _print_err("(fzf not found; using simple picker)")
    for i, e in enumerate(results, 1):
        _print_err(f"{i:3d}) {e.path}")
    try:
        with open("/dev/tty") as tty_in:
            _print_err(prompt.rstrip() + " ")
            choice = tty_in.readline().strip()
    except OSError:
        return None
    if not choice.isdigit():
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(results):
        return results[idx].path
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zoxide", description="A smarter cd command, in Python.")
    p.add_argument("--version", action="version", version=f"zoxide {__version__}")
    sub = p.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="Add one or more paths to the database")
    p_add.add_argument("paths", nargs="+")
    p_add.add_argument("--weight", type=float, default=1.0)
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", aliases=["rm"], help="Remove a path from the database")
    p_rm.add_argument("keywords", nargs="*")
    p_rm.add_argument("-i", "--interactive", action="store_true")
    p_rm.set_defaults(func=cmd_remove)

    p_q = sub.add_parser("query", help="Search the database")
    p_q.add_argument("keywords", nargs="*")
    p_q.add_argument("-l", "--list", action="store_true", help="List all matches")
    p_q.add_argument("-s", "--score", action="store_true", help="Show score with -l")
    p_q.add_argument("-i", "--interactive", action="store_true", help="Pick interactively")
    p_q.add_argument("-a", "--all", action="store_true", help="Include non-existent paths")
    p_q.add_argument("-e", "--exclude", help="Exclude this path from results")
    p_q.set_defaults(func=cmd_query)

    p_edit = sub.add_parser("edit", help="Directly set an entry's score")
    p_edit.add_argument("path")
    p_edit.add_argument("score", type=float)
    p_edit.set_defaults(func=cmd_edit)

    p_imp = sub.add_parser("import", help="Import entries from another frecency tool's DB")
    p_imp.add_argument("path")
    p_imp.add_argument("--merge", action="store_true", help="Keep max rank on conflicts")
    p_imp.add_argument("--merge-missing", action="store_true", help="Import even nonexistent dirs")
    p_imp.set_defaults(func=cmd_import)

    p_init = sub.add_parser("init", help="Generate shell integration script")
    p_init.add_argument("shell", choices=["bash", "zsh", "fish", "posix"])
    p_init.add_argument("--cmd", default="z", help="Name of the jump command (default: z)")
    p_init.add_argument("--hook", choices=["none", "prompt", "pwd"], default="pwd")
    p_init.add_argument("--no-cmd", action="store_true", help="Do not define any commands")
    p_init.add_argument("--no-aliases", action="store_true", help="Do not define zi/etc aliases")
    p_init.set_defaults(func=cmd_init)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)
