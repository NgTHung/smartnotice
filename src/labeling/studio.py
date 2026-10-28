"""Exchange exact text spans and typed relations with Label Studio."""

import hashlib
import re
from datetime import UTC, datetime
from uuid import uuid4

from smartnotice.labeling.llm import (
    MAX_OUTPUT_TOKENS,
    PROMPT_VERSION,
    TEMPERATURE,
    build_prompt,
    json_sha256,
    text_sha256,
)
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import (
    Annotation,
    Argument,
    Event,
    Notice,
    ProposalProvenance,
    Provider,
    ReviewRecord,
    Span,
)


def export_tasks(notices: list[Notice]) -> list[dict]:
    """Return unlabeled tasks with the immutable document and sentence metadata."""
    return [
        {
            "data": {
                "doc_id": notice.doc_id,
                "text": notice.text,
                "source_type": notice.source_type,
                "reference_date": str(notice.reference_date) if notice.reference_date else "",
                "sentences": [sentence.model_dump() for sentence in notice.sentences],
            }
        }
        for notice in notices
    ]


def export_prediction_task(
    notice: Notice, proposal: Annotation, *, provider: Provider, model: str
) -> dict:
    """Attach one validated model suggestion as a Label Studio prediction.

    The prediction is read-only until an annotator creates and checks a human
    annotation. Provenance stays in task data so it survives task export.
    """
    validate_annotation(proposal, notice)
    if proposal.annotator_id != "model_prediction":
        raise ValueError("Only model proposals can be exported as predictions")
    task = export_tasks([notice])[0]
    spans = {span.span_id: span for span in proposal.spans}
    results = [
        {
            "id": span.span_id,
            "from_name": "entities",
            "to_name": "notice",
            "type": "labels",
            "value": {
                "start": span.start,
                "end": span.end,
                "text": span.text,
                "labels": [span.label],
            },
        }
        for span in proposal.spans
    ]
    results.extend(
        {
            "type": "relation",
            "from_id": event.action_span_id,
            "to_id": argument.span_id,
            "labels": [argument.role or spans[argument.span_id].label],
        }
        for event in proposal.events
        for argument in event.arguments
    )
    task["predictions"] = [
        {"model_version": f"{provider}:{model}:{PROMPT_VERSION}", "result": results}
    ]
    task["data"]["proposal"] = ProposalProvenance(
        run_id=str(uuid4()),
        created_at=datetime.now(UTC),
        provider=provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=hashlib.sha256(build_prompt(notice).encode("utf-8")).hexdigest(),
        text_sha256=text_sha256(notice),
        raw_sha256=notice.raw_sha256,
        prediction_sha256=json_sha256(_result_signature(results)),
        synthetic=notice.synthetic,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    ).model_dump(mode="json")
    return task


def _result_signature(results: list[dict]) -> tuple:
    """Compare the span and relation content of a prediction and review."""
    values = []
    for result in results:
        if result["type"] == "labels":
            value = result["value"]
            values.append(
                (
                    "labels",
                    result["id"],
                    value["start"],
                    value["end"],
                    value["text"],
                    tuple(value["labels"]),
                )
            )
        elif result["type"] == "relation":
            values.append(("relation", result["from_id"], result["to_id"], tuple(result["labels"])))
    return tuple(sorted(values))


def import_reviewed_tasks(
    tasks: list[dict], notices: list[Notice], prediction_tasks: list[dict]
) -> tuple[list[Annotation], list[dict]]:
    """Import human-checked predictions and return annotations and review log.

    Each task needs one human completion or cancellation and its original saved
    prediction. Stale text, changed suggestions, or unknown reviewers fail.
    Cancellations produce skipped log rows only. Completion is human-supplied
    evidence of review, not an independent verification of annotation quality.
    """
    if not tasks:
        raise ValueError("No human review tasks supplied")
    documents = {notice.doc_id: notice for notice in notices}
    if len(documents) != len(notices):
        raise ValueError("Review notice document IDs must be unique")
    originals = {task["data"]["doc_id"]: task for task in prediction_tasks}
    if len(originals) != len(prediction_tasks):
        raise ValueError("Original predictions must have unique document IDs")
    annotations, reviews = [], []
    seen = set()
    for task in tasks:
        data = task["data"]
        doc_id = data["doc_id"]
        if doc_id in seen:
            raise ValueError(f"Duplicate reviewed document: {doc_id}")
        seen.add(doc_id)
        notice = documents[doc_id]
        original = originals.get(doc_id)
        if original is None:
            raise ValueError(f"Missing original prediction for document {doc_id}")
        provenance = ProposalProvenance.model_validate(original["data"].get("proposal", {}))
        if (
            data["text"] != notice.text
            or original["data"]["text"] != notice.text
            or provenance.text_sha256 != text_sha256(notice)
            or provenance.raw_sha256 != notice.raw_sha256
            or provenance.synthetic != notice.synthetic
            or data.get("proposal") != original["data"]["proposal"]
        ):
            raise ValueError(f"Reviewed task text changed: {doc_id}")
        predictions = original.get("predictions", [])
        completed = task.get("annotations", [])
        if len(predictions) != 1 or len(completed) != 1:
            raise ValueError(f"Expected one prediction and one human annotation: {doc_id}")
        prediction_signature = _result_signature(predictions[0]["result"])
        if json_sha256(prediction_signature) != provenance.prediction_sha256:
            raise ValueError(f"Original prediction changed: {doc_id}")
        item = completed[0]
        identity = item.get("completed_by")
        if isinstance(identity, dict):
            identity = identity.get("id")
        reviewer = str(identity) if identity is not None else ""
        if (
            isinstance(identity, bool)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", reviewer)
            or reviewer in {"unknown", "model_prediction"}
        ):
            raise ValueError(f"Missing human reviewer for document {doc_id}")
        decision = "skipped" if item.get("was_cancelled") else "edited"
        annotation_hash = None
        if decision != "skipped":
            safe_task = {**task, "annotations": [{**item, "completed_by": reviewer}]}
            imported = import_tasks([safe_task], [notice])
            if len(imported) != 1:
                raise ValueError(f"Missing human annotation for document {doc_id}")
            annotations.extend(imported)
            annotation_hash = json_sha256(imported[0].model_dump(mode="json"))
            if _result_signature(item["result"]) == prediction_signature:
                decision = "accepted"
        reviews.append(
            ReviewRecord(
                doc_id=doc_id,
                run_id=provenance.run_id,
                reviewer_id=reviewer,
                imported_at=datetime.now(UTC),
                decision=decision,
                provider=provenance.provider,
                model=provenance.model,
                text_sha256=provenance.text_sha256,
                prediction_sha256=provenance.prediction_sha256,
                annotation_sha256=annotation_hash,
                synthetic=notice.synthetic,
            ).model_dump(mode="json")
        )
    return annotations, reviews


def import_tasks(tasks: list[dict], notices: list[Notice]) -> list[Annotation]:
    """Convert completed span/relation exports; require canonical-text equality.

    The UI collects spans and ACTION-to-argument links. Dates, reviewed evidence,
    and structured constraints are curated in canonical JSONL after conversion.
    Canceled annotations are skipped. Multiple annotators produce separate rows.
    """
    documents = {notice.doc_id: notice for notice in notices}
    output = []
    for task in tasks:
        doc_id = task["data"]["doc_id"]
        notice = documents[doc_id]
        if task["data"]["text"] != notice.text:
            raise ValueError(f"Label Studio text changed: {doc_id}")
        for item in task.get("annotations", []):
            if item.get("was_cancelled"):
                continue
            spans, relations = [], []
            for result in item.get("result", []):
                if result["type"] == "labels":
                    value = result["value"]
                    if len(value["labels"]) != 1:
                        raise ValueError("Each span requires exactly one label")
                    spans.append(
                        Span(
                            span_id=result["id"],
                            label=value["labels"][0],
                            start=value["start"],
                            end=value["end"],
                            text=value["text"],
                        )
                    )
                elif result["type"] == "relation":
                    relations.append(result)
            lookup = {span.span_id: span for span in spans}
            events = []
            for span in spans:
                if span.label != "ACTION":
                    continue
                arguments = []
                linked = [span]
                for relation in relations:
                    if relation["from_id"] != span.span_id:
                        continue
                    target = lookup[relation["to_id"]]
                    labels = relation.get("labels", [])
                    if len(labels) != 1:
                        raise ValueError("Each relation requires one relation label")
                    label = labels[0]
                    if target.label == "TIME":
                        arguments.append(Argument(span_id=target.span_id, role=label))
                    else:
                        if label != target.label:
                            raise ValueError("Relation label must match its argument type")
                        arguments.append(Argument(span_id=target.span_id))
                    linked.append(target)
                evidence = [
                    sentence.sentence_id
                    for sentence in notice.sentences
                    if any(sentence.start <= s.start and s.end <= sentence.end for s in linked)
                ]
                events.append(
                    Event(
                        event_id=f"e{len(events) + 1}",
                        action_span_id=span.span_id,
                        arguments=arguments,
                        evidence_sentence_ids=evidence,
                    )
                )
            for relation in relations:
                if (
                    relation["from_id"] not in lookup
                    or lookup[relation["from_id"]].label != "ACTION"
                ):
                    raise ValueError("Relations must originate from an ACTION")
            annotation = Annotation(
                doc_id=doc_id,
                annotator_id=str(item.get("completed_by", "unknown")),
                spans=spans,
                events=events,
            )
            validate_annotation(annotation, notice)
            output.append(annotation)
    return output
