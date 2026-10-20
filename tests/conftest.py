from pathlib import Path

import pytest
from smartnotice.io import read_jsonl
from smartnotice.preprocessing.pipeline import prepare
from smartnotice.schemas import Annotation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def notices(tmp_path):
    return prepare(ROOT / "data/raw/examples/manifest.jsonl", tmp_path / "notices.jsonl")


@pytest.fixture
def annotations():
    return [
        Annotation.model_validate(row)
        for row in read_jsonl(ROOT / "data/annotations/examples/events.jsonl")
    ]
