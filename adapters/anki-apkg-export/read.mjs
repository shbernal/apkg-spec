// Map @shbernal/anki-apkg-export's reader onto the canonical model in
// model.schema.json. A field the reader does not expose is left out, and the
// eval scores that section as a miss: the gap is the finding.
//
//   node adapters/anki-apkg-export/read.mjs <package.apkg>
//
// ANKI_APKG_EXPORT points at the package checkout; the sibling repo by default.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root =
  process.env.ANKI_APKG_EXPORT ?? path.resolve(import.meta.dirname, "../../../anki-apkg-export");
const { readApkg } = await import(pathToFileURL(path.join(root, "dist/index.js")).href);

const pkg = await readApkg(readFileSync(process.argv[2]));
const names = new Map(pkg.notetypes.map((nt) => [nt.id, nt.name]));
const used = new Set(pkg.notes.map((n) => n.mid));
const byName = (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);

const model = {
  notetypes: pkg.notetypes
    .filter((nt) => used.has(nt.id))
    .map((nt) => ({
      name: nt.name,
      kind: nt.isCloze ? "cloze" : "normal",
      fields: [...nt.fields],
      ...(nt.templates && { templates: nt.templates }),
      ...(nt.css !== undefined && { css: nt.css }),
      ...(nt.sortField !== undefined && { sortField: nt.sortField }),
    }))
    .sort(byName),
  notes: pkg.notes
    .map((n) => ({
      guid: n.guid,
      notetype: names.get(n.mid),
      fields: [...n.fields],
      tags: [...n.tags].sort(),
    }))
    .sort((a, b) => (a.guid < b.guid ? -1 : a.guid > b.guid ? 1 : 0)),
  ...(pkg.cards && { cards: pkg.cards }),
  ...(pkg.decks && { decks: pkg.decks }),
  media: Object.fromEntries(
    [...pkg.media.entries()]
      .map(([name, data]) => [name, createHash("sha1").update(data).digest("hex")])
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
  ),
};
process.stdout.write(JSON.stringify(model));
