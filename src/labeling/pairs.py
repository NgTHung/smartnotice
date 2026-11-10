"""Build event/profile rows while retaining document IDs for split inheritance."""

from smartnotice.labeling.applicability import match_audiences
from smartnotice.labeling.llm import json_sha256
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import Annotation, Notice, Profile


def build_pairs(
    notices: list[Notice],
    annotations: list[Annotation],
    profiles: list[Profile],
    *,
    assume_all_students_without_audience: bool = False,
) -> list[dict]:
    """Generate silver labels from one adjudicated annotation per document.

    Constraints and reasons are label provenance. Model inputs consist only of
    event_text and profile. A downstream trainer joins splits by doc_id. Each row
    records ``annotation_sha256`` and ``profile_set_sha256``, canonical JSON
    hashes of its curated annotation and of the ordered profile list.

    With ``assume_all_students_without_audience=True``, an event with no
    AUDIENCE argument uses the recorded university-learner population default.
    This is a policy assumption, not an extracted span. Explicit audiences,
    missing constraint rows, and eligibility CONDITION arguments retain their
    normal matching behavior. Opted-in rows record the policy and whether the
    default was applied; otherwise missing audiences remain UNCLEAR.
    """
    ids = [annotation.doc_id for annotation in annotations]
    if len(ids) != len(set(ids)):
        raise ValueError("Use one adjudicated annotation per document to build pairs")
    profile_ids = [profile.profile_id for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("Profile IDs must be unique")
    documents = {notice.doc_id: notice for notice in notices}
    profile_set_sha256 = json_sha256([profile.model_dump(mode="json") for profile in profiles])
    rows = []
    for annotation in annotations:
        notice = documents[annotation.doc_id]
        validate_annotation(annotation, notice)
        annotation_sha256 = json_sha256(annotation.model_dump(mode="json"))
        sentences = {sentence.sentence_id: sentence.text for sentence in notice.sentences}
        constraints = {c.audience_span_id: c for c in annotation.audience_constraints}
        span_labels = {span.span_id: span.label for span in annotation.spans}
        for event in annotation.events:
            audience_ids = [
                a.span_id for a in event.arguments if span_labels[a.span_id] == "AUDIENCE"
            ]
            audience = [constraints[sid] for sid in audience_ids if sid in constraints]
            default_applied = assume_all_students_without_audience and not audience_ids
            for profile in profiles:
                if any(sid not in constraints for sid in audience_ids):
                    label, reason = "UNCLEAR", "unreviewed_audience_constraint"
                elif default_applied:
                    label, reason = "APPLIES", "assumed_all_students_no_audience"
                else:
                    label, reason = match_audiences(audience, profile)
                has_condition = any(
                    span_labels[argument.span_id] == "CONDITION" for argument in event.arguments
                )
                if has_condition and label == "APPLIES":
                    label, reason = "UNCLEAR", "unmodeled_condition"
                rows.append(
                    {
                        "doc_id": notice.doc_id,
                        "event_id": event.event_id,
                        "profile_id": profile.profile_id,
                        "event_text": "\n".join(
                            sentences[sid] for sid in event.evidence_sentence_ids
                        ),
                        "profile": profile.model_dump(exclude={"profile_id"}),
                        "label": label,
                        "label_origin": "constraint_rule",
                        "rule_reason": reason,
                        "annotation_sha256": annotation_sha256,
                        "profile_set_sha256": profile_set_sha256,
                        "synthetic": notice.synthetic,
                        **(
                            {
                                "audience_policy": "assume_all_students_without_audience",
                                "audience_default_applied": default_applied,
                            }
                            if assume_all_students_without_audience
                            else {}
                        ),
                    }
                )
    return rows
