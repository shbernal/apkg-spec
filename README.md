# apkg-spec

A specification of the Anki `.apkg` format, with the evidence for every line of it.

Anki has never published one. Its package format lives in Rust source, protobuf
definitions and a SQL schema, and every third-party tool that reads or writes a
deck re-derives it, usually in part. This repository writes it down once, and
holds each statement to the official Anki library: a claim without a passing
test does not count.

- [SPEC.md](SPEC.md): the format, from the zip container down to the card queue
- [claims.yaml](claims.yaml): each normative claim, its upstream source, and its level
- [conformance/](conformance/): packages the official library exported, one per feature, in both package versions, each with the model it must read as
- [model.schema.json](model.schema.json): the canonical model, so two implementations can agree on what a deck holds without agreeing on bytes

## Test an implementation

Add a `read` command, and optionally a `write` command and the package versions
it writes, to `eval/implementations.toml`, then:

```sh
uv run eval/run.py
```

The eval needs `uv` and Node 24. It scores
[`@shbernal/anki-apkg-export`](https://www.npmjs.com/package/@shbernal/anki-apkg-export)
from npm; set `ANKI_APKG_EXPORT` to a checkout of it to score local changes.

Status: draft, against Anki 26.08.1.

## License

[MIT](LICENSE)
