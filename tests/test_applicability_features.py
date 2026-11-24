from hashlib import sha256

import pytest
from applicability_fixture import make_corpus
from pydantic import ValidationError
from smartnotice.modeling.applicability_features import build_inputs
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


@pytest.fixture
def corpus():
    return make_corpus(n_docs=4)


def test_inputs_exclude_label_provenance(corpus):
    notices, annotations, _, pairs, _ = corpus
    forbidden = {
        "audience_constraints",
        "cohort_min",
        "excluded_statuses",
        "rule_reason",
        "label",
        "label_origin",
        "audience_policy",
        "audience_default_applied",
        "annotation_sha256",
        "profile_set_sha256",
    }
    supplied = dict.fromkeys(forbidden, "forbidden")
    pair = pairs[0] | supplied
    pair["profile"] = pair["profile"] | supplied
    [item] = build_inputs([pair], notices, annotations, "human")
    assert forbidden.isdisjoint(item.model_dump())
    assert item.cohort == 2024


@pytest.mark.parametrize("source", ["human", "predicted"])
def test_human_source_uses_event_audience_and_condition_spans(corpus, source):
    notices, annotations, _, pairs, _ = corpus
    [item] = build_inputs([pairs[-1]], notices, annotations, source)
    assert item.audience_texts == ["sinh viên K24"]
    assert item.condition_texts == ["có chứng chỉ"]
    assert item.reference_date == notices[-1].reference_date
    assert item.source_type == notices[-1].source_type


def test_none_source_has_no_span_texts(corpus):
    notices, _, _, pairs, _ = corpus
    [item] = build_inputs(pairs[:1], notices, None, "none")
    assert item.audience_texts is item.condition_texts is None
    assert item.event_text == pairs[0]["event_text"]


def test_missing_event_reports_line(corpus):
    notices, annotations, _, pairs, _ = corpus
    with pytest.raises(ValueError, match="pair line 1.*unknown"):
        build_inputs([pairs[0] | {"event_id": "unknown"}], notices, annotations, "human")


@pytest.mark.parametrize("source", ["human", "predicted"])
def test_annotation_required_for_span_sources(corpus, source):
    notices, _, _, pairs, _ = corpus
    with pytest.raises(ValueError, match="audience annotations"):
        build_inputs(pairs, notices, None, source)
