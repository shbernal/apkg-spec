"""Record each claim's test outcomes for `eval/run.py`.

A test proves a claim by carrying `@pytest.mark.claim("APKG-…")`. A claim id
that is not in `claims.yaml` is an error, so a typo cannot pass silently.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
KNOWN = {c["id"] for c in yaml.safe_load((ROOT / "claims.yaml").read_text())["claims"]}
_results: dict[str, list[bool]] = defaultdict(list)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for mark in item.iter_markers("claim"):
            if mark.args[0] not in KNOWN:
                raise pytest.UsageError(f"{item.nodeid}: unknown claim {mark.args[0]}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and not report.passed):
        for mark in item.iter_markers("claim"):
            _results[mark.args[0]].append(report.passed)


def pytest_sessionfinish() -> None:
    if path := os.environ.get("CLAIMS_REPORT"):
        Path(path).write_text(json.dumps(_results))


@pytest.fixture(scope="session")
def conformance() -> Path:
    return ROOT / "conformance"
