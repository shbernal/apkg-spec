# Running an agent toward a score

Two controls keep a long agent run honest:

- **`/goal`**: a small model reads the transcript after each turn and decides
  whether the condition holds. It cannot run commands, so on its own it trusts
  what the agent printed.
- **The Stop hook** (`.claude/hooks/gate.sh`): while `eval/goal.json` exists,
  the agent cannot stop until `uv run eval/run.py --gate` passes. The gate also
  fails when a locked path changed since the goal started, or when a repository
  the goal names has uncommitted work. This is the check the agent cannot talk
  its way past.

`eval/history.jsonl` (local, gitignored) gets one line per eval run, with the
commit and every score.

## Start a run

From a clean tree:

```sh
uv run eval/goal.py start --target <metric>=<pct> [--lock GLOB]... [--clean REPO]...
```

It commits `eval/goal.json` and prints the `/goal` line to paste into a Claude
Code session started in this repository. `eval/**` and `.claude/**` are always
locked. End the run with `uv run eval/goal.py stop`.

Headless, for a run nobody watches:

```sh
claude -p --permission-mode acceptEdits --add-dir ../anki-apkg-export "$(uv run eval/goal.py start ...)"
```

## The phases

Each phase is a goal with an end. Do them in order: each one's output is the
next one's input.

### 1. Claims

Prove every claim in `claims.yaml`, and write the SPEC.md prose around them.

```sh
uv run eval/goal.py start --target claims=100 --target spec=100 \
  --lock 'conformance/**' --lock 'oracle/**' --lock claims.yaml
```

`claims.yaml` is locked so that a hard claim cannot be weakened into an easy
one. A claim the oracle disproves is a reason to stop and report, which the
condition says. Reword it by hand, then start a new run.

To grow the spec, add claims by hand (or in a run where `claims.yaml` is not
locked), commit, and run this phase again.

### 2. Reader

Make `anki-apkg-export` read every conformance package into the canonical
model.

```sh
uv run eval/goal.py start --target read:anki-apkg-export=100 \
  --lock 'conformance/**' --lock 'oracle/**' --lock 'tests/**' --lock claims.yaml \
  --clean ../anki-apkg-export
```

Start the session with `--add-dir ../anki-apkg-export`. The adapter in
`adapters/anki-apkg-export/` is not locked, because it is glue that changes
with the reader's API. The package's own gates (`pnpm test`, `lint`,
`typecheck`) still apply to every commit there.

### 3. Writer

A new package writes the canonical model as a version 3 package. Add it to
`eval/implementations.toml` with a `write` command, commit, then:

```sh
uv run eval/goal.py start --target write:<package>=100 \
  --lock 'conformance/**' --lock 'oracle/**' --lock 'tests/**' --lock claims.yaml \
  --clean ../<package>
```

### 4. Real decks

The corpus has no end, so this phase is a loop, not a goal. Put decks in
`corpus/local/`, then in a session:

```
/loop Run `uv run eval/run.py -v`. Take the largest cluster of corpus failures
(same section, same reason). Reproduce it as a synthetic case in
oracle/fixtures.py, regenerate with `uv run oracle/fixtures.py <case>`, add a
claim and a test if the cluster shows a fact SPEC.md lacks, fix the
implementation, and commit each repository. Stop the loop when no corpus
failure is left or the same cluster survives two attempts.
```

Each fix lands as a committed synthetic case, so what a real deck taught stays
in the corpus after the deck is gone. Score the held-out slice now and then
with `uv run eval/run.py --heldout`; a gap between `corpus/` and `heldout/`
scores means the fixes are too specific.
