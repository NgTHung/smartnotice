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


@pytest.mark.parametrize(
    ("profile", "label"),
    [
        ({"cohort": "k24", "program": "clc", "status": "active"}, "APPLIES"),
        ({"cohort": "K23", "program": "CLC", "status": "active"}, "NOT_APPLIES"),
        ({"cohort": "K24", "program": "CLC", "status": "defended"}, "NOT_APPLIES"),
        ({"cohort": "K24", "program": "CLC"}, "UNCLEAR"),
        ({"cohort": "K24", "status": "active"}, "UNCLEAR"),
    ],
)
def test_audience_matching_exclusion_and_missing_attributes(profile, label):
    constraint = AudienceConstraint(
        audience_span_id="u", cohorts=["K24"], programs=["CLC"], excluded_statuses=["defended"]
    )
    assert match_profile(constraint, Profile(profile_id="p", **profile))[0] == label


def test_audience_alternatives_and_implicit_abstention():
    profile = Profile(profile_id="p", cohort="K24")
    a = AudienceConstraint(audience_span_id="a", cohorts=["K23"])
    b = AudienceConstraint(audience_span_id="b", cohorts=["K24"])
    assert match_audiences([a, b], profile)[0] == "APPLIES"
    assert match_audiences([], profile)[0] == "UNCLEAR"
    assert match_profile(b.model_copy(update={"implicit": True}), profile)[0] == "UNCLEAR"


def test_generated_pairs_need_adjudicated_unique_documents(notices, annotations):
    profiles = [Profile(profile_id="p", cohort="K24", major="CNTT", program="CLC")]
    rows = build_pairs(notices, annotations, profiles)
    assert len(rows) == 6
    assert all(row["label_origin"] == "constraint_rule" for row in rows)
    assert all("constraints" not in row["profile"] for row in rows)
    assert rows[0]["label"] == "APPLIES"
    with pytest.raises(ValueError, match="adjudicated"):
        build_pairs(notices, [annotations[0], annotations[0]], profiles)


def test_unmodeled_conditions_cannot_produce_applies(notices, annotations):
    profile = Profile(profile_id="p", cohort="K23", status="active")
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
