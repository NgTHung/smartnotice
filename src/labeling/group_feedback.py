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
    ledger. Reject stale, duplicate, incomplete or unsupported input with
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
    return GroupFeedbackResult(
        notes_sha256=notes_sha256,
        source_assembly_fingerprint=notes.assembly_fingerprint,
        reviews=sorted(reviews, key=lambda r: r.review_id),
        applications=applications,
        unreviewed_group_ids=sorted(groups.keys() - note_map.keys()),
    )
