// Map @shbernal/anki-apkg-export's reader onto the canonical model in
// model.schema.json.
//
//   node adapters/anki-apkg-export/read.mjs <package.apkg>
//
// The npm package by default; ANKI_APKG_EXPORT points at a built checkout instead.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const checkout = process.env.ANKI_APKG_EXPORT;
const { readApkg } = await import(
  checkout
    ? pathToFileURL(path.join(checkout, "dist/index.js")).href
    : "@shbernal/anki-apkg-export"
);

const pkg = await readApkg(readFileSync(process.argv[2]));
const names = new Map(pkg.notetypes.map((nt) => [nt.id, nt.name]));
const guids = new Map(pkg.notes.map((n) => [n.id, n.guid]));
const deckNames = new Map(pkg.decks.map((d) => [d.id, d.name]));
const used = new Set(pkg.notes.map((n) => n.mid));
const usedDecks = new Set(pkg.cards.map((c) => c.did));
const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const byName = (a, b) => compare(a.name, b.name);

const model = {
  notetypes: pkg.notetypes
    .filter((nt) => used.has(nt.id))
    .map((nt) => ({
      name: nt.name,
      kind: nt.isCloze ? "cloze" : "normal",
      fields: [...nt.fields],
      templates: nt.templates.map(({ name, qfmt, afmt }) => ({ name, qfmt, afmt })),
      css: nt.css,
      sortField: nt.sortField,
      latexPre: nt.latexPre,
      latexPost: nt.latexPost,
      latexSvg: nt.latexSvg,
    }))
    .sort(byName),
  notes: pkg.notes
    .map((n) => ({
      guid: n.guid,
      notetype: names.get(n.mid),
      fields: [...n.fields],
      tags: [...n.tags].sort(),
    }))
    .sort((a, b) => compare(a.guid, b.guid)),
  cards: pkg.cards
    .map((c) => ({
      note: guids.get(c.nid),
      ord: c.ord,
      deck: deckNames.get(c.did),
      type: c.type,
      queue: c.queue,
      due: c.due,
      ivl: c.ivl,
      factor: c.factor,
      reps: c.reps,
      lapses: c.lapses,
    }))
    .sort((a, b) => compare(a.note, b.note) || a.ord - b.ord),
  decks: pkg.decks
    .filter((d) => usedDecks.has(d.id))
    .map(({ name, description }) => ({ name, description }))
    .sort(byName),
  media: Object.fromEntries(
    [...pkg.media.entries()]
      .map(([name, data]) => [name, createHash("sha1").update(data).digest("hex")])
      .sort(([a], [b]) => compare(a, b)),
  ),
};
process.stdout.write(JSON.stringify(model));
