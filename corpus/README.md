# Corpus

Put real `.apkg` files under `corpus/local/`. The directory is gitignored: shared
decks carry their authors' content under no clear license, so they stay on the
machine that downloaded them.

`eval/run.py` reads each one with the oracle and scores implementations against
that model. A package the oracle cannot read is skipped. One package in five,
picked by a hash of its filename, is held out and scored only with `--heldout`.
