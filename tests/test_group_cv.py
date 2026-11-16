"""Check Group K-fold against event reviews and frozen split boundaries."""

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from smartnotice.labeling.event_groups import assembly_fingerprint
from smartnotice.preprocessing.group_cv import allocate_group_folds, plan_group_folds
from smartnotice.schemas import FrozenGroupAssignment, GroupReviewNote, LocalGroupReviewNotes
from test_group_assembly import assemble, make_notice, review


@pytest.fixture
def reviewed_corpus():
    items = [make_notice(f"{i:020x}") for i in range(1, 13)]
    a, b, c, holdout, d, e, *_ = items
    assembly = assemble(
        items,
        [review(a, b, rid="first"), review(c, holdout, rid="protected"), review(d, e, rid="open")],
    )
    confirmed = {a[0].doc_id, c[0].doc_id}
    now = datetime(2026, 11, 16, tzinfo=UTC)
    notes = LocalGroupReviewNotes(
        kind="local_group_review_notes",
        draft=True,
        assembly_fingerprint=assembly_fingerprint(assembly),
        exported_at=now,
        entries=[
            GroupReviewNote(
                group_id=g.group_id,
                status="looks_ok" if confirmed.intersection(g.document_ids) else "needs_check",
                text="Synthetic free text that does not change membership.",
                updated_at=now,
            )
            for g in assembly.groups
        ],
    )
    rows = [
        FrozenGroupAssignment(
            doc_id=n.doc_id,
            group_id=f"{2 if i == 3 else i:020x}",
            split="test" if i == 4 else ("domain_test" if i == 12 else "train"),
            text_sha256=sha256(n.text.encode()).hexdigest(),
        )
        for i, (n, _) in enumerate(items, 1)
    ]
    return rows, assembly, notes


def test_quarantine_is_transitive_and_unreviewed_links_do_not_merge(reviewed_corpus):
    rows, assembly, notes = reviewed_corpus
    plan, links = plan_group_folds(rows, assembly, notes, n_splits=3)
    a, b, c, holdout, d, e, *_, domain = plan
    assert len(links) == 2
    assert len({a.fold_group_id, b.fold_group_id, c.fold_group_id, holdout.fold_group_id}) == 1
    assert all(
        row.fold is None and row.exclusion_reason == "linked_to_outside_train" for row in (a, b, c)
    )
    assert holdout.split == "test" and domain.split == "domain_test"
    assert holdout.fold is None and domain.fold is None
    assert d.fold_group_id != e.fold_group_id
    assert {r.fold for r in plan if r.fold is not None} == {0, 1, 2}


def test_group_kfold_keeps_eligible_event_and_source_groups_together(reviewed_corpus):
    rows, assembly, notes = reviewed_corpus
    rows[3] = rows[3].model_copy(update={"split": "train"})
    result = plan_group_folds(rows, assembly, notes, n_splits=3, seed=12)
    assignments, _ = result
    assert {r.fold for r in assignments[:4]} == {0}
    for fold in range(3):
        train = {r.fold_group_id for r in assignments if r.fold is not None and r.fold != fold}
        validation = {r.fold_group_id for r in assignments if r.fold == fold}
        assert train.isdisjoint(validation)
    assert result == plan_group_folds(list(reversed(rows)), assembly, notes, n_splits=3, seed=12)


def test_precautionary_constraint_joins_documents_without_event_acceptance(reviewed_corpus):
    rows, _, _ = reviewed_corpus
    left, right = (row.doc_id for row in rows[4:6])
    assignments = allocate_group_folds(rows, [[left, right]], n_splits=3)
    by_doc = {row.doc_id: row for row in assignments}
    assert by_doc[left].fold_group_id == by_doc[right].fold_group_id
    assert by_doc[left].fold == by_doc[right].fold
    with pytest.raises(ValueError, match="unknown document"):
        allocate_group_folds(rows, [[left, "f" * 20]], n_splits=3)


def test_refuses_stale_review_and_text_and_impossible_fold_count(reviewed_corpus):
    rows, assembly, notes = reviewed_corpus
    with pytest.raises(ValueError, match="fingerprint"):
        plan_group_folds(
            rows, assembly, notes.model_copy(update={"assembly_fingerprint": "0" * 64})
        )
    with pytest.raises(ValueError, match="eligible groups"):
        plan_group_folds(rows, assembly, notes, n_splits=len(rows))
    rows[0] = rows[0].model_copy(update={"text_sha256": "0" * 64})
    with pytest.raises(ValueError, match="stale assembly mention"):
        plan_group_folds(rows, assembly, notes)
