# AI project guidelines

`apkg-spec`: a specification of the Anki `.apkg` format, the conformance corpus that proves it, and an eval harness that scores implementations against the official Anki library.

- Key commands
  - `uv run eval/run.py` — every score; `-v` lists every failure
  - `uv run oracle/fixtures.py` — regenerate `conformance/`; `--check` to verify it
  - `uv run pytest` — the claim tests
  - `uv run eval/goal.py start|stop` — a goal run the Stop hook enforces

- Key documentation
  - [SPEC.md](SPEC.md) and [claims.yaml](claims.yaml) — the spec; every normative sentence cites a claim id
  - [model.schema.json](model.schema.json) — the canonical model every eval compares
  - [docs/loop.md](docs/loop.md) — how to run an agent toward a score

- Rules
  - The official `anki` wheel, pinned in `pyproject.toml`, is the oracle. When the oracle and the spec disagree, the spec is wrong.
  - A claim needs an upstream `source` and a test that would fail if the claim were false. A test that only restates the fixture proves nothing.
  - `corpus/local/` holds real decks. Never commit them, never quote their content in commits or docs.
  - While `eval/goal.json` exists, the Stop hook runs the gate. Locked paths are in that file; do not edit them, and do not edit the gate to pass it.

- Iron Laws
  - Tokens are expensive, state of the art models need minimal guidance, don't repeat yourself, don't babysit, don't be over-specific.
  - AI-native project. All code is AI-generated.
  - Minimal attention when model implements without errors, we document in more detail when model struggles.
  - Do not expect the user to have read each line, don't lose him on the internals, give visibility on a higher-architectural level.
  - No journaling: code comments / documentation describe current state, they don't carry a log of their own edit history.
