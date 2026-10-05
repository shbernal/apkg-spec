from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

import pytest
from apkg import collection_bytes, open_db, packages

# 2001-09-09 .. 2286-11-20 in seconds; the same span in milliseconds starts at 1e12.
SECONDS = range(10**9, 10**10)
MILLISECONDS = range(10**12, 10**13)


def strip(text: str) -> str:
    """HTML stripped, an <img>'s filename kept, entities decoded, whitespace left alone."""
    text = re.sub(r"""<img[^>]*src=["']?([^"'>]+)["']?[^>]*>""", r" \1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", "", text)
    return html.unescape(text.replace("&nbsp;", " "))


def sort_fields(package: Path) -> dict[str, int]:
    """guid -> index of its notetype's sort field."""
    model = json.loads((package.parent / "model.json").read_text())
    sortf = {nt["name"]: nt["sortField"] for nt in model["notetypes"]}
    return {n["guid"]: sortf[n["notetype"]] for n in model["notes"]}


@pytest.mark.claim("APKG-NOTE-001")
def test_fields_are_joined_by_unit_separator(conformance: Path) -> None:
    for version in ("v2", "v3"):
        package = conformance / "custom-notetype" / f"{version}.apkg"
        with open_db(collection_bytes(package)) as db:
            flds = dict(db.execute("select guid, flds from notes"))
            if version == "v2":
                (models,) = db.execute("select models from col").fetchone()
                (vocab,) = [m for m in json.loads(models).values() if m["name"] == "Vocabulary"]
                names = [f["name"] for f in sorted(vocab["flds"], key=lambda f: f["ord"])]
            else:
                names = [
                    name
                    for (name,) in db.execute(
                        "select f.name from fields f join notetypes n on n.id = f.ntid"
                        " where n.name = 'Vocabulary' order by f.ord"
                    )
                ]
        assert names == ["Word", "Meaning", "Example"], version
        assert flds["custom-notetype-0"] == "laconic\x1fusing few words\x1fa laconic reply"
        assert flds["custom-notetype-1"] == "ephemeral\x1flasting a very short time\x1f"


@pytest.mark.claim("APKG-NOTE-002")
def test_checksum_of_stripped_first_field(conformance: Path) -> None:
    for case, _, package in packages(conformance):
        with open_db(collection_bytes(package)) as db:
            for flds, csum in db.execute("select flds, csum from notes"):
                first = strip(flds.split("\x1f")[0])
                assert csum == int(hashlib.sha1(first.encode()).hexdigest()[:8], 16), case


@pytest.mark.claim("APKG-NOTE-003")
def test_sort_field_is_stripped(conformance: Path) -> None:
    seen_media = False
    for case, _, package in packages(conformance):
        sortf = sort_fields(package)
        with open_db(collection_bytes(package)) as db:
            for guid, flds, sfld in db.execute("select guid, flds, sfld from notes"):
                source = flds.split("\x1f")[sortf[guid]]
                assert str(sfld) == strip(source), (case, guid)
                seen_media |= "<img" in source
    assert seen_media, "no sort field holds an image"


@pytest.mark.claim("APKG-NOTE-004")
def test_id_and_mod_units(conformance: Path) -> None:
    for case, _, package in packages(conformance):
        with open_db(collection_bytes(package)) as db:
            rows = db.execute("select id, mod from notes union all select id, mod from cards")
            for id_, mod in rows:
                assert id_ in MILLISECONDS and mod in SECONDS, case
                # Both come from the clock of the same session.
                assert abs(id_ // 1000 - mod) < 3600, case


@pytest.mark.claim("APKG-NOTE-005")
def test_tags_are_space_padded(conformance: Path) -> None:
    package = conformance / "tags" / "v3.apkg"
    with open_db(collection_bytes(package)) as db:
        tags = dict(db.execute("select guid, tags from notes"))
    assert tags == {"tags-0": " lang::fr lang::fr::verbs ", "tags-1": " Mixed_Case über 日本語 "}
    for case, _, package in packages(conformance):
        with open_db(collection_bytes(package)) as db:
            for (value,) in db.execute("select tags from notes where tags != ''"):
                assert re.fullmatch(r" (\S+ )+", value), (case, value)
