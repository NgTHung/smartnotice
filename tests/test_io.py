"""Check that failed manifest replacement preserves previous collection evidence."""

import hashlib
from pathlib import Path

import pytest
from smartnotice.collectors.local import save_source
from smartnotice.io import read_jsonl, write_jsonl


def test_failed_manifest_replace_keeps_previous_manifest_and_downloaded_source(
    tmp_path, monkeypatch
):
    first = save_source(b"first", tmp_path, "web", url="https://example.invalid/one")
    replace = Path.replace

    def fail_manifest(path, destination):
        if path.name == "manifest.jsonl.tmp":
            raise PermissionError("synthetic storage failure")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_manifest)
    with pytest.raises(PermissionError, match="storage failure"):
        save_source(b"second", tmp_path, "web", url="https://example.invalid/two")
    assert read_jsonl(tmp_path / "manifest.jsonl") == [first]
    assert (tmp_path / (hashlib.sha256(b"second").hexdigest() + ".html")).read_bytes() == b"second"


def test_serialization_error_preserves_existing_jsonl(tmp_path):
    path = tmp_path / "records.jsonl"
    write_jsonl(path, [{"text": "Sinh viên nộp hồ sơ."}])
    before = path.read_bytes()
    cycle = {}
    cycle["loop"] = cycle
    with pytest.raises(ValueError, match="Circular"):
        write_jsonl(path, [cycle])
    assert path.read_bytes() == before
