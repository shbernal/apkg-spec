from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from anki.errors import InvalidInput
from apkg import collection_bytes, fresh_collection, import_package, rewrite, tamper


def _with_sql(src: Path, dst: Path, sql: str) -> Path:
    data = tamper(collection_bytes(src, "collection.anki21"), sql)
    return rewrite(src, dst, replace={"collection.anki21": data})


@pytest.mark.claim("APKG-IMP-001")
@pytest.mark.parametrize("version", ["v2", "v3"])
def test_second_import_adds_nothing(conformance: Path, tmp_path: Path, version: str) -> None:
    package = conformance / "basic" / f"{version}.apkg"
    with fresh_collection() as col:
        first = import_package(col, package)
        assert len(first.new) == 2
        second = import_package(col, package)
        assert len(second.new) == 0
        assert len(second.duplicate) == 2
        assert col.note_count() == 2

    # A changed guid makes the same note new again.
    if version == "v2":
        changed = _with_sql(
            package,
            tmp_path / "guid.apkg",
            "update notes set guid = guid || '-x' where guid = 'basic-0'",
        )
        with fresh_collection() as col:
            import_package(col, package)
            assert len(import_package(col, changed).new) == 1
            assert col.note_count() == 3


@pytest.mark.claim("APKG-IMP-002")
def test_import_recomputes_checksums(conformance: Path, tmp_path: Path) -> None:
    package = _with_sql(
        conformance / "basic" / "v2.apkg", tmp_path / "csum.apkg", "update notes set csum = 0"
    )
    with fresh_collection() as col:
        import_package(col, package)
        rows = col.db.all("select csum, sfld from notes")
    assert len(rows) == 2
    for csum, sfld in rows:
        assert csum == int(hashlib.sha1(str(sfld).encode()).hexdigest()[:8], 16)


@pytest.mark.claim("APKG-IMP-003")
@pytest.mark.parametrize(
    "change", ["flds || char(31) || 'extra'", "substr(flds, 1, instr(flds, char(31)) - 1)"]
)
def test_import_rejects_wrong_field_count(conformance: Path, tmp_path: Path, change: str) -> None:
    package = _with_sql(
        conformance / "basic" / "v2.apkg",
        tmp_path / "fields.apkg",
        f"update notes set flds = {change} where guid = 'basic-0'",
    )
    with fresh_collection() as col:
        with pytest.raises(InvalidInput, match="fields"):
            import_package(col, package)
        assert col.db.scalar("select count() from notes where guid = 'basic-0'") == 0
