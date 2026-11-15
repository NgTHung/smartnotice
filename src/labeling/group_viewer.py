"""Prepare a standalone local HTML view of source-bound event groups."""

import json

from smartnotice.labeling.event_groups import assembly_fingerprint
from smartnotice.labeling.llm import text_sha256
from smartnotice.schemas import (
    EventGroupAssembly,
    EvidenceQuote,
    GroupDisplayLabels,
    GroupFeedbackResult,
    Notice,
)


def render_group_review(
    assembly: EventGroupAssembly,
    notices: list[Notice],
    template: str,
    *,
    feedback: GroupFeedbackResult | list[GroupFeedbackResult] | None = None,
    labels: GroupDisplayLabels | None = None,
) -> str:
    """Render a local-only page with exact source text and safely embedded JSON.

    Require one __SMARTNOTICE_REVIEW_DATA__ placeholder. Reject stale source
    snapshots, unsupported quotes and inconsistent group/task membership with
    ValueError. Keep only notices used by the assembly, omitting source_ref and
    unrelated private metadata. Source offsets remain Python code point offsets;
    the UI must use Array.from(text) when applying them in JavaScript. The page
    records optional browser notes, never canonical reviews or privacy approvals.
    Optional applied feedback must match the supplied pair records and resulting
    partitions; historical notes are displayed separately from new browser notes.
    For multiple batches, the last applied note for each resulting group wins.
    Display labels must match the fingerprint and quote the title in a member's
    source text. A display label creates neither an event nor a student task.
    """
    marker = "__SMARTNOTICE_REVIEW_DATA__"
    if template.count(marker) != 1:
        raise ValueError("Template requires exactly one data placeholder")
    documents = {n.doc_id: n for n in notices}
    if len(documents) != len(notices):
        raise ValueError("Duplicate source document IDs")
    mentions = {m.version.event_ref: m for m in assembly.mentions}
    if len(mentions) != len(assembly.mentions):
        raise ValueError("Duplicate assembly mention IDs")

    def check_quote(quote: EvidenceQuote) -> None:
        notice = documents.get(quote.doc_id)
        if notice is None or notice.text[quote.start : quote.end] != quote.text:
            raise ValueError("Review quote does not resolve to source text")
        if not any(
            s.sentence_id == quote.sentence_id and s.start <= quote.start < quote.end <= s.end
            for s in notice.sentences
        ):
            raise ValueError("Review quote does not fit its source sentence")

    used = set()
    for ref, mention in mentions.items():
        doc = ref.split(":", 1)[0]
        notice = documents.get(doc)
        if (
            notice is None
            or notice.raw_sha256 != mention.version.raw_sha256
            or text_sha256(notice) != mention.version.text_sha256
        ):
            raise ValueError(f"Source snapshot mismatch: {ref}")
        used.add(doc)
        for span in mention.spans:
            if notice.text[span.start : span.end] != span.text:
                raise ValueError(f"Span no longer resolves to source: {ref}")
    seen = []
    for group in assembly.groups:
        seen.extend(group.members)
        task_members = [ref for task in group.tasks for ref in task.members]
        if sorted(task_members) != sorted(group.members) or any(
            ref not in mentions for ref in group.members
        ):
            raise ValueError("Group/task membership is inconsistent")
        if sorted(group.document_ids) != sorted({ref.split(":", 1)[0] for ref in group.members}):
            raise ValueError("Group document membership is inconsistent")
        for task in group.tasks:
            facts = {f.fact_id: f for f in task.facts}
            for fact in task.facts:
                if fact.mention_ref not in task.members or any(
                    fid not in facts for fid in fact.superseded_by
                ):
                    raise ValueError("Fact does not resolve inside its task")
                check_quote(fact.quote)
            for field, ids in task.active_values.items():
                if any(
                    fid not in facts or facts[fid].field != field or facts[fid].superseded_by
                    for fid in ids
                ):
                    raise ValueError("Active fact reference is inconsistent")
    if sorted(seen) != sorted(mentions):
        raise ValueError("Assembly membership does not preserve all mentions exactly once")
    for review in assembly.reviews:
        for version in [review.left, review.right]:
            if version.event_ref not in mentions or version != mentions[version.event_ref].version:
                raise ValueError("Review annotation snapshot is stale")
        for quote in review.evidence:
            check_quote(quote)
        for change in review.changes:
            check_quote(change.new)
            if change.old:
                check_quote(change.old)
    data = assembly.model_dump(mode="json")
    fingerprint = assembly_fingerprint(assembly)
    if labels is not None:
        if labels.assembly_fingerprint != fingerprint:
            raise ValueError("Display labels target a different assembly fingerprint")
        group_map = {g.group_id: g for g in assembly.groups}
        seen_labels = set()
        for label in labels.labels:
            if label.group_id not in group_map or label.group_id in seen_labels:
                raise ValueError("Unknown or duplicate display-label group")
            seen_labels.add(label.group_id)
            for quote in label.evidence:
                check_quote(quote)
                if quote.doc_id not in group_map[label.group_id].document_ids:
                    raise ValueError("Display-label evidence must come from its group")
            title = " ".join(label.title.casefold().split())
            if not any(title == " ".join(q.text.casefold().split()) for q in label.evidence):
                raise ValueError("Display label must reproduce a quoted source title")
    applied_feedback = {}
    batches = feedback if isinstance(feedback, list) else [feedback] if feedback else []
    for batch in batches:
        if {r.review_id: r for r in batch.reviews} != {r.review_id: r for r in assembly.reviews}:
            raise ValueError("Applied feedback pair records do not match this assembly")
        batch_feedback = {}
        for application in batch.applications:
            if application.outcome in {"deferred", "not_reviewed"}:
                continue
            partitions = application.partitions + (
                [application.additional_members] if application.additional_members else []
            )
            for partition in partitions:
                targets = [g for g in assembly.groups if set(g.members) == set(partition)]
                if len(targets) != 1:
                    raise ValueError("Applied feedback partition does not resolve to one group")
                gid = targets[0].group_id
                note = {
                    "group_id": application.note.group_id,
                    "status": application.note.status,
                    "text": application.note.text,
                    "updated_at": application.note.updated_at.isoformat(),
                }
                previous = batch_feedback.get(gid)
                source_notes = (previous["source_notes"] if previous else []) + [note]
                batch_feedback[gid] = {
                    "group_id": gid,
                    "source_group_id": application.note.group_id,
                    "outcome": application.outcome,
                    "status": "needs_check"
                    if application.outcome == "merged"
                    else application.note.status,
                    "text": "\n".join(dict.fromkeys(n["text"] for n in source_notes if n["text"])),
                    "rationale": application.rationale,
                    "updated_at": application.note.updated_at.isoformat(),
                    "source_notes": source_notes,
                }
        applied_feedback.update(batch_feedback)
    payload = {
        "viewer_version": "smartnotice-group-viewer-v1",
        "assembly_fingerprint": fingerprint,
        "assembly": data,
        "applied_feedback": list(applied_feedback.values()),
        "notices": [
            {
                "doc_id": doc,
                "text": documents[doc].text,
                "reference_date": documents[doc].reference_date.isoformat()
                if documents[doc].reference_date
                else None,
                "reference_date_origin": documents[doc].reference_date_origin,
                "parser_warnings": documents[doc].parser_warnings,
            }
            for doc in sorted(used)
        ],
    }
    if labels is not None:
        payload["display_labels"] = labels.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False)
    for char, escaped in [
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ]:
        encoded = encoded.replace(char, escaped)
    return template.replace(marker, encoded)
