"""Apply source-bound user group feedback without inventing pair-level reviews."""

from itertools import combinations

from smartnotice.labeling.event_groups import assembly_fingerprint
from smartnotice.schemas import (
    AppliedGroupFeedback,
    EventGroupAssembly,
    EvidenceQuote,
    GroupFeedbackResolution,
    GroupFeedbackResult,
    GroupingReview,
    GroupMergeResolution,
    LocalGroupReviewNotes,
    ReviewAuthor,
)


def apply_group_feedback(
    assembly: EventGroupAssembly,
    notes: LocalGroupReviewNotes,
    resolutions: list[GroupFeedbackResolution],
    *,
    notes_sha256: str,
    application_author: ReviewAuthor,
    merges: list[GroupMergeResolution] | None = None,
) -> GroupFeedbackResult:
    """Derive pair decisions from group notes and explicit content resolutions.

    Validate the viewed assembly fingerprint and every complete partition before
    changing decisions. A split replaces crossing positive edges; adding only a
    negative edge would leave a contradictory component. Retain within-partition
    task relations and updates. Notes on one group do not approve cross-group
    pairs, other groups, annotation labels, dates or privacy clearance.

    Free-text split notes require caller-supplied resolutions; never infer a
    partition from prose. Derived decisions retain an assistant application
    author, while the original user notes and timestamps remain in a separate
    ledger. Explicit merges join supplied groups while preserving their separate
    steps; they replace every crossing decision rather than creating a conflicting
    positive bridge. Merge groups require submitted notes and cannot also split.
    Reject stale, duplicate, incomplete or unsupported input with
    ValueError, without mutating the source assembly or notes.
    """
    notes = LocalGroupReviewNotes.model_validate(notes.model_dump())
    if notes.assembly_fingerprint != assembly_fingerprint(assembly):
        raise ValueError("Review notes target a different assembly fingerprint")
    if application_author.reviewer_kind != "ai_assistant":
        raise ValueError("Automated feedback application requires assistant attribution")
    groups = {g.group_id: g for g in assembly.groups}
    note_map = {n.group_id: n for n in notes.entries}
    plans = {r.group_id: r for r in resolutions}
    if len(plans) != len(resolutions):
        raise ValueError("Duplicate group resolution")
    if set(note_map) - groups.keys() or set(plans) - note_map.keys():
        raise ValueError("Unknown group or resolution without a user note")
    merges = [GroupMergeResolution.model_validate(m.model_dump()) for m in merges or []]
    merged_ids = set()
    for merge in merges:
        selected = set(merge.group_ids)
        if len(selected) != len(merge.group_ids) or selected & merged_ids:
            raise ValueError("Duplicate or overlapping merge groups")
        if not selected <= note_map.keys():
            raise ValueError("A merge requires a submitted note for every selected group")
        if any(gid in plans and plans[gid].mode != "ACCEPT" for gid in selected):
            raise ValueError("A group cannot both split and merge in the same application")
        if any(note_map[gid].status == "not_seen" for gid in selected):
            raise ValueError("Unread feedback cannot supply a merge resolution")
        merged_ids.update(selected)
    reviews = [r.model_copy(deep=True) for r in assembly.reviews]
    mentions = {m.version.event_ref: m for m in assembly.mentions}
    applications = []

    def member_evidence(ref: str) -> list[EvidenceQuote]:
        mention = mentions[ref]
        return [
            EvidenceQuote(
                doc_id=ref.split(":")[0],
                sentence_id=s.sentence_id,
                start=s.start,
                end=s.end,
                text=s.text,
            )
            for s in mention.sentences
        ]

    for gid, note in sorted(note_map.items()):
        group = groups[gid]
        plan = plans.get(gid)
        partitions = [sorted(group.members)]
        affected = []
        additional = []
        rationale = "User group feedback preserved without changing annotation or time labels."
        if note.status in {"not_seen", "needs_check"}:
            if plan is not None:
                raise ValueError("Deferred or unread notes cannot supply an accepted resolution")
            outcome = "not_reviewed" if note.status == "not_seen" else "deferred"
        else:
            if note.status == "suggest_split" and (plan is None or plan.mode == "ACCEPT"):
                raise ValueError("Split feedback requires an explicit resolution")
            if note.status == "looks_ok" and plan is not None and plan.mode != "ACCEPT":
                raise ValueError("Accepted feedback cannot be silently converted into a split")
            outcome = "accepted"
            if plan:
                rationale = plan.rationale
                additional = plan.additional_members
                if plan.mode == "PARTITION":
                    flattened = [ref for part in plan.partitions for ref in part]
                    if (
                        len(plan.partitions) < 2
                        or any(not p for p in plan.partitions)
                        or sorted(flattened) != sorted(group.members)
                    ):
                        raise ValueError("A split partition must cover old members exactly once")
                    if additional:
                        raise ValueError("A partition cannot silently add new members")
                    partitions = sorted(sorted(part) for part in plan.partitions)
                    outcome = "partitioned"
                elif plan.mode == "SEPARATE_CONTENT":
                    if not additional or any(ref in mentions for ref in additional):
                        raise ValueError("Content separation requires distinct additional mentions")
                    if len(additional) != len(set(additional)):
                        raise ValueError("Duplicate additional content member")
                    outcome = "content_separated"
            ownership = {ref: i for i, part in enumerate(partitions) for ref in part}
            local = [
                r
                for r in reviews
                if r.left.event_ref in ownership and r.right.event_ref in ownership
            ]
            for review in local:
                if ownership[review.left.event_ref] != ownership[review.right.event_ref]:
                    review.decision = "DIFFERENT_EVENT"
                    review.task_relation = "UNRESOLVED"
                    review.notice_relation = "OTHER"
                    review.changes = []
                    review.author = application_author.model_copy(deep=True)
                    review.rationale = rationale
                    affected.append(review.review_id)
                if plan and plan.evidence:
                    doc_ids = {
                        review.left.event_ref.split(":")[0],
                        review.right.event_ref.split(":")[0],
                    }
                    review.evidence.extend(
                        q.model_copy(deep=True)
                        for q in plan.evidence
                        if q.doc_id in doc_ids and q not in review.evidence
                    )
                    review.author = application_author.model_copy(deep=True)
                    if review.review_id not in affected:
                        affected.append(review.review_id)
            if outcome == "partitioned":
                known = {tuple(sorted((r.left.event_ref, r.right.event_ref))) for r in reviews}
                for index, (left, right) in enumerate(combinations(sorted(group.members), 2), 1):
                    if ownership[left] == ownership[right] or (left, right) in known:
                        continue
                    rid = f"feedback-{gid[:8]}-{index:03}"
                    if any(r.review_id == rid for r in reviews):
                        raise ValueError("Derived feedback review ID collision")
                    reviews.append(
                        GroupingReview(
                            review_id=rid,
                            left=mentions[left].version,
                            right=mentions[right].version,
                            decision="DIFFERENT_EVENT",
                            task_relation="UNRESOLVED",
                            author=application_author,
                            rationale=rationale,
                            evidence=member_evidence(left) + member_evidence(right),
                        )
                    )
                    affected.append(rid)
            if outcome == "accepted":
                affected = sorted(set(affected) | {r.review_id for r in local})
        applications.append(
            AppliedGroupFeedback(
                note=note.model_copy(deep=True),
                outcome=outcome,
                partitions=partitions,
                additional_members=additional,
                rationale=rationale,
                affected_review_ids=sorted(affected),
                application_author=application_author,
            )
        )
    for merge in merges:
        ownership = {ref: gid for gid in merge.group_ids for ref in groups[gid].members}
        combined = sorted(ownership)
        affected = []
        pairs = {frozenset((r.left.event_ref, r.right.event_ref)): r for r in reviews}
        for left, right in combinations(combined, 2):
            if ownership[left] == ownership[right]:
                continue
            key = frozenset((left, right))
            evidence = member_evidence(left) + member_evidence(right)
            docs = {q.doc_id for q in evidence}
            evidence += [q for q in merge.evidence if q.doc_id in docs and q not in evidence]
            if key in pairs:
                review = pairs[key]
                review.decision = "SAME_EVENT"
                review.task_relation = merge.task_relation
                review.notice_relation = "OTHER"
                review.changes = []
                review.author = application_author.model_copy(deep=True)
                review.rationale = merge.rationale
                review.evidence = evidence
            else:
                rid = f"merge-{ownership[left][:8]}-{left}-{right}"
                if any(r.review_id == rid for r in reviews):
                    raise ValueError("Derived merge review ID collision")
                review = GroupingReview(
                    review_id=rid,
                    left=mentions[left].version,
                    right=mentions[right].version,
                    decision="SAME_EVENT",
                    task_relation=merge.task_relation,
                    author=application_author,
                    rationale=merge.rationale,
                    evidence=evidence,
                )
                reviews.append(review)
            affected.append(review.review_id)
        for application in applications:
            if application.note.group_id in merge.group_ids:
                application.outcome = "merged"
                application.partitions = [combined]
                application.rationale = merge.rationale
                application.affected_review_ids = sorted(
                    set(application.affected_review_ids + affected)
                )
    return GroupFeedbackResult(
        notes_sha256=notes_sha256,
        source_assembly_fingerprint=notes.assembly_fingerprint,
        reviews=sorted(reviews, key=lambda r: r.review_id),
        applications=applications,
        unreviewed_group_ids=sorted(groups.keys() - note_map.keys()),
    )
