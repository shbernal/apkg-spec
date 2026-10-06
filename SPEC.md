# The Anki `.apkg` format

**Draft.** Describes the format as Anki 26.08.1 reads and writes it.

Anki publishes no specification of its package format. This document derives
one from the upstream source and checks each claim against the official Anki
library. Every normative statement carries an id such as `[APKG-COL-001]`.
`claims.yaml` lists each id with its upstream source, and a test in `tests/`
proves it. A statement without an id is explanation, not specification.

The key words MUST, SHOULD and MAY are used as in RFC 2119. A claim marked
OBSERVED in `claims.yaml` describes what current Anki does, with no promise
from upstream behind it.

## 1. Scope

An `.apkg` is a deck export: the notes of one or more decks, the cards, notetypes
and deck options they use, and the media they reference. A `.colpkg` is a whole
collection backup. It shares the container described in section 2 and is outside
this document.

The format is defined here as files on disk. Section 7 records the importer
behavior a writer depends on, and leaves everything else about import (merging
notetypes, scheduling options, conflict resolution) to Anki.

## 2. Container

An `.apkg` file is a zip archive [APKG-ZIP-001]. Its entries are the collection,
a `media` map, the media files, and usually a `meta` entry.

The package version decides how every other entry is read. A `meta` entry, when
present, holds a serialized `PackageMetadata` protobuf message whose `version`
field names the package version [APKG-VER-001]. A reader MUST read `meta` first:
Anki trusts it over the entries it finds. Without a `meta` entry, a package that
holds `collection.anki21` is version 2, and any other package is version 1
[APKG-VER-002].

Current Anki writes `meta` in both of its export modes: version 2 for a legacy
export ("support older Anki versions") and version 3 otherwise. It has no way to
write version 1 [APKG-VER-003], which comes from older clients and third-party
writers.

| version | collection entry       | encoding  | schema | `media` entry         |
| ------- | ---------------------- | --------- | ------ | --------------------- |
| 1       | `collection.anki2`     | SQLite    | 11     | JSON                  |
| 2       | `collection.anki21`    | SQLite    | 11     | JSON                  |
| 3       | `collection.anki21b`   | zstd      | 18     | zstd `MediaEntries`   |

## 3. The collection

The collection entry is `collection.anki2` in version 1, `collection.anki21` in
version 2 and `collection.anki21b` in version 3 [APKG-COL-001]. In version 3 it
is a zstd-compressed SQLite file. In versions 1 and 2 it is a plain SQLite file
[APKG-COL-002]. `col.ver` records the schema: 11 in versions 1 and 2, 18 in
version 3 [APKG-COL-004].

Version 2 and 3 packages written by current Anki also carry a schema 11
`collection.anki2` holding one placeholder note that asks the user to update
Anki [APKG-COL-003]. A client too old to know the newer entry imports that note
instead of failing. A reader MUST NOT take this entry for the real collection
when `meta` or `collection.anki21` is present.

Both schemas share the `notes`, `cards`, `revlog` and `graves` tables, with the
same columns. They differ in where notetypes, decks and deck options live.

### 3.1 Schema 11

The `col` table has a single row. Its text columns hold JSON:

- `models`: notetypes, keyed by id. Each has `name`, `type` (0 normal, 1 cloze),
  `flds` and `tmpls` (arrays ordered by `ord`; a field has `name`, a template has
  `name`, `qfmt` and `afmt`), `css`, `sortf` (the index of the sort field), and
  `did`, `mod`, `usn`, `req`, `latexPre`, `latexPost`.
- `decks`: decks, keyed by id. Each has `name` (levels joined by `::`), `desc`,
  `conf` (a key into `dconf`), `dyn`, and per-day counters.
- `dconf`: deck option presets, keyed by id, with `new`, `rev` and `lapse` objects.
- `conf`: collection settings.
- `tags`: unused in exports (`{}`).

### 3.2 Schema 18

The JSON columns of `col` are empty strings. The same data lives in tables whose
blobs are protobuf messages from Anki's `proto/anki/` definitions:

| table         | key           | payload                                        |
| ------------- | ------------- | ---------------------------------------------- |
| `notetypes`   | `id`, `name`  | `config`: `Notetype.Config` (kind, css, sort field) |
| `fields`      | `ntid`, `ord` | `name`, `config`: `Notetype.Field.Config`      |
| `templates`   | `ntid`, `ord` | `name`, `config`: `Notetype.Template.Config` (qfmt, afmt) |
| `decks`       | `id`, `name`  | `common`: `Deck.Common`, `kind`: `Deck.KindContainer` (description, preset) |
| `deck_config` | `id`, `name`  | `config`: `DeckConfig.Config`                  |
| `config`      | `KEY`         | `val`: JSON collection setting                 |
| `tags`        | `tag`         | one row per tag                                |

Deck names join their levels with U+001F rather than `::`. Name columns are
declared `COLLATE unicase`, a collation Anki registers itself: a reader that
opens the file with plain SQLite has to register one under that name before it
can query those tables.

## 4. Notes

Each row of `notes` is one note. `notes.flds` holds its field values in notetype
order, joined by U+001F [APKG-NOTE-001]. `notes.guid` identifies the note across
collections (section 7). Anki generates ten random characters, but any string
unique to the note is accepted.

Two columns are derived from the fields. `notes.sfld` is the sort field with HTML
stripped and media filenames kept, so `<img src="a.png">` sorts as ` a.png `
[APKG-NOTE-003]. Entities are decoded and whitespace is not trimmed. The column has
integer affinity, so a numeric sort field reads back as an integer. `notes.csum`
is the first 8 hex digits of the sha1 of the first field, stripped the same way,
read as an integer [APKG-NOTE-002]. A writer SHOULD compute both. Anki recomputes
`csum` on import (section 7) and the browser sorts on `sfld`.

`notes.id` and `cards.id` are milliseconds since the epoch. `notes.mod` and
`cards.mod` are seconds [APKG-NOTE-004]. `notes.tags` holds the tags separated by
single spaces, with one leading and one trailing space, and is empty for a note
without tags [APKG-NOTE-005].

## 5. Cards

Each row of `cards` is one card of note `nid`, generated by template `ord`. A
normal notetype gives one card per template whose question renders non-empty. A
cloze notetype gives one card per cloze number, with `ord` the number minus one.
`did` is the card's deck.

`cards.queue` is -3 for a manually buried card, -2 for a card the scheduler buried
(a sibling), -1 for a suspended card, 0 new, 1 learning, 2 review and 3 learning
counted in days [APKG-CARD-002]. `cards.type` is 0 new, 1 learning, 2 review or 3
relearning, and keeps its value while the card is buried or suspended.

`cards.due` depends on the queue. For a new card it is its 1-based position in
the new queue, which siblings share [APKG-CARD-001]. For a review or day-learning
card it is a day number counted from the collection's creation. For an intraday
learning card it is a timestamp in seconds. `ivl` is the interval in days and
`factor` the ease in permille.

## 6. Media

Media files are stored under zip entry names that are decimal integers, never
under their real filenames [APKG-MED-001]. The `media` entry maps them back.

In versions 1 and 2 the `media` entry is a JSON object that maps each zip entry
name to a filename [APKG-MED-002]. In version 3 it is a zstd-compressed
`MediaEntries` message. The position of an entry in `entries` is its zip entry
name, and each entry carries the filename, size and sha1 [APKG-MED-003]. Each
media file in a version 3 package is zstd-compressed on its own [APKG-MED-004],
and `size` and `sha1` describe the decompressed bytes.

An export includes only the media files that the exported notes reference
[APKG-MED-005], through `<img src>`, `[sound:…]` and similar references in field
values. A reference may have no file behind it: Anki exports and imports such a
note, and only a media check reports the file missing [APKG-MED-006]. A reader
SHOULD tolerate it, and a writer SHOULD pass the reference through rather than
fail or drop it.

## 7. Import behavior

Import matches notes by guid, so a second import of the same package adds no
notes [APKG-IMP-001]. A writer that wants re-exports to update rather than
duplicate notes MUST keep guids stable.

Import recomputes `csum` and does not reject a package whose stored checksums are
wrong [APKG-IMP-002]. It rejects a note whose field count differs from the field
count of its notetype [APKG-IMP-003]. Anki raises an error and imports nothing
from the package.

## 8. The canonical model

`model.schema.json` defines what a package holds once ids, clocks, package
version and schema version are set aside. Two packages with equal models hold
the same deck. The eval compares models, never bytes.
