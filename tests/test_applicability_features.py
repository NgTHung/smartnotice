from datetime import date
from hashlib import sha256
from unicodedata import normalize

import pytest
from applicability_fixture import make_corpus
from pydantic import ValidationError
from smartnotice.modeling.applicability_features import (
    AudienceCues,
    FeatureBuilder,
    admission_year_for_study_year,
    build_inputs,
    cross_features,
    extract_audience_cues,
)
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


@pytest.fixture
def lexicon():
    return load_lexicon(DEFAULT_LEXICON_PATH)[0]


@pytest.fixture
def cue_item(corpus):
    notices, annotations, _, pairs, _ = corpus
    return build_inputs(pairs[:1], notices, annotations, "human")[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sinh viên K24", {"cohorts": {2024}}),
        ("khóa 2025", {"cohorts": {2025}}),
        ("khoá 25", {"cohorts": {2025}}),
        ("từ K22 đến K24", {"cohort_min": 2022, "cohort_max": 2024}),
        ("khóa từ 24 đến khóa 22", {"cohort_min": 2022, "cohort_max": 2024}),
        ("K24 về trước", {"cohort_max": 2024}),
        ("K24 trở về trước", {"cohort_max": 2024}),
        ("K22 trở đi", {"cohort_min": 2022}),
        ("K22 trở lên", {"cohort_min": 2022}),
        ("năm thứ nhất", {"cohorts": {2025}}),
        ("năm thứ hai trở đi", {"cohort_max": 2024}),
        ("năm 2", {"cohorts": {2024}}),
        ("học viên sau đại học", {"degrees": {"master", "doctoral"}}),
        ("trừ sinh viên bảo lưu", {"excluded_statuses": {"on_leave"}, "statuses": set()}),
        (
            "trừ phụ huynh; sinh viên bảo lưu",
            {"excluded_statuses": set(), "statuses": {"on_leave"}, "outside_population": False},
        ),
        ("chất lượng cao", {"programs": {"CLC"}}),
        ("lớp trưởng", {"unrepresented": True}),
        ("lớp 24CTT1", {"unrepresented": True, "cohorts": set()}),
        ("giảng viên", {"outside_population": True}),
        ("toàn thể sinh viên", {"all_students": True}),
        ("toàn thể", {"all_students": True}),
        ("toàn thể giảng viên", {"all_students": False, "outside_population": True}),
        ("sinh viên CÔNG NGHỆ THÔNG TIN", {"majors": {"CNTT"}}),
        ("", {"absent": True}),
        ("sinh viên", {"absent": True}),
    ],
)
def test_extract_audience_cues(cue_item, lexicon, text, expected):
    item = cue_item.model_copy(update={"audience_texts": [normalize("NFD", text)] if text else []})
    cues = extract_audience_cues(item, lexicon)
    for key, value in expected.items():
        assert getattr(cues, key) == value
    if "cohort_min" in expected or "cohort_max" in expected:
        assert cues.cohorts == set()


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (date(2025, 1, 1), 2024),
        (date(2025, 6, 30), 2024),
        (date(2025, 7, 1), None),
        (date(2025, 8, 1), None),
        (date(2025, 10, 15), None),
        (date(2025, 10, 16), 2025),
        (None, None),
    ],
)
def test_admission_year_boundary(cue_item, lexicon, reference, expected):
    assert admission_year_for_study_year(1, reference) == expected
    item = cue_item.model_copy(
        update={"reference_date": reference, "audience_texts": ["năm thứ nhất"]}
    )
    cues = extract_audience_cues(item, lexicon)
    assert cues.cohorts == ({expected} if expected else set())
    assert cues.cohort_unresolved is (expected is None)


def test_study_year_without_reference_date_is_unresolved(cue_item, lexicon):
    item = cue_item.model_copy(
        update={"reference_date": None, "audience_texts": ["sinh viên năm thứ hai trở đi"]}
    )
    cues = extract_audience_cues(item, lexicon)
    assert cues.cohort_unresolved
    assert cues.cohorts == set()
    assert cues.cohort_min is cues.cohort_max is None


def test_event_text_only_reads_audience_and_condition_cues(cue_item, lexicon):
    item = cue_item.model_copy(
        update={
            "audience_texts": None,
            "condition_texts": None,
            "event_text": "Đăng ký cho sinh viên K24 có chứng chỉ.",
        }
    )
    cues = extract_audience_cues(item, lexicon)
    assert cues.cohorts == {2024}
    assert cues.condition
    assert cues.n_audience == cues.n_condition == cues.audience_chars == 0


def test_span_mode_condition_uses_linked_condition_text(cue_item, lexicon):
    item = cue_item.model_copy(update={"condition_texts": ["có chứng chỉ"]})
    cues = extract_audience_cues(item, lexicon)
    assert cues.condition and cues.n_condition == 1
    assert cues.n_audience == 1
    assert cues.audience_chars == len("sinh viên K24")
    assert not extract_audience_cues(cue_item, lexicon).condition


def test_cohort_match_conflict_and_range(cue_item):
    item = cue_item.model_copy(update={"cohort": 2023})
    conflict = cross_features(AudienceCues(cohorts={2024}), item)
    assert conflict["cohort_conflict"] == 1
    assert conflict["cohort_distance"] == 1
    match = cross_features(AudienceCues(cohorts={2023, 2024}), item)
    assert match["cohort_match"] == 1
    assert match["all_mentioned_match"] == 1
    bounds = AudienceCues(cohort_min=2022, cohort_max=2024)
    assert cross_features(bounds, item)["cohort_in_range"] == 1
    assert cross_features(bounds, item.model_copy(update={"cohort": 2021}))["cohort_below_min"] == 1
    assert cross_features(bounds, item.model_copy(update={"cohort": 2025}))["cohort_above_max"] == 1


def test_missing_profile_marks_required_unknown(cue_item):
    cues = AudienceCues(degrees={"master"}, majors={"CNTT"}, excluded_statuses={"on_leave"})
    features = cross_features(cues, cue_item)
    assert features["degree_level_required_but_unknown"] == 1
    assert features["major_required_but_unknown"] == 1
    assert features["status_required_but_unknown"] == 1
    assert features["n_required_unknown"] == 3
    assert features["any_conflict"] == features["all_mentioned_match"] == 0


def test_excluded_status_hit(cue_item):
    item = cue_item.model_copy(update={"status": "on_leave"})
    features = cross_features(AudienceCues(excluded_statuses={"on_leave"}), item)
    assert features["excluded_status_hit"] == 1
    assert features["status_conflict"] == features["any_conflict"] == 1
    assert features["status_match"] == 0


def test_raw_profile_values_not_features(cue_item, lexicon):
    first = cue_item.model_copy(update={"major": "FIRST", "program": "FIRST", "cohort": 2024})
    second = cue_item.model_copy(update={"major": "OTHER", "program": "OTHER", "cohort": 2030})
    builder = FeatureBuilder(lexicon, tfidf=False).fit([first, second])
    assert all(
        disallowed not in name
        for name in builder.feature_names
        for disallowed in ("CNTT", "FIRST", "OTHER", "2024", "rule_reason", "label_origin")
    )
    dense = builder.transform([first, second]).toarray()
    allowed_differences = {
        "cohort_match",
        "cohort_conflict",
        "cohort_distance",
        "any_conflict",
        "all_mentioned_match",
    }
    actual_differences = {
        name for name, a, b in zip(builder.feature_names, dense[0], dense[1], strict=True) if a != b
    }
    assert actual_differences == allowed_differences


def test_tfidf_fits_training_events_only(cue_item, lexicon):
    first = cue_item.model_copy(update={"event_id": "a", "event_text": "đăng ký hiếm"})
    duplicate = first.model_copy(update={"profile_id": "second-profile"})
    second = cue_item.model_copy(update={"event_id": "b", "event_text": "đăng ký"})
    held_out = cue_item.model_copy(update={"event_id": "c", "event_text": "đăng ký bí mật"})
    builder = FeatureBuilder(lexicon).fit([first, duplicate, second])
    matrix = builder.transform([held_out])
    state = builder.tfidf_state()
    assert set(state["vocabulary"]) == {"đăng", "ký", "đăng ký"}
    assert state["idf"] == [1.0, 1.0, 1.0]
    assert matrix.shape == (1, len(builder.feature_names))


def test_tfidf_can_have_zero_terms_after_min_df(cue_item, lexicon):
    builder = FeatureBuilder(lexicon).fit([cue_item])
    assert builder.tfidf_state() == {"vocabulary": {}, "idf": []}
    assert builder.transform([cue_item]).shape == (1, len(builder.feature_names))


def test_source_feature_toggle(cue_item, lexicon):
    with_source = FeatureBuilder(lexicon, tfidf=False).fit([cue_item])
    without_source = FeatureBuilder(lexicon, tfidf=False, source_feature=False).fit([cue_item])
    assert set(with_source.feature_names) - set(without_source.feature_names) == {
        "source_type_email",
        "source_type_web",
    }
    matrix = with_source.transform([cue_item])
    assert matrix[0, with_source.feature_names.index("source_type_web")] == 1
    assert matrix[0, with_source.feature_names.index("source_type_email")] == 0
    assert without_source.tfidf_state() is None
