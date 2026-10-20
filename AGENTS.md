# SmartNotice development

Use `uv` for Python environments, dependency changes, scripts, notebooks, and tests. Keep `uv.lock` consistent with `pyproject.toml`.

Apply the supplied `WRITING_GUIDE.md` to documentation, comments, and docstrings. Its Itemset paths and Julia examples illustrate style; they do not define SmartNotice's architecture. SmartNotice requirements live in `docs/assignment.md`, its data contract in `docs/interface.md`, and dated plans and results in dated files. Do not invent a Linear project or issue IDs.

Preserve Vietnamese diacritics. Assign offsets only after normalization and redaction. Never commit participant email, consent records, personal profiles, or generated real corpus data. Mark synthetic records explicitly. Do not use synthetic counts as research evidence.

Keep source threads, related templates, duplicates, and derived event/profile pairs in the same split. Reserved web groups cannot enter training. Run `uv run pytest`, `uv run ruff check .`, and the offline demo for pipeline changes. Execute notebooks when their analysis changes.
