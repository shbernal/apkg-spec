// Map the canonical model in model.schema.json onto @shbernal/anki-apkg-export's
// writer.
//
//   node adapters/anki-apkg-export/write.mjs <model.json> <media dir> <out.apkg> --version <n>
//
// The model keys everything by name or guid; the writer wants ids, so each
// entity gets one here, counted up from a fixed instant.
// ANKI_APKG_EXPORT points at the package checkout; the sibling repo by default.
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";

const root =
  process.env.ANKI_APKG_EXPORT ?? path.resolve(import.meta.dirname, "../../../anki-apkg-export");
const { writeApkg } = await import(pathToFileURL(path.join(root, "dist/index.js")).href);

const {
  positionals: [modelPath, mediaDir, output],
  values: { version },
} = parseArgs({ allowPositionals: true, options: { version: { type: "string", default: "2" } } });

const model = JSON.parse(readFileSync(modelPath, "utf8"));
const now = 1_700_000_000_000;
let next = now;
const id = () => next++;

const notetypeIds = new Map(model.notetypes.map((nt) => [nt.name, id()]));
const noteIds = new Map(model.notes.map((n) => [n.guid, id()]));
const deckIds = new Map(model.decks.map((d) => [d.name, id()]));

const pkg = await writeApkg(
  {
    notetypes: model.notetypes.map((nt) => ({
      id: notetypeIds.get(nt.name),
      name: nt.name,
      isCloze: nt.kind === "cloze",
      fields: nt.fields,
      templates: nt.templates,
      css: nt.css,
      sortField: nt.sortField,
    })),
    notes: model.notes.map((n) => ({
      id: noteIds.get(n.guid),
      guid: n.guid,
      mid: notetypeIds.get(n.notetype),
      fields: n.fields,
      tags: n.tags,
    })),
    cards: model.cards.map((c) => ({
      id: id(),
      nid: noteIds.get(c.note),
      did: deckIds.get(c.deck),
      ord: c.ord,
      type: c.type,
      queue: c.queue,
      due: c.due,
      ivl: c.ivl,
      factor: c.factor,
      reps: c.reps,
      lapses: c.lapses,
    })),
    decks: model.decks.map((d) => ({ id: deckIds.get(d.name), ...d })),
    media: new Map(
      Object.keys(model.media).map((name) => [name, readFileSync(path.join(mediaDir, name))]),
    ),
  },
  { packageVersion: Number(version), now },
);
writeFileSync(output, pkg);
