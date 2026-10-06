"""Generate the conformance corpus in `conformance/` with the official Anki library.

Each case is one feature. For each, the same collection is exported twice:

    conformance/<case>/v2.apkg      legacy export: package v2, schema 11
    conformance/<case>/v3.apkg      current export: package v3, schema 18
    conformance/<case>/model.json   the canonical model both packages hold

Guids are set from the case name, so `model.json` is stable across runs. The
package bytes are not, because ids come from the clock.

    uv run oracle/fixtures.py           # regenerate
    uv run oracle/fixtures.py --check   # fail if a regenerated model differs
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable
from pathlib import Path

from anki.collection import Collection, DeckIdLimit
from anki.import_export_pb2 import ExportAnkiPackageOptions
from model import read_model

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "conformance"


def png(rgb: tuple[int, int, int]) -> bytes:
    pixels = b"".join(b"\x00" + bytes(rgb) * 2 for _ in range(2))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class Builder:
    def __init__(self, col: Collection, case: str) -> None:
        self.col = col
        self.case = case
        self.count = 0
        self.deck = col.decks.id(case)

    def note(
        self,
        notetype: str,
        fields: list[str],
        tags: list[str] | None = None,
        deck: str | None = None,
    ) -> int:
        model = self.col.models.by_name(notetype)
        assert model is not None, notetype
        note = self.col.new_note(model)
        for i, value in enumerate(fields):
            note.fields[i] = value
        note.tags = tags or []
        note.guid = f"{self.case}-{self.count}"
        self.count += 1
        self.col.add_note(note, self.col.decks.id(deck) if deck else self.deck)
        return note.id


def basic(b: Builder) -> None:
    b.note("Basic", ["What is the capital of France?", "Paris"], ["geo"])
    b.note("Basic", ["2 + 2", "4"])


def reversed_cards(b: Builder) -> None:
    b.note("Basic (and reversed card)", ["chien", "dog"], ["french"])
    b.note("Basic (optional reversed card)", ["chat", "cat", "y"])
    b.note("Basic (optional reversed card)", ["oiseau", "bird", ""])


def type_in(b: Builder) -> None:
    b.note("Basic (type in the answer)", ["Chemical symbol for gold", "Au"])


def cloze(b: Builder) -> None:
    b.note("Cloze", ["{{c1::Ottawa}} is the capital of {{c2::Canada}}.", ""])
    b.note("Cloze", ["{{c1::H}}{{c1::2}}O and {{c3::NaCl::salt}}", "chemistry"], ["chem"])


def custom_notetype(b: Builder) -> None:
    mm = b.col.models
    nt = mm.new("Vocabulary")
    for name in ("Word", "Meaning", "Example"):
        mm.add_field(nt, mm.new_field(name))
    for name, q, a in (
        ("Recognize", "{{Word}}", "{{FrontSide}}<hr id=answer>{{Meaning}}<br>{{Example}}"),
        ("Recall", "{{Meaning}}", "{{FrontSide}}<hr id=answer>{{Word}}"),
    ):
        t = mm.new_template(name)
        t["qfmt"], t["afmt"] = q, a
        mm.add_template(nt, t)
    nt["css"] = ".card { font-family: serif; }"
    nt["sortf"] = 1
    mm.add(nt)
    b.note("Vocabulary", ["laconic", "using few words", "a laconic reply"])
    b.note("Vocabulary", ["ephemeral", "lasting a very short time", ""])


def media(b: Builder) -> None:
    files = {
        "red.png": png((255, 0, 0)),
        "green dot.png": png((0, 255, 0)),
        "café.png": png((0, 0, 255)),
        "tone.mp3": b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(64),
    }
    for name, data in files.items():
        b.col.media.write_data(name, data)
    b.note("Basic", ['<img src="red.png">', '<img src="green dot.png">'])
    b.note("Basic", ['<img src="café.png">', "[sound:tone.mp3]"])


def missing_media(b: Builder) -> None:
    b.col.media.write_data("present.png", png((0, 0, 0)))
    b.note("Basic", ['<img src="present.png"> <img src="absent.png">', "[sound:cmn-缺.mp3]"])


def latex(b: Builder) -> None:
    mm = b.col.models
    nt = mm.copy(mm.by_name("Basic"), add=False)
    nt["name"] = "LaTeX SVG"
    nt["latexPre"] = "\\documentclass{article}\\usepackage{amsmath}\\begin{document}"
    nt["latexPost"] = "\\end{document}"
    nt["latexsvg"] = True
    mm.add(nt)
    b.note("Basic", ["[latex]x^2[/latex]", "png"])
    b.note("LaTeX SVG", ["[$]\\sqrt{2}[/$]", "svg"])
    # Stand-ins for rendered images, under the names Anki looks for.
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    for name in b.col.media.check().missing:
        b.col.media.write_data(name, svg if name.endswith(".svg") else png((0, 0, 0)))


def text_edge_cases(b: Builder) -> None:
    b.note("Basic", ["emoji 🦊 and CJK 今日", "RTL مرحبا"])
    b.note("Basic", ["&lt;b&gt; &amp; &nbsp;", "line<br>break\nnewline"])
    b.note("Basic", ["<b>bold</b> <i>it</i> <span style='color:red'>c</span>", "  spaces  "])
    b.note("Basic", ["back left empty", ""])


def decks(b: Builder) -> None:
    child = b.col.decks.id(f"{b.case}::Child::Grandchild")
    deck = b.col.decks.get(child)
    assert deck is not None
    deck["desc"] = "A <b>nested</b> deck."
    b.col.decks.save(deck)
    b.note("Basic", ["in parent", "p"])
    b.note("Basic", ["in grandchild", "g"], deck=f"{b.case}::Child::Grandchild")


def tags(b: Builder) -> None:
    b.note("Basic", ["hierarchical", "t"], ["lang::fr::verbs", "lang::fr"])
    b.note("Basic", ["unicode", "t"], ["日本語", "über", "Mixed_Case"])


def scheduling(b: Builder) -> None:
    ids = [b.note("Basic", [f"card {i}", str(i)]) for i in range(5)]
    cards = [b.col.get_note(nid).cards()[0] for nid in ids]
    sched = b.col.sched
    sched.set_due_date([cards[0].id], "3")  # review, due in 3 days
    sched.set_due_date([cards[1].id], "10!")  # review, interval set to 10
    sched.suspend_cards([cards[2].id])
    sched.bury_cards([cards[3].id])
    # cards[4] stays new


def many_notes(b: Builder) -> None:
    for i in range(300):
        b.note("Basic", [f"front {i:03}", f"back {i:03}"], [f"batch{i // 100}"])


CASES: dict[str, Callable[[Builder], None]] = {
    "basic": basic,
    "reversed-cards": reversed_cards,
    "type-in": type_in,
    "cloze": cloze,
    "custom-notetype": custom_notetype,
    "media": media,
    "missing-media": missing_media,
    "latex": latex,
    "text-edge-cases": text_edge_cases,
    "decks": decks,
    "tags": tags,
    "scheduling": scheduling,
    "many-notes": many_notes,
}


def export(col: Collection, deck: str, out: Path, *, legacy: bool) -> None:
    col.export_anki_package(
        out_path=str(out),
        options=ExportAnkiPackageOptions(
            with_scheduling=True, with_deck_configs=True, with_media=True, legacy=legacy
        ),
        limit=DeckIdLimit(col.decks.id(deck)),
    )


def generate(case: str, target: Path) -> dict:
    tmp = Path(tempfile.mkdtemp())
    try:
        col = Collection(str(tmp / "collection.anki2"))
        CASES[case](Builder(col, case))
        target.mkdir(parents=True, exist_ok=True)
        export(col, case, target / "v2.apkg", legacy=True)
        export(col, case, target / "v3.apkg", legacy=False)
        col.close()
        models = [read_model(target / f"{v}.apkg") for v in ("v2", "v3")]
        for m in models:
            m.pop("packageVersion")
        if models[0] != models[1]:
            raise SystemExit(f"{case}: v2 and v3 exports hold different models")
        return models[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("cases", nargs="*", default=list(CASES))
    args = parser.parse_args()

    stale = []
    for case in args.cases:
        if args.check:
            scratch = Path(tempfile.mkdtemp())
            model = generate(case, scratch)
            shutil.rmtree(scratch)
            committed = json.loads((OUT / case / "model.json").read_text())
            if committed != model:
                stale.append(case)
            print(f"{case:18} {'STALE' if case in stale else 'ok'}")
            continue
        model = generate(case, OUT / case)
        (OUT / case / "model.json").write_text(
            json.dumps(model, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"{case:18} {len(model['notes']):>4} notes {len(model['cards']):>4} cards")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
