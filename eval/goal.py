"""Start or end a goal run: targets the Stop hook holds the agent to.

    uv run eval/goal.py start --target read:anki-apkg-export=100 \\
        --lock 'eval/**' --lock 'oracle/**' --lock 'conformance/**' \\
        --clean "$ANKI_APKG_EXPORT"
    uv run eval/goal.py stop

`start` writes eval/goal.json, commits it, and prints the `/goal` condition to
paste. The commit that adds it is the base: the gate fails if any locked path, goal.json
included, differs from it. `stop` removes the file in a commit of its own.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOAL = ROOT / "eval" / "goal.json"
ALWAYS_LOCKED = ["eval/**", ".claude/**"]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def condition(goal: dict) -> str:
    targets = ", ".join(f"`{k}` >= {v}%" for k, v in goal["targets"].items())
    return (
        f"`uv run eval/run.py --gate` prints `GATE PASS` in its last run, after the last "
        f"code change and commit. Targets: {targets}. Do not edit {', '.join(goal['locked'])}. "
        f"Stop and report as impossible if a target needs a locked path changed."
    )


def start(args: argparse.Namespace) -> int:
    if GOAL.exists():
        print("a goal is already running; `uv run eval/goal.py stop` first", file=sys.stderr)
        return 1
    if git("status", "--porcelain"):
        print("commit or stash first: the goal's base must be a clean tree", file=sys.stderr)
        return 1
    targets = {}
    for item in args.target:
        key, _, value = item.partition("=")
        targets[key] = float(value)
    goal = {
        "targets": targets,
        "locked": sorted(set(ALWAYS_LOCKED + args.lock)),
        "clean": args.clean,
        "maxBlocks": args.max_blocks,
    }
    GOAL.write_text(json.dumps(goal, indent=2) + "\n")
    git("add", str(GOAL))
    git("commit", "-q", "-m", "Start a goal run")
    print("/goal " + condition(goal))
    return 0


def stop(_: argparse.Namespace) -> int:
    if not GOAL.exists():
        print("no goal is running")
        return 0
    git("rm", "-q", str(GOAL))
    git("commit", "-q", "-m", "End the goal run")
    (ROOT / "eval" / ".gate-blocks").unlink(missing_ok=True)
    print("goal ended")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)
    s = sub.add_parser("start")
    s.add_argument("--target", action="append", required=True, metavar="METRIC=PCT")
    s.add_argument("--lock", action="append", default=[], metavar="GLOB")
    s.add_argument("--clean", action="append", default=[], metavar="REPO")
    s.add_argument("--max-blocks", type=int, default=40)
    s.set_defaults(func=start)
    sub.add_parser("stop").set_defaults(func=stop)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
