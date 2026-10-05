from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest
from model import unzstd

ENTRY = {"v2": "collection.anki21", "v3": "collection.anki21b"}


def cases(conformance: Path) -> list[Path]:
    return sorted(p for p in conformance.iterdir() if p.is_dir())


@pytest.mark.claim("APKG-ZIP-001")
def test_every_package_is_a_zip(conformance: Path) -> None:
    for case in cases(conformance):
        for version in ENTRY:
            assert zipfile.is_zipfile(case / f"{version}.apkg"), case.name


@pytest.mark.claim("APKG-COL-001")
@pytest.mark.claim("APKG-COL-002")
def test_collection_entry_by_version(conformance: Path) -> None:
    for case in cases(conformance):
        for version, entry in ENTRY.items():
            with zipfile.ZipFile(case / f"{version}.apkg") as archive:
                data = archive.read(entry)
            if version == "v3":
                assert data[:4] == b"\x28\xb5\x2f\xfd", "zstd magic"
                data = unzstd(data)
            assert data[:16] == b"SQLite format 3\x00", case.name


@pytest.mark.claim("APKG-COL-004")
def test_schema_version_by_package_version(conformance: Path) -> None:
    for case in cases(conformance):
        for version, schema in (("v2", 11), ("v3", 18)):
            with zipfile.ZipFile(case / f"{version}.apkg") as archive:
                data = archive.read(ENTRY[version])
            if version == "v3":
                data = unzstd(data)
            with tempfile.NamedTemporaryFile(suffix=".db") as db:
                db.write(data)
                db.flush()
                (ver,) = sqlite3.connect(db.name).execute("select ver from col").fetchone()
            assert ver == schema, case.name
