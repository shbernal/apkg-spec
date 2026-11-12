from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from anki.errors import BackendError
from anki.import_export_pb2 import ExportAnkiPackageOptions, PackageMetadata
from apkg import (
    ENTRY,
    collection_bytes,
    fresh_collection,
    import_package,
    open_db,
    packages,
    rewrite,
)
from fixtures import WITHOUT_META
from model import read_model

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SQLITE_MAGIC = b"SQLite format 3\x00"
PLACEHOLDER = "Please update to the latest Anki version"


def meta_version(package: Path) -> int:
    meta = PackageMetadata()
    with zipfile.ZipFile(package) as archive:
        meta.ParseFromString(archive.read("meta"))
    return int(meta.version)


@pytest.mark.claim("APKG-ZIP-001")
def test_every_package_is_a_zip(conformance: Path) -> None:
    for case, _, package in packages(conformance):
        assert zipfile.is_zipfile(package), case


@pytest.mark.claim("APKG-VER-001")
def test_meta_names_the_version_whose_collection_is_present(
    conformance: Path, tmp_path: Path
) -> None:
    for case, _, package in packages(conformance):
        if case in WITHOUT_META:
            continue
        version = meta_version(package)
        entry = {1: "collection.anki2", 2: "collection.anki21", 3: "collection.anki21b"}[version]
        with zipfile.ZipFile(package) as archive:
            assert entry in archive.namelist(), case
        # Anki trusts `meta` over the entries: a forged version 3 looks for `collection.anki21b`.
        if version == 2:
            forged = PackageMetadata(version=PackageMetadata.VERSION_LATEST).SerializeToString()
            target = rewrite(package, tmp_path / f"{case}.apkg", replace={"meta": forged})
            with (
                fresh_collection() as col,
                pytest.raises(BackendError, match="not found in archive"),
            ):
                import_package(col, target)


def _imported_fronts(package: Path) -> list[str]:
    with fresh_collection() as col:
        import_package(col, package)
        return sorted(col.get_note(nid).fields[0] for nid in col.find_notes(""))


@pytest.mark.claim("APKG-VER-002")
def test_version_without_meta(conformance: Path, tmp_path: Path) -> None:
    v2 = conformance / "basic" / "v2.apkg"
    expected = ["2 + 2", "What is the capital of France?"]

    # Version 2: `collection.anki21` is read, not the placeholder `collection.anki2`.
    no_meta = rewrite(v2, tmp_path / "v2-no-meta.apkg", drop=("meta",))
    assert _imported_fronts(no_meta) == expected

    # Version 1: only `collection.anki2`, which is read as the real collection.
    real = collection_bytes(v2, "collection.anki21")
    v1 = rewrite(
        v2,
        tmp_path / "v1.apkg",
        drop=("meta", "collection.anki21"),
        replace={"collection.anki2": real},
    )
    assert _imported_fronts(v1) == expected

    # The same layout with the placeholder left in place imports the placeholder.
    stub = rewrite(v2, tmp_path / "v1-stub.apkg", drop=("meta", "collection.anki21"))
    assert all(front.startswith(PLACEHOLDER) for front in _imported_fronts(stub))


@pytest.mark.claim("APKG-VER-003")
def test_current_anki_writes_meta_with_version_2_or_3(conformance: Path) -> None:
    for case, version, package in packages(conformance):
        if case in WITHOUT_META:
            continue
        assert meta_version(package) == {"v2": 2, "v3": 3}[version], case
    # The only export choice that bears on the version is the `legacy` flag.
    options = {f.name for f in ExportAnkiPackageOptions.DESCRIPTOR.fields}
    assert options == {"with_scheduling", "with_deck_configs", "with_media", "legacy"}


@pytest.mark.claim("APKG-COL-001")
@pytest.mark.claim("APKG-COL-002")
def test_collection_entry_by_version(conformance: Path) -> None:
    for case, version, package in packages(conformance):
        with zipfile.ZipFile(package) as archive:
            data = archive.read(ENTRY[version])
        if version == "v3":
            assert data[:4] == ZSTD_MAGIC, case
            assert data[:16] != SQLITE_MAGIC, case
        else:
            assert data[:16] == SQLITE_MAGIC, case
        assert collection_bytes(package)[:16] == SQLITE_MAGIC, case


@pytest.mark.claim("APKG-COL-003")
def test_placeholder_collection(conformance: Path) -> None:
    for case, _, package in packages(conformance):
        data = collection_bytes(package, "collection.anki2")
        assert data[:16] == SQLITE_MAGIC, case
        with open_db(data) as db:
            assert db.execute("select ver from col").fetchone() == (11,), case
            notes = db.execute("select flds from notes").fetchall()
        assert len(notes) == 1, case
        assert notes[0][0].startswith(PLACEHOLDER), case


@pytest.mark.claim("APKG-COL-004")
def test_schema_version_by_package_version(conformance: Path) -> None:
    for case, version, package in packages(conformance):
        with open_db(collection_bytes(package)) as db:
            (ver,) = db.execute("select ver from col").fetchone()
        assert ver == {"v2": 11, "v3": 18}[version], case


@pytest.mark.claim("APKG-COL-005")
def test_schema11_ids_may_be_strings(conformance: Path) -> None:
    case = conformance / "string-ids"
    with open_db(collection_bytes(case / "v2.apkg")) as db:
        models, decks = db.execute("select models, decks from col").fetchone()
    for entries in (json.loads(models), json.loads(decks)):
        assert all(isinstance(e["id"], str) and e["id"].isdigit() for e in entries.values())

    legacy, current = read_model(case / "v2.apkg"), read_model(case / "v3.apkg")
    legacy.pop("packageVersion"), current.pop("packageVersion")
    assert legacy == current
    assert {n["notetype"] for n in legacy["notes"]} == {"Basic"}
    assert {c["deck"] for c in legacy["cards"]} == {"string-ids", "string-ids::Child"}
