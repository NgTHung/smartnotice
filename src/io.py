"""Read and write UTF-8 JSON Lines without platform-dependent encodings."""

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read records and report the line containing invalid JSON."""
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Serialize records before atomically replacing a single-writer UTF-8 file.

    Create the destination directory. A failed write/replace preserves an existing
    file and may leave a sibling .tmp file for inspection. Calls are not concurrent.
    """
    text = "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
