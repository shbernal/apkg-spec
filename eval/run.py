"""Score the spec and every implementation against the official Anki library.

    uv run eval/run.py              # all scores, appended to eval/history.jsonl
    uv run eval/run.py --gate       # also hold the scores to eval/goal.json
    uv run eval/run.py --heldout    # score the held-out corpus slice too

Metrics, each a percentage:

    claims            claims in claims.yaml with a passing test and no failing one
    spec              claims SPEC.md cites, with no TODO left in it
    read:<impl>       model sections the implementation reads right, per package
    write-v<N>:<impl>      sections that survive a package version N write, read by Anki
    roundtrip-v<N>:<impl>  write(read(package)) as version N, on the local corpus

An implementation's `write_versions` (default [2]) lists the versions scored.

Packages come from `conformance/` (synthetic, committed) and `corpus/local/`
(real decks, never committed). One package in five of the corpus is held out
by a hash of its name and is scored only with --heldout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))

from model import (
    SECTIONS,
    acceptance_problems,
    diff,
    package_version,
    read_media,
    read_model,
)

GOAL = ROOT / "eval" / "goal.json"
HISTORY = ROOT / "eval" / "history.jsonl"
TIMEOUT = 120


@dataclass
class Score:
    passed: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)

    def add(self, ok: bool, label: str) -> None:
        self.total += 1
        self.passed += ok
        if not ok:
            self.failures.append(label)

    @property
    def pct(self) -> float:
        return round(100 * self.passed / self.total, 1) if self.total else 0.0


def heldout(path: Path) -> bool:
    return int(hashlib.sha1(path.name.encode()).hexdigest(), 16) % 5 == 0


def packages(include_heldout: bool) -> list[tuple[str, Path, dict[str, Any] | None]]:
    """(label, package, expected model or None to derive it from the oracle)."""
    out: list[tuple[str, Path, dict[str, Any] | None]] = []
    for case in sorted((ROOT / "conformance").iterdir()):
        if not (case / "model.json").is_file():
            continue
        expected = json.loads((case / "model.json").read_text())
        for version in ("v2", "v3"):
            out.append((f"{case.name}/{version}", case / f"{version}.apkg", expected))
    corpus = ROOT / "corpus" / "local"
    if corpus.is_dir():
        for path in sorted(corpus.glob("**/*.apkg")):
            if heldout(path) and not include_heldout:
                continue
            tag = "heldout" if heldout(path) else "corpus"
            out.append((f"{tag}/{path.relative_to(corpus)}", path, None))
    return out


def run(template: str, **paths: Path) -> subprocess.CompletedProcess[str]:
    argv = [part.format(**{k: str(v) for k, v in paths.items()}) for part in shlex.split(template)]
    return subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT, check=False
    )


def score_sections(score: Score, label: str, expected: dict, actual: dict | None) -> None:
    result = diff(expected, actual or {})
    for section in SECTIONS:
        reason = result[section]
        score.add(reason is None, f"{label} {section}: {reason}")


def read_with(impl: dict, package: Path) -> tuple[dict | None, str | None]:
    try:
        proc = run(impl["read"], input=package)
    except subprocess.TimeoutExpired:
        return None, "read timed out"
    if proc.returncode != 0:
        return None, f"read exited {proc.returncode}: {proc.stderr.strip()[-300:]}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as error:
        return None, f"read printed invalid JSON: {error}"


def media_dir(package: Path, work: Path) -> Path:
    """The package's media as files named as the model names them.

    The model carries only hashes, so a writer reads the bytes from here. Corpus
    round trips take them from the source package too: the read side already
    scored the hashes.
    """
    out = work / f"media-{hashlib.sha1(str(package).encode()).hexdigest()[:12]}"
    if not out.is_dir():
        out.mkdir()
        for name, blob in read_media(package).items():
            (out / name).write_bytes(blob)
    return out


def write_with(impl: dict, model: dict, media: Path, version: int, out: Path) -> str | None:
    model_path = out.with_suffix(".json")
    model_path.write_text(json.dumps(model, ensure_ascii=False))
    try:
        proc = run(impl["write"], model=model_path, media=media, version=version, output=out)
    except subprocess.TimeoutExpired:
        return "write timed out"
    if proc.returncode != 0 or not out.is_file():
        return f"write exited {proc.returncode}: {proc.stderr.strip()[-300:]}"
    try:
        with zipfile.ZipFile(out) as archive:
            written = package_version(archive)
    except zipfile.BadZipFile:
        return "write produced no zip"
    if written != version:
        return f"asked for package version {version}, wrote {written}"
    if problems := acceptance_problems(out):
        return "anki refused: " + "; ".join(problems)
    return None


def score_implementation(name: str, impl: dict, pkgs: list, oracle_cache: dict) -> dict[str, Score]:
    scores: dict[str, Score] = {"read": Score()}
    versions = impl.get("write_versions", [2]) if impl.get("write") else []
    for version in versions:
        scores[f"write-v{version}"] = Score()
        scores[f"roundtrip-v{version}"] = Score()
    work = Path(tempfile.mkdtemp(prefix=f"apkg-eval-{name}-"))
    for label, package, expected in pkgs:
        if expected is None:
            expected = oracle_cache.setdefault(str(package), _oracle_model(package))
            if expected is None:
                continue  # the oracle cannot read it either; not a test case
        is_corpus = not label.startswith(tuple(f"{c}/" for c in _conformance_cases()))

        actual, error = read_with(impl, package)
        if error:
            for section in SECTIONS:
                scores["read"].add(False, f"{label} {section}: {error}")
        else:
            score_sections(scores["read"], label, expected, actual)

        # Synthetic cases test the writer on the oracle's model; corpus cases
        # test the full round trip on what the implementation itself read.
        for version in versions:
            kind, source = ("roundtrip", actual) if is_corpus else ("write", expected)
            key = f"{kind}-v{version}"
            out = work / f"{label.replace('/', '_')}.v{version}.apkg"
            if source is None:
                error = "nothing read to write"
            else:
                error = write_with(impl, source, media_dir(package, work), version, out)
            if error:
                for section in SECTIONS:
                    scores[key].add(False, f"{label} {section}: {error}")
            else:
                score_sections(scores[key], label, expected, _oracle_model(out))
    # No corpus means no round trip, which is no score rather than 0%.
    return {kind: score for kind, score in scores.items() if score.total}


def _conformance_cases() -> list[str]:
    return [p.name for p in (ROOT / "conformance").iterdir() if p.is_dir()]


def _oracle_model(package: Path) -> dict | None:
    try:
        model = read_model(package)
    except Exception:  # noqa: BLE001
        return None
    model.pop("packageVersion", None)
    return model


def score_claims() -> Score:
    claims = yaml.safe_load((ROOT / "claims.yaml").read_text())["claims"]
    report = Path(tempfile.mkdtemp()) / "claims.json"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env={**os.environ, "CLAIMS_REPORT": str(report)},
        capture_output=True,
        check=False,
    )
    results: dict[str, list[bool]] = json.loads(report.read_text()) if report.exists() else {}
    score = Score()
    for claim in claims:
        outcomes = results.get(claim["id"], [])
        if not outcomes:
            score.add(False, f"{claim['id']}: no test")
        else:
            score.add(all(outcomes), f"{claim['id']}: {outcomes.count(False)} failing test(s)")
    return score


def score_spec() -> Score:
    claims = yaml.safe_load((ROOT / "claims.yaml").read_text())["claims"]
    text = (ROOT / "SPEC.md").read_text()
    score = Score()
    for claim in claims:
        score.add(f"[{claim['id']}]" in text, f"{claim['id']}: not cited in SPEC.md")
    todos = text.count("TODO")
    score.add(todos == 0, f"SPEC.md: {todos} TODO(s) left")
    return score


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def locked_changes(goal: dict) -> list[str]:
    """Locked paths that differ from the commit that started the goal."""
    base = git("log", "-1", "--diff-filter=A", "--format=%H", "--", "eval/goal.json")
    changed = git("diff", "--name-only", base).splitlines()
    changed += git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({p for p in changed for pattern in goal["locked"] if fnmatch(p, pattern)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--heldout", action="store_true")
    parser.add_argument("--only", help="score only this implementation (and skip claims)")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every failure")
    args = parser.parse_args()

    implementations = tomllib.loads((ROOT / "eval" / "implementations.toml").read_text())
    pkgs = packages(args.heldout)
    metrics: dict[str, Score] = {}
    if not args.only:
        metrics["claims"] = score_claims()
        metrics["spec"] = score_spec()
    cache: dict = {}
    for name, impl in implementations.items():
        if args.only and name != args.only:
            continue
        if build := impl.get("build"):
            proc = subprocess.run(
                shlex.split(build), cwd=ROOT, capture_output=True, text=True, check=False
            )
            if proc.returncode != 0:
                print(f"BUILD FAIL {name}: {proc.stderr.strip()[-500:]}")
        for kind, score in score_implementation(name, impl, pkgs, cache).items():
            metrics[f"{kind}:{name}"] = score

    for key, score in metrics.items():
        print(f"SCORE {key:<32} {score.pct:5.1f}%  ({score.passed}/{score.total})")
        shown = score.failures if args.verbose else score.failures[:5]
        for failure in shown:
            print(f"    - {failure}")
        if len(score.failures) > len(shown):
            print(f"    … {len(score.failures) - len(shown)} more (-v)")

    dirty = bool(git("status", "--porcelain"))
    with HISTORY.open("a") as history:
        history.write(
            json.dumps(
                {
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "commit": git("rev-parse", "--short", "HEAD") or None,
                    "dirty": dirty,
                    "heldout": args.heldout,
                    "scores": {k: s.pct for k, s in metrics.items()},
                }
            )
            + "\n"
        )

    if not args.gate:
        return 0
    if not GOAL.exists():
        print("GATE no eval/goal.json; nothing to hold the scores to")
        return 0
    goal = json.loads(GOAL.read_text())
    problems = [
        f"{key} is {metrics[key].pct if key in metrics else 'unmeasured'}%, target {target}%"
        for key, target in goal["targets"].items()
        if key not in metrics or metrics[key].pct < target
    ]
    if touched := locked_changes(goal):
        problems.append(f"locked paths changed since the goal started: {', '.join(touched)}")
    for repo in [".", *goal.get("clean", [])]:
        if git("-C", repo, "status", "--porcelain"):
            problems.append(f"{repo} has uncommitted changes; commit the work the scores describe")
    for problem in problems:
        print(f"GATE FAIL {problem}")
    if not problems:
        print("GATE PASS all targets met")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
