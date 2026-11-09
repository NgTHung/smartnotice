import pytest
from smartnotice.labeling.analysis import cohens_kappa, span_f1
from smartnotice.labeling.applicability import match_audiences, match_profile
from smartnotice.labeling.pairs import build_pairs
from smartnotice.labeling.studio import export_tasks, import_tasks
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import AudienceConstraint, Profile


def test_annotation_examples_have_valid_evidence_and_shared_arguments(notices, annotations):
    documents = {n.doc_id: n for n in notices}
    for annotation in annotations:
        validate_annotation(annotation, documents[annotation.doc_id])
    thesis = annotations[1]
    assert thesis.events[0].arguments[0].span_id == thesis.events[1].arguments[0].span_id


@pytest.mark.parametrize("defect", ["offset", "time_role", "evidence", "duplicate"])
def test_annotation_validation_rejects_broken_contracts(notices, annotations, defect):
    annotation = annotations[0].model_copy(deep=True)
    notice = next(n for n in notices if n.doc_id == annotation.doc_id)
    if defect == "offset":
        annotation.spans[0].start += 1
    elif defect == "time_role":
        annotation.events[0].arguments[1].role = None
    elif defect == "evidence":
        annotation.events[0].evidence_sentence_ids = ["s999"]
    else:
        annotation.spans.append(annotation.spans[0])
    with pytest.raises(ValueError):
        validate_annotation(annotation, notice)


def _listed(**fields):
    return AudienceConstraint(audience_span_id="u", scope="listed", **fields)


@pytest.mark.parametrize(
    ("profile", "label"),
    [
        ({"cohort": 2024, "program": "clc", "status": "active"}, "APPLIES"),
        ({"cohort": 2023, "program": "CLC", "status": "active"}, "NOT_APPLIES"),
        ({"cohort": 2024, "program": "CLC", "status": "defended"}, "NOT_APPLIES"),
        ({"cohort": 2024, "program": "CLC"}, "UNCLEAR"),
        ({"cohort": 2024, "status": "active"}, "UNCLEAR"),
    ],
)
def test_audience_matching_exclusion_and_missing_attributes(profile, label):
    constraint = _listed(cohorts=[2024], programs=["CLC"], excluded_statuses=["defended"])
    assert match_profile(constraint, Profile(profile_id="p", **profile))[0] == label


@pytest.mark.parametrize(
    ("scope", "excluded", "profile", "expected"),
    [
        ("all_students", [], {"cohort": 2020}, ("APPLIES", "all_students")),
        (
            "all_students",
            ["graduated"],
            {"status": "graduated"},
            ("NOT_APPLIES", "excluded_status"),
        ),
        ("all_students", ["graduated"], {}, ("UNCLEAR", "missing_profile_attribute")),
        ("outside_population", [], {"cohort": 2024}, ("NOT_APPLIES", "outside_population")),
        ("implicit", [], {"cohort": 2024}, ("UNCLEAR", "implicit_audience")),
    ],
)
def test_constraint_scope_decides_label(scope, excluded, profile, expected):
    constraint = AudienceConstraint(audience_span_id="u", scope=scope, excluded_statuses=excluded)
    assert match_profile(constraint, Profile(profile_id="p", **profile)) == expected


@pytest.mark.parametrize(
    ("bounds", "cohort", "expected"),
    [
        ({"cohort_max": 2024}, 2021, "APPLIES"),
        ({"cohort_max": 2024}, 2025, "NOT_APPLIES"),
        ({"cohort_min": 2022, "cohort_max": 2024}, 2022, "APPLIES"),
        ({"cohort_min": 2022, "cohort_max": 2024}, 2021, "NOT_APPLIES"),
        ({"cohort_min": 2025}, 2025, "APPLIES"),
    ],
)
def test_cohort_bounds_are_inclusive_admission_years(bounds, cohort, expected):
    label, _ = match_profile(_listed(**bounds), Profile(profile_id="p", cohort=cohort))
    assert label == expected


def test_degree_level_mismatch_and_missing_level():
    constraint = _listed(degree_levels=["master"])
    undergraduate = Profile(profile_id="p", degree_level="undergraduate")
    assert match_profile(constraint, undergraduate) == ("NOT_APPLIES", "mismatched_degree_level")
    missing = match_profile(constraint, Profile(profile_id="p"))
    assert missing == ("UNCLEAR", "missing_profile_attribute")


def test_unrepresented_requirement_abstains_but_keeps_known_mismatch():
    constraint = _listed(cohorts=[2024], unrepresented=True)
    matching = match_profile(constraint, Profile(profile_id="p", cohort=2024))
    assert matching == ("UNCLEAR", "unrepresented_requirement")
    other = match_profile(constraint, Profile(profile_id="p", cohort=2023))
    assert other == ("NOT_APPLIES", "mismatched_cohort")
    role_only = _listed(unrepresented=True)
    assert match_profile(role_only, Profile(profile_id="p"))[0] == "UNCLEAR"


@pytest.mark.parametrize(
    "fields",
    [
        {"scope": "listed"},
        {"scope": "all_students", "cohorts": [2024]},
        {"scope": "implicit", "excluded_statuses": ["graduated"]},
        {"scope": "outside_population", "unrepresented": True},
        {"scope": "listed", "cohorts": [2024], "cohort_max": 2024},
        {"scope": "listed", "cohort_min": 2025, "cohort_max": 2024},
        {"scope": "listed", "statuses": ["Active"]},
        {"scope": "listed", "degree_levels": ["bachelor"]},
        {"cohorts": [2024]},
        {"scope": "listed", "cohorts": ["K24"]},
        {"scope": "listed", "cohorts": [2024], "implicit": True},
    ],
)
def test_audience_constraint_rejects_unsupported_combinations(fields):
    with pytest.raises(ValueError):
        AudienceConstraint(audience_span_id="u", **fields)


@pytest.mark.parametrize(
    "fields", [{"cohort": "K24"}, {"status": "dang hoc"}, {"degree_level": "bachelor"}]
)
def test_profile_rejects_noncanonical_values(fields):
    with pytest.raises(ValueError):
        Profile(profile_id="p", **fields)


def test_audience_alternatives_combine_with_or():
    profile = Profile(profile_id="p", cohort=2024)
    a = AudienceConstraint(audience_span_id="a", scope="listed", cohorts=[2023])
    b = AudienceConstraint(audience_span_id="b", scope="listed", cohorts=[2024])
    assert match_audiences([a, b], profile)[0] == "APPLIES"
    assert match_audiences([a], profile)[0] == "NOT_APPLIES"
    assert match_audiences([], profile)[0] == "UNCLEAR"


def test_generated_pairs_need_adjudicated_unique_documents(notices, annotations):
    profiles = [Profile(profile_id="p", cohort=2024, major="CNTT", program="CLC")]
    rows = build_pairs(notices, annotations, profiles)
    assert len(rows) == 6
    assert all(row["label_origin"] == "constraint_rule" for row in rows)
    assert all("constraints" not in row["profile"] for row in rows)
    assert rows[0]["label"] == "APPLIES"
    with pytest.raises(ValueError, match="adjudicated"):
        build_pairs(notices, [annotations[0], annotations[0]], profiles)


def test_unmodeled_conditions_cannot_produce_applies(notices, annotations):
    profile = Profile(profile_id="p", cohort=2023, status="active")
    rows = build_pairs(notices, [annotations[1]], [profile])
    assert rows[0]["label"] == "APPLIES"
    assert rows[1]["label"] == "UNCLEAR"
    assert rows[1]["rule_reason"] == "unmodeled_condition"


def test_label_studio_import_preserves_types_and_rejects_edited_text(notices, annotations):
    annotation = annotations[0]
    notice = next(n for n in notices if n.doc_id == annotation.doc_id)
    task = export_tasks([notice])[0]
    results = [
        {
            "type": "labels",
            "id": s.span_id,
            "value": {"start": s.start, "end": s.end, "text": s.text, "labels": [s.label]},
        }
        for s in annotation.spans
    ]
    lookup = {s.span_id: s for s in annotation.spans}
    results += [
        {
            "type": "relation",
            "from_id": event.action_span_id,
            "to_id": a.span_id,
            "labels": [a.role or lookup[a.span_id].label],
        }
        for event in annotation.events
        for a in event.arguments
    ]
    task["annotations"] = [{"completed_by": 42, "result": results}]
    imported = import_tasks([task], [notice])[0]
    assert imported.spans == annotation.spans
    assert imported.events[0].arguments[1].role == "DEADLINE"
    task["data"]["text"] += "edited"
    with pytest.raises(ValueError, match="text changed"):
        import_tasks([task], [notice])


def test_agreement_metrics_use_aligned_decisions(annotations):
    assert span_f1(annotations[0], annotations[0])["f1"] == 1
    assert cohens_kappa(["A", "A", "B", "B"], ["A", "A", "B", "B"]) == 1
    assert cohens_kappa(["A", "A"], ["A", "A"]) is None
    with pytest.raises(ValueError, match="equal"):
        cohens_kappa(["A"], ["A", "B"])
    with pytest.raises(ValueError, match="same document"):
        span_f1(annotations[0], annotations[1])
