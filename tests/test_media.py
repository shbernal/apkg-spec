from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

import pytest
from anki.collection import DeckIdLimit
from anki.import_export_pb2 import ExportAnkiPackageOptions, MediaEntries
from apkg import fresh_collection, import_package, packages
from model import unzstd

FIXED = {"meta", "media", "collection.anki2", "collection.anki21", "collection.anki21b"}
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def committed_media(package: Path) -> dict[str, str]:
    """Filename -> sha1, as the conformance case's model records it."""
    return json.loads((package.parent / "model.json").read_text())["media"]


@pytest.mark.claim("APKG-MED-001")
def test_media_entries_are_decimal_integers(conformance: Path) -> None:
    for case, _, package in packages(conformance):
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist()) - FIXED
        assert all(re.fullmatch(r"0|[1-9][0-9]*", n) for n in names), case
        assert not names & set(committed_media(package)), case
        assert len(names) == len(committed_media(package)), case


@pytest.mark.claim("APKG-MED-002")
def test_legacy_media_map_is_json(conformance: Path) -> None:
    for case, version, package in packages(conformance):
        if version != "v2":
            continue
        with zipfile.ZipFile(package) as archive:
            mapping = json.loads(archive.read("media"))
            files = {
                name: hashlib.sha1(archive.read(entry)).hexdigest()
                for entry, name in mapping.items()
            }
        assert isinstance(mapping, dict), case
        assert files == committed_media(package), case


@pytest.mark.claim("APKG-MED-003")
@pytest.mark.claim("APKG-MED-004")
def test_media_entries_message(conformance: Path) -> None:
    for case, version, package in packages(conformance):
        if version != "v3":
            continue
        with zipfile.ZipFile(package) as archive:
            raw = archive.read("media")
            assert raw[:4] == ZSTD_MAGIC, case
            entries = MediaEntries()
            entries.ParseFromString(unzstd(raw))
            files = {}
            for position, entry in enumerate(entries.entries):
                stored = archive.read(str(position))
                assert stored[:4] == ZSTD_MAGIC, case
                data = unzstd(stored)
                assert entry.size == len(data), case
                assert entry.sha1 == hashlib.sha1(data).digest(), case
                files[entry.name] = entry.sha1.hex()
        assert files == committed_media(package), case


@pytest.mark.claim("APKG-MED-005")
@pytest.mark.parametrize("legacy", [True, False])
def test_export_includes_only_referenced_media(tmp_path: Path, legacy: bool) -> None:
    with fresh_collection() as col:
        for name in ("used.png", "sound.mp3", "unused.png"):
            col.media.write_data(name, name.encode() * 4)
        deck = col.decks.id("Media")
        note = col.new_note(col.models.by_name("Basic"))
        note.fields = ['<img src="used.png">', "[sound:sound.mp3]"]
        col.add_note(note, deck)
        out = tmp_path / "out.apkg"
        col.export_anki_package(
            out_path=str(out),
            options=ExportAnkiPackageOptions(with_media=True, legacy=legacy),
            limit=DeckIdLimit(deck),
        )
    with zipfile.ZipFile(out) as archive:
        raw = archive.read("media")
    if legacy:
        names = set(json.loads(raw).values())
    else:
        entries = MediaEntries()
        entries.ParseFromString(unzstd(raw))
        names = {e.name for e in entries.entries}
    assert names == {"used.png", "sound.mp3"}


@pytest.mark.claim("APKG-MED-006")
@pytest.mark.parametrize("version", ["v2", "v3"])
def test_reference_without_file(conformance: Path, version: str) -> None:
    package = conformance / "missing-media" / f"{version}.apkg"
    assert set(committed_media(package)) == {"present.png"}
    with fresh_collection() as col:
        log = import_package(col, package)
        assert len(log.new) == 1
        assert not log.conflicting and not log.missing_notetype and not log.missing_deck
        assert set(col.media.check().missing) == {"absent.png", "cmn-缺.mp3"}
