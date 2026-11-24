from hashlib import sha256

import pytest
from pydantic import ValidationError
from smartnotice.modeling.lexicon import DEFAULT_LEXICON_PATH, Lexicon, load_lexicon


def test_lexicon_loads_with_hash():
    lexicon, digest = load_lexicon(DEFAULT_LEXICON_PATH)
    assert lexicon.version == "draft-2026-11-24"
    assert "CLC" in lexicon.programs
    assert digest == sha256(DEFAULT_LEXICON_PATH.read_bytes()).hexdigest()


def test_lexicon_rejects_unknown_key():
    lexicon, _ = load_lexicon(DEFAULT_LEXICON_PATH)
    with pytest.raises(ValidationError, match="extra"):
        Lexicon.model_validate(lexicon.model_dump() | {"unexpected": []})


def test_lexicon_rejects_blank_surface_form():
    lexicon, _ = load_lexicon(DEFAULT_LEXICON_PATH)
    with pytest.raises(ValueError, match="blank"):
        Lexicon.model_validate(lexicon.model_dump() | {"condition": [""]})
