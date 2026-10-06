"""The canonical model of an `.apkg`, as the official Anki library reads it.

Every eval compares models, never bytes. Ids and timestamps come from a clock,
so the model keys notes on their guid, notetypes and decks on their name, and
media on its filename, with the sha1 of its bytes as the value.

`model.schema.json` at the repository root is the contract an implementation's
`read` command has to meet. This module is the reference for it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import anki.lang

anki.lang.set_lang("en_US")

from anki.collection import Collection
from anki.import_export_pb2 import (
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
    MediaEntries,
    PackageMetadata,
)
from anki.models import MODEL_CLOZE

SECTIONS = ("notetypes", "notes", "cards", "decks", "media")

# Collection entries by package version. A v2 and v3 package also carry a stub
# `collection.anki2`; reading that one gets you the "please upgrade" note.
COLLECTION_ENTRY = {1: "collection.anki2", 2: "collection.anki21", 3: "collection.anki21b"}


def unzstd(data: bytes) -> bytes:
    import zstandard

    return zstandard.ZstdDecompressor().decompressobj().decompress(data)


def package_version(archive: zipfile.ZipFile) -> int:
    names = set(archive.namelist())
    if "meta" in names:
        meta = PackageMetadata()
        meta.ParseFromString(archive.read("meta"))
        return int(meta.version)
    return 2 if "collection.anki21" in names else 1


def media_map(archive: zipfile.ZipFile, version: int) -> dict[str, str]:
    """Zip entry name -> media filename."""
    if "media" not in archive.namelist():
        return {}
    raw = archive.read("media")
    if version < 3:
        return {str(k): str(v) for k, v in json.loads(raw or b"{}").items()}
    entries = MediaEntries()
    entries.ParseFromString(unzstd(raw))
    return {
        str(e.legacy_zip_filename if e.HasField("legacy_zip_filename") else i): e.name
        for i, e in enumerate(entries.entries)
    }


def read_media(package: Path) -> dict[str, bytes]:
    """Media filename -> its bytes, decompressed."""
    with zipfile.ZipFile(package) as archive:
        version = package_version(archive)
        media: dict[str, bytes] = {}
        for entry, name in media_map(archive, version).items():
            blob = archive.read(entry)
            media[name] = unzstd(blob) if version == 3 else blob
        return media


def read_model(package: Path) -> dict[str, Any]:
    """Open the package's collection directly, without an import in between."""
    tmp = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(package) as archive:
            version = package_version(archive)
            data = archive.read(COLLECTION_ENTRY[version])
            if version == 3:
                data = unzstd(data)
        media = {name: hashlib.sha1(blob).hexdigest() for name, blob in read_media(package).items()}
        path = tmp / "collection.anki2"
        path.write_bytes(data)
        col = Collection(str(path))
        try:
            model = collection_model(col)
        finally:
            col.close(downgrade=False)
        model["media"] = dict(sorted(media.items()))
        return {"packageVersion": version, **model}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def collection_model(col: Collection) -> dict[str, Any]:
    notetypes = []
    names_by_id: dict[int, str] = {}
    for entry in col.models.all_names_and_ids():
        nt = col.models.get(entry.id)
        assert nt is not None
        names_by_id[entry.id] = nt["name"]
        notetypes.append(
            {
                "name": nt["name"],
                "kind": "cloze" if nt["type"] == MODEL_CLOZE else "normal",
                "fields": [f["name"] for f in nt["flds"]],
                "templates": [
                    {"name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]} for t in nt["tmpls"]
                ],
                "css": nt["css"],
                "sortField": nt["sortf"],
            }
        )

    used_notetypes = {mid for (mid,) in col.db.all("select distinct mid from notes")}
    notetypes = [nt for nt in notetypes if nt["name"] in {names_by_id[m] for m in used_notetypes}]

    notes = []
    guid_by_nid: dict[int, str] = {}
    for nid, guid, mid, flds, tags in col.db.all("select id, guid, mid, flds, tags from notes"):
        guid_by_nid[nid] = guid
        notes.append(
            {
                "guid": guid,
                "notetype": names_by_id[mid],
                "fields": flds.split("\x1f"),
                "tags": sorted(t for t in tags.split(" ") if t),
            }
        )

    deck_names = {d.id: d.name for d in col.decks.all_names_and_ids()}
    cards = []
    used_decks: set[int] = set()
    for nid, did, ord_, ctype, queue, due, ivl, factor, reps, lapses in col.db.all(
        "select nid, did, ord, type, queue, due, ivl, factor, reps, lapses from cards"
    ):
        used_decks.add(did)
        cards.append(
            {
                "note": guid_by_nid[nid],
                "ord": ord_,
                "deck": deck_names[did],
                "type": ctype,
                "queue": queue,
                "due": due,
                "ivl": ivl,
                "factor": factor,
                "reps": reps,
                "lapses": lapses,
            }
        )

    decks = []
    for did in sorted(used_decks, key=lambda d: deck_names[d]):
        deck = col.decks.get(did)
        assert deck is not None
        decks.append({"name": deck["name"], "description": deck.get("desc", "")})

    return {
        "notetypes": sorted(notetypes, key=lambda n: n["name"]),
        "notes": sorted(notes, key=lambda n: n["guid"]),
        "cards": sorted(cards, key=lambda c: (c["note"], c["ord"])),
        "decks": decks,
    }


def acceptance_problems(package: Path) -> list[str]:
    """Import into a fresh collection the way the desktop app does.

    Empty when Anki takes the package cleanly. This proves Anki accepts the
    file; it does not prove the bytes are right. `read_model` covers that.
    """
    tmp = Path(tempfile.mkdtemp())
    col = Collection(str(tmp / "collection.anki2"))
    problems: list[str] = []
    try:
        try:
            log = col.import_anki_package(
                ImportAnkiPackageRequest(
                    package_path=str(package),
                    options=ImportAnkiPackageOptions(
                        merge_notetypes=False, with_scheduling=True, with_deck_configs=True
                    ),
                )
            ).log
        except Exception as error:  # noqa: BLE001 - any failure is the finding
            return [f"import raised {type(error).__name__}: {error}"]
        for field in ("conflicting", "missing_notetype", "missing_deck", "empty_first_field"):
            if entries := getattr(log, field):
                problems.append(f"import log: {len(entries)} {field}")
        if not log.found_notes:
            problems.append("import found no notes")
        _, ok = col.fix_integrity()
        if not ok:
            problems.append("check database reported problems")
        problems.extend(f"missing media: {name}" for name in col.media.check().missing)
        return problems
    finally:
        col.close()
        shutil.rmtree(tmp, ignore_errors=True)


def diff(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, str | None]:
    """Per section: None when equal, else a short reason."""
    out: dict[str, str | None] = {}
    for section in SECTIONS:
        want, got = expected.get(section), actual.get(section)
        if got is None:
            out[section] = "missing"
        elif want == got:
            out[section] = None
        else:
            out[section] = first_difference(want, got, section)
    return out


def first_difference(want: Any, got: Any, path: str) -> str:
    if type(want) is not type(got):
        return f"{path}: expected {type(want).__name__}, got {type(got).__name__}"
    if isinstance(want, dict):
        for key in sorted(set(want) | set(got)):
            if key not in got:
                return f"{path}.{key}: missing"
            if key not in want:
                return f"{path}.{key}: unexpected"
            if want[key] != got[key]:
                return first_difference(want[key], got[key], f"{path}.{key}")
    if isinstance(want, list):
        if len(want) != len(got):
            return f"{path}: expected {len(want)} items, got {len(got)}"
        for i, (w, g) in enumerate(zip(want, got, strict=True)):
            if w != g:
                return first_difference(w, g, f"{path}[{i}]")
    return f"{path}: expected {want!r:.80}, got {got!r:.80}"


if __name__ == "__main__":
    import sys

    print(json.dumps(read_model(Path(sys.argv[1])), indent=2, ensure_ascii=False))
