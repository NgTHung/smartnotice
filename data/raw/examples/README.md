# Synthetic notice sources

These invented email and HTML notices exercise Vietnamese text parsing, tables, privacy filtering, annotations, and split grouping. They contain no participant data and provide no evidence about a collected research corpus.

All manifest entries carry `synthetic=true`; example.invalid addresses are inert. The scholarship family shares a group across email updates and a web notice. The internship web notice is reserved for the example domain holdout.

`checksums.json` records exact source-byte hashes. Regenerate these fixtures and their canonical annotations with `uv run python tools/create_examples.py`, then run the demo. Fixture changes also change document IDs and annotation offsets.
