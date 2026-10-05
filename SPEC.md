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

<!-- TODO: what a package is (a deck export) versus a .colpkg (a whole collection); what this document leaves to the importer's behavior. -->

## 2. Container

<!-- APKG-ZIP-001, APKG-VER-001..003 -->

## 3. The collection

<!-- APKG-COL-001..004; schema 11 versus schema 18; the stub collection. -->

### 3.1 Schema 11

<!-- The five tables; the JSON blobs in `col`; the models, decks and dconf JSON shapes. -->

### 3.2 Schema 18

<!-- The notetypes, fields, templates, decks and deck_config tables; their protobuf payloads. -->

## 4. Notes

<!-- APKG-NOTE-001..005; guid format; derived fields. -->

## 5. Cards

<!-- APKG-CARD-001..002; type, queue, due by queue; how cards are generated from templates and cloze numbers. -->

## 6. Media

<!-- APKG-MED-001..005 -->

## 7. Import behavior

<!-- APKG-IMP-001..003; what import repairs and what it keeps. -->

## 8. The canonical model

`model.schema.json` defines what a package holds once ids, clocks, package
version and schema version are set aside. Two packages with equal models hold
the same deck. The eval compares models, never bytes.
