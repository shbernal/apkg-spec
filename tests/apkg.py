"""Helpers the claim tests share: open a package's collection, rewrite a package, import one."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anki.collection import Collection
from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest
from model import unzstd

ENTRY = {"v2": "collection.anki21", "v3": "collection.anki21b"}
VERSIONS = tuple(ENTRY)


def cases(conformance: Path) -> list[Path]:
    return sorted(p for p in conformance.iterdir() if p.is_dir())


def packages(conformance: Path) -> Iterator[tuple[str, str, Path]]:
    """(case, version, package) for every committed package."""
    for case in cases(conformance):
        for version in VERSIONS:
            yield case.name, version, case / f"{version}.apkg"


def collection_bytes(package: Path, entry: str | None = None) -> bytes:
    with zipfile.ZipFile(package) as archive:
        name = entry or next(e for e in ENTRY.values() if e in archive.namelist())
        data = archive.read(name)
    return unzstd(data) if name == "collection.anki21b" else data


@contextmanager
def open_db(data: bytes) -> Iterator[sqlite3.Connection]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "collection.db"
        path.write_bytes(data)
        db = sqlite3.connect(path)
        # Schema 18 declares names `collate unicase`, an Anki-defined collation.
        db.create_collation(
            "unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold())
        )
        try:
            yield db
        finally:
            db.close()


def rewrite(
    src: Path, dst: Path, drop: tuple[str, ...] = (), replace: dict[str, bytes] | None = None
) -> Path:
    """Copy a package, leaving out `drop` and swapping in `replace` entries."""
    replace = replace or {}
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if info.filename not in drop:
                zout.writestr(info.filename, replace.get(info.filename, zin.read(info.filename)))
        for name, data in replace.items():
            if name not in zin.namelist():
                zout.writestr(name, data)
    return dst


def tamper(data: bytes, sql: str) -> bytes:
    """Run `sql` against a plain SQLite collection and return the result."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "collection.db"
        path.write_bytes(data)
        db = sqlite3.connect(path)
        db.executescript(sql)
        db.commit()
        db.close()
        return path.read_bytes()


def import_package(col: Collection, package: Path):
    return col.import_anki_package(
        ImportAnkiPackageRequest(
            package_path=str(package),
            options=ImportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True),
        )
    ).log


@contextmanager
def fresh_collection() -> Iterator[Collection]:
    with tempfile.TemporaryDirectory() as tmp:
        col = Collection(str(Path(tmp) / "collection.anki2"))
        try:
            yield col
        finally:
            col.close()
