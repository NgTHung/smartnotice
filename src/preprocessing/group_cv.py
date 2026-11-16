"""Keep reviewed event families and frozen document groups together in CV."""

import hashlib
import random
from collections import defaultdict

from smartnotice.labeling.event_groups import assembly_fingerprint
from smartnotice.preprocessing.split import DEFAULT_SEED
from smartnotice.schemas import (
    EventGroupAssembly,
    FrozenGroupAssignment,
    GroupFoldAssignment,
    LocalGroupReviewNotes,
    ReviewedEventLink,
)


def event_group_documents(
    assembly: EventGroupAssembly, assignments: list[FrozenGroupAssignment]
) -> dict[str, list[str]]:
    """Resolve event group membership against the frozen prepared text hashes.

    Return distinct, sorted document IDs per group. Reject stale text, unknown
    members and invalid partitions with ValueError. This joins metadata only;
    it does not validate annotation semantics or approve groups.
    """
    text_hashes = {row.doc_id: row.text_sha256 for row in assignments}
    mentions = {}
    for mention in assembly.mentions:
        ref = mention.version.event_ref
        doc_id, separator, span_id = ref.partition(":")
        if (
            ref in mentions
            or not separator
            or span_id != mention.event.action_span_id
            or text_hashes.get(doc_id) != mention.version.text_sha256
        ):
            raise ValueError(f"Invalid, unknown or stale assembly mention for document {doc_id}")
        mentions[ref] = doc_id
    groups = {}
    seen = set()
    for group in assembly.groups:
        members = set(group.members)
        if (
            group.group_id in groups
            or not members
            or len(members) != len(group.members)
            or seen.intersection(members)
            or members.difference(mentions)
        ):
            raise ValueError(f"Invalid membership in event group {group.group_id}")
        docs = sorted({mentions[ref] for ref in members})
        if sorted(group.document_ids) != docs:
            raise ValueError(f"Document IDs disagree with members in event group {group.group_id}")
        groups[group.group_id] = docs
        seen.update(members)
    if seen != mentions.keys():
        raise ValueError("Event groups do not cover all assembly mentions")
    return groups


def plan_group_folds(
    assignments: list[FrozenGroupAssignment],
    assembly: EventGroupAssembly,
    notes: LocalGroupReviewNotes,
    *,
    n_splits: int = 5,
    seed: int = DEFAULT_SEED,
) -> tuple[list[GroupFoldAssignment], list[ReviewedEventLink]]:
    """Plan train-only Group K-fold from frozen groups and snapshot-bound notes.

    Only looks_ok supplies links; free text supplies no link or task. Merge
    links transitively at document level. Components touching any other frozen
    split are ineligible for CV. Put larger eligible groups first in the least
    populated fold, using a local seeded shuffle to break equal-size ties.
    Return one row per source document and the accepted multi-document links.
    Raise ValueError for invalid inputs or fewer eligible groups than folds.
    """
    if notes.assembly_fingerprint != assembly_fingerprint(assembly):
        raise ValueError("Review notes do not match the assembly fingerprint")
    event_docs = event_group_documents(assembly, assignments)
    if any(note.group_id not in event_docs for note in notes.entries):
        raise ValueError("Review notes reference an unknown event group")
    reviewed_links = [
        ReviewedEventLink(event_group_id=note.group_id, doc_ids=event_docs[note.group_id])
        for note in sorted(notes.entries, key=lambda note: note.group_id)
        if note.status == "looks_ok" and len(event_docs[note.group_id]) > 1
    ]
    rows = allocate_group_folds(
        assignments, [link.doc_ids for link in reviewed_links], n_splits=n_splits, seed=seed
    )
    return rows, reviewed_links


def allocate_group_folds(
    assignments: list[FrozenGroupAssignment],
    coassignments: list[list[str]],
    *,
    n_splits: int = 5,
    seed: int = DEFAULT_SEED,
) -> list[GroupFoldAssignment]:
    """Allocate train-only folds with extra document co-assignment constraints.

    Each list in coassignments names documents to keep together in CV. It does
    not establish event identity. Return one row per assignment, with a null
    fold outside components wholly in train. Reject duplicate documents,
    unknown constraint members, and invalid or infeasible fold counts.
    """
    by_doc = {row.doc_id: row for row in assignments}
    if len(by_doc) != len(assignments):
        raise ValueError("Frozen document IDs must be unique")
    if n_splits < 2:
        raise ValueError("Group K-fold requires at least two folds")
    frozen_groups = defaultdict(list)
    for row in assignments:
        frozen_groups[row.group_id].append(row.doc_id)
    parents = {doc_id: doc_id for doc_id in by_doc}

    def root(doc_id: str) -> str:
        while parents[doc_id] != doc_id:
            parents[doc_id] = parents[parents[doc_id]]
            doc_id = parents[doc_id]
        return doc_id

    for docs in list(frozen_groups.values()) + coassignments:
        if not by_doc.keys() >= set(docs):
            raise ValueError("Co-assignment references an unknown document")
        for doc_id in docs[1:]:
            parents[root(doc_id)] = root(docs[0])
    components = defaultdict(list)
    for doc_id in sorted(by_doc):
        components[root(doc_id)].append(doc_id)
    fold_groups = {
        hashlib.sha256("|".join(docs).encode("utf-8")).hexdigest()[:20]: docs
        for docs in components.values()
    }
    eligible = sorted(
        key for key, docs in fold_groups.items() if all(by_doc[d].split == "train" for d in docs)
    )
    if len(eligible) < n_splits:
        raise ValueError(f"Requested {n_splits} folds but only {len(eligible)} eligible groups")
    random.Random(seed).shuffle(eligible)
    eligible.sort(key=lambda key: len(fold_groups[key]), reverse=True)
    sizes = [0] * n_splits
    fold_by_group = {}
    for key in eligible:
        fold = min(range(n_splits), key=sizes.__getitem__)
        fold_by_group[key] = fold
        sizes[fold] += len(fold_groups[key])
    result = []
    for key, docs in fold_groups.items():
        fold = fold_by_group.get(key)
        for doc_id in docs:
            row = by_doc[doc_id]
            reason = None
            if row.split != "train":
                reason = "outside_train"
            elif fold is None:
                reason = "linked_to_outside_train"
            result.append(
                GroupFoldAssignment(
                    doc_id=doc_id,
                    group_id=row.group_id,
                    split=row.split,
                    fold_group_id=key,
                    fold=fold,
                    exclusion_reason=reason,
                )
            )
    return sorted(result, key=lambda row: row.doc_id)
