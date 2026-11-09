"""Assemble source-bound pair reviews into provisional events and distinct tasks."""

import hashlib
import json
from collections import defaultdict

from smartnotice.labeling.llm import text_sha256
from smartnotice.labeling.validation import validate_annotation
from smartnotice.schemas import (
    Annotation,
    AssemblyMention,
    BuiltEventGroup,
    EventGroupAssembly,
    EvidenceQuote,
    GroupConflict,
    GroupedFact,
    GroupedTask,
    GroupingReview,
    MentionVersion,
    Notice,
    TimeBoundaryReview,
    UpdateApplication,
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def annotation_sha256(annotation: Annotation) -> str:
    """Hash canonical model fields with sorted JSON keys and preserved Unicode."""
    return _hash(annotation.model_dump(mode="json"))


def assembly_fingerprint(assembly: EventGroupAssembly) -> str:
    """Identify the canonical assembly displayed by the local HTML viewer."""
    return _hash(assembly.model_dump(mode="json"))


def _value_key(fact: GroupedFact) -> str:
    if fact.equivalence_key is not None:
        return "reviewed:" + fact.equivalence_key
    return "literal:" + " ".join(fact.quote.text.casefold().split())


def _components(members: set[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    neighbors = {member: set() for member in members}
    for left, right in edges:
        neighbors[left].add(right)
        neighbors[right].add(left)
    remaining = set(members)
    components = []
    while remaining:
        pending, component = [min(remaining)], set()
        while pending:
            member = pending.pop()
            if member in component:
                continue
            component.add(member)
            pending.extend(neighbors[member] - component)
        remaining -= component
        components.append(sorted(component))
    return components


def build_event_groups(
    notices: list[Notice],
    annotations: list[Annotation],
    reviews: list[GroupingReview],
    time_boundaries: list[TimeBoundaryReview] | None = None,
) -> EventGroupAssembly:
    """Build deterministic provisional groups while preserving tasks and evidence.

    All source/annotation hashes, quotes and annotation offsets must match.
    Positive identity edges form candidate components; an explicit negative or
    unclear cross-pair quarantines the whole component as singletons. Task
    equivalence has its own consistency check. Missing cross-pairs do not supply
    evidence or reviewed negatives; output always requires further review.

    UPDATE_OF points from new to old. Supersede only explicitly supported values
    within the same task, including identical repeated old values. Preserve
    competing terminal values; never pick the latest date or send time. Reject
    duplicate records, stale evidence, unknown mentions and cyclic updates with
    ValueError. No input, split assignment or privacy approval is changed.
    """
    documents = {n.doc_id: n for n in notices}
    if len(documents) != len(notices) or len({a.doc_id for a in annotations}) != len(annotations):
        raise ValueError("Duplicate document or annotation IDs")
    mentions = {}
    for annotation in annotations:
        if annotation.doc_id not in documents:
            raise ValueError(f"Unknown annotation document: {annotation.doc_id}")
        notice = documents[annotation.doc_id]
        validate_annotation(annotation, notice)
        by_id = {s.span_id: s for s in annotation.spans}
        for event in annotation.events:
            ref = f"{annotation.doc_id}:{event.action_span_id}"
            if ref in mentions:
                raise ValueError(f"Duplicate ACTION reference: {ref}")
            ids = [event.action_span_id] + [a.span_id for a in event.arguments]
            mentions[ref] = AssemblyMention(
                version=MentionVersion(
                    event_ref=ref,
                    raw_sha256=notice.raw_sha256,
                    text_sha256=text_sha256(notice),
                    annotation_sha256=annotation_sha256(annotation),
                ),
                event=event.model_copy(deep=True),
                spans=[by_id[s].model_copy(deep=True) for s in ids],
                sentences=[
                    s.model_copy(deep=True)
                    for s in notice.sentences
                    if s.sentence_id in event.evidence_sentence_ids
                ],
                annotation_origin=annotation.annotator_id,
            )

    def check_version(version: MentionVersion) -> None:
        if version.event_ref not in mentions or mentions[version.event_ref].version != version:
            raise ValueError(f"Unknown or stale mention snapshot: {version.event_ref}")

    def check_quote(quote: EvidenceQuote) -> None:
        notice = documents.get(quote.doc_id)
        if notice is None or notice.text[quote.start : quote.end] != quote.text:
            raise ValueError("Source quote does not match prepared text")
        sentence = next((s for s in notice.sentences if s.sentence_id == quote.sentence_id), None)
        if sentence is None or not sentence.start <= quote.start < quote.end <= sentence.end:
            raise ValueError("Source quote must fit its evidence sentence")

    copied_reviews = sorted(
        [GroupingReview.model_validate(r.model_dump()) for r in reviews], key=lambda r: r.review_id
    )
    seen_ids, seen_pairs = set(), set()
    update_edges = defaultdict(set)
    for review in copied_reviews:
        pair = tuple(sorted((review.left.event_ref, review.right.event_ref)))
        if review.review_id in seen_ids or pair in seen_pairs:
            raise ValueError("Duplicate review ID or pair; adjudicate before assembly")
        seen_ids.add(review.review_id)
        seen_pairs.add(pair)
        check_version(review.left)
        check_version(review.right)
        doc_ids = {mentions[ref].version.event_ref.split(":")[0] for ref in pair}
        if {q.doc_id for q in review.evidence} != doc_ids:
            raise ValueError("Pair evidence must cover exactly the two source documents")
        for quote in review.evidence:
            check_quote(quote)
        for change in review.changes:
            check_quote(change.new)
            if change.new.doc_id != review.left.event_ref.split(":")[0]:
                raise ValueError("New value must come from the update source")
            if change.old:
                check_quote(change.old)
                if change.old.doc_id != review.right.event_ref.split(":")[0]:
                    raise ValueError("Old value must come from the previous source")
        if review.decision == "UPDATE_OF":
            update_edges[review.left.event_ref].add(review.right.event_ref)
    visited, active = set(), set()

    def visit(ref: str) -> None:
        if ref in active:
            raise ValueError("UPDATE_OF cycle requires review")
        if ref in visited:
            return
        active.add(ref)
        for prior in sorted(update_edges.get(ref, set())):
            visit(prior)
        active.remove(ref)
        visited.add(ref)

    for ref in sorted(update_edges):
        visit(ref)

    def is_newer(candidate: str, previous: str) -> bool:
        pending, seen = [candidate], set()
        while pending:
            current = pending.pop()
            if current == previous:
                return True
            if current not in seen:
                seen.add(current)
                pending.extend(update_edges.get(current, set()))
        return False

    boundaries = sorted(
        [TimeBoundaryReview.model_validate(b.model_dump()) for b in time_boundaries or []],
        key=lambda b: (b.mention.event_ref, b.span_id),
    )
    boundary_map, value_keys = {}, {}
    for boundary in boundaries:
        check_version(boundary.mention)
        mention = mentions[boundary.mention.event_ref]
        argument = next((a for a in mention.event.arguments if a.span_id == boundary.span_id), None)
        span = next((s for s in mention.spans if s.span_id == boundary.span_id), None)
        key = (boundary.mention.event_ref, boundary.span_id)
        if key in boundary_map or argument is None or span.label != "TIME":
            raise ValueError("Duplicate or unknown TIME boundary")
        if boundary.boundary != "POINT" and argument.role not in {"START", "EVENT_TIME"}:
            raise ValueError("A deadline cannot be reinterpreted as a session endpoint")
        boundary_map[key] = boundary.boundary
        value_keys[key] = boundary.value_key

    for review in copied_reviews:
        for change in review.changes:
            if change.field not in {"START", "END", "DEADLINE", "EVENT_TIME"}:
                continue
            for version, quote in [(review.left, change.new), (review.right, change.old)]:
                if quote is None:
                    continue
                mention = mentions[version.event_ref]
                spans = {s.span_id: s for s in mention.spans}
                supported = False
                for argument in mention.event.arguments:
                    span = spans[argument.span_id]
                    field = boundary_map.get((version.event_ref, span.span_id))
                    field = field if field in {"START", "END"} else argument.role
                    if (
                        span.label == "TIME"
                        and field == change.field
                        and (
                            quote.start <= span.start
                            and span.end <= quote.end
                            or span.start <= quote.start
                            and quote.end <= span.end
                        )
                    ):
                        supported = True
                if not supported:
                    raise ValueError("TIME update requires an annotated TIME of the same field")

    refs = set(mentions)
    positives = [r for r in copied_reviews if r.decision in {"SAME_EVENT", "UPDATE_OF"}]
    conflicts = []
    group_members = []
    for component in _components(refs, [(r.left.event_ref, r.right.event_ref) for r in positives]):
        negative = [
            r.review_id
            for r in copied_reviews
            if r.decision in {"DIFFERENT_EVENT", "UNCLEAR"}
            and r.left.event_ref in component
            and r.right.event_ref in component
        ]
        if negative:
            conflicts.append(
                GroupConflict(kind="group_contradiction", members=component, review_ids=negative)
            )
            group_members.extend([[member] for member in component])
        else:
            group_members.append(component)
    groups, applications = [], []
    for component in sorted(group_members):
        local = [
            r for r in positives if r.left.event_ref in component and r.right.event_ref in component
        ]
        same_task = [r for r in local if r.task_relation == "SAME_TASK"]
        tasks = []
        for members in _components(
            set(component), [(r.left.event_ref, r.right.event_ref) for r in same_task]
        ):
            separate = [
                r.review_id
                for r in local
                if r.task_relation in {"DIFFERENT_TASK", "DIFFERENT_SESSION", "CONDITIONAL_TASK"}
                and r.left.event_ref in members
                and r.right.event_ref in members
            ]
            if separate:
                conflicts.append(
                    GroupConflict(kind="task_contradiction", members=members, review_ids=separate)
                )
                tasks.extend([[member] for member in members])
            else:
                tasks.append(members)
        built_tasks = []
        for members in sorted(tasks):
            facts = {}

            def add_fact(
                ref: str,
                field: str,
                quote: EvidenceQuote,
                facts: dict[str, GroupedFact],
                span_id=None,
                argument=None,
            ) -> GroupedFact:
                fid = _hash([mentions[ref].version.model_dump(), field, quote.model_dump()])[:24]
                if fid not in facts:
                    facts[fid] = GroupedFact(
                        fact_id=fid,
                        mention_ref=ref,
                        field=field,
                        quote=quote,
                        span_id=span_id,
                        normalized_date=argument.normalized_date if argument else None,
                        inferred=argument.inferred if argument else False,
                        equivalence_key=value_keys.get((ref, span_id)),
                    )
                return facts[fid]

            for ref in members:
                mention = mentions[ref]
                spans = {s.span_id: s for s in mention.spans}
                for argument in mention.event.arguments:
                    span = spans[argument.span_id]
                    sentence = next(
                        s for s in mention.sentences if s.start <= span.start and span.end <= s.end
                    )
                    field = argument.role if span.label == "TIME" else span.label
                    boundary = boundary_map.get((ref, span.span_id))
                    if boundary in {"START", "END"}:
                        field = boundary
                    add_fact(
                        ref,
                        field,
                        EvidenceQuote(
                            doc_id=ref.split(":")[0],
                            sentence_id=sentence.sentence_id,
                            start=span.start,
                            end=span.end,
                            text=span.text,
                        ),
                        facts,
                        span.span_id,
                        argument,
                    )

            def change_fact(
                ref: str, field: str, quote: EvidenceQuote, facts: dict[str, GroupedFact]
            ) -> GroupedFact:
                matching = [
                    f
                    for f in facts.values()
                    if f.mention_ref == ref
                    and f.field == field
                    and (
                        quote.start <= f.quote.start
                        and f.quote.end <= quote.end
                        or f.quote.start <= quote.start
                        and quote.end <= f.quote.end
                    )
                ]
                if len(matching) > 1:
                    raise ValueError(
                        "An update quote covers multiple values; use a complete TIME span"
                    )
                return matching[0] if matching else add_fact(ref, field, quote, facts)

            for review in local:
                if review.decision != "UPDATE_OF" or not {
                    review.left.event_ref,
                    review.right.event_ref,
                } <= set(members):
                    continue
                for change in review.changes:
                    new = change_fact(review.left.event_ref, change.field, change.new, facts)
                    old_ids = []
                    if change.old:
                        old = change_fact(review.right.event_ref, change.field, change.old, facts)
                        equivalent = [
                            f
                            for f in facts.values()
                            if f.field == old.field
                            and _value_key(f) == _value_key(old)
                            and f.fact_id != new.fact_id
                            and not is_newer(f.mention_ref, review.left.event_ref)
                        ]
                        for fact in equivalent:
                            fact.superseded_by = sorted(set(fact.superseded_by) | {new.fact_id})
                            old_ids.append(fact.fact_id)
                    applications.append(
                        UpdateApplication(
                            review_id=review.review_id,
                            field=change.field,
                            old_fact_ids=sorted(old_ids),
                            new_fact_id=new.fact_id,
                            applied=True,
                        )
                    )
            values = defaultdict(list)
            for fact in sorted(facts.values(), key=lambda f: f.fact_id):
                if not fact.superseded_by:
                    values[fact.field].append(fact.fact_id)
            for field, ids in sorted(values.items()):
                distinct = {_value_key(facts[fid]) for fid in ids}
                if (
                    field in {"START", "END", "DEADLINE", "EVENT_TIME", "LOCATION", "STATUS"}
                    and len(distinct) > 1
                ):
                    # Separate hour/date spans are kept, but are not silently combined.
                    conflicts.append(
                        GroupConflict(kind="competing_values", members=members, field=field)
                    )
            built_tasks.append(
                GroupedTask(
                    task_id=_hash(members)[:24],
                    members=members,
                    facts=sorted(facts.values(), key=lambda f: f.fact_id),
                    active_values=dict(sorted(values.items())),
                )
            )
        groups.append(
            BuiltEventGroup(
                group_id=_hash(component)[:24],
                members=component,
                document_ids=sorted({r.split(":")[0] for r in component}),
                tasks=built_tasks,
            )
        )
    for review in copied_reviews:
        if review.decision == "UPDATE_OF" and not any(
            a.review_id == review.review_id for a in applications
        ):
            applications.extend(
                UpdateApplication(
                    review_id=review.review_id,
                    field=c.field,
                    old_fact_ids=[],
                    new_fact_id=None,
                    applied=False,
                )
                for c in review.changes
            )
    return EventGroupAssembly(
        mentions=[mentions[r] for r in sorted(mentions)],
        reviews=copied_reviews,
        time_boundaries=boundaries,
        groups=sorted(groups, key=lambda g: g.group_id),
        updates=sorted(applications, key=lambda a: (a.review_id, a.field)),
        conflicts=sorted(conflicts, key=lambda c: (c.kind, c.members, c.field or "")),
    )
