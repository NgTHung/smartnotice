from collections import Counter

import pytest
from smartnotice.preprocessing.frozen_split import allocate_frozen_groups


def _documents(notices, count=20):
    return [
        notices[0].model_copy(
            update={"doc_id": str(i), "group_id": str(i), "domain_holdout": False}
        )
        for i in range(count)
    ]


def test_equal_groups_target_ratio_and_are_order_independent(notices):
    docs = _documents(notices)
    groups = {n.doc_id: n.group_id for n in docs}
    features = {n.doc_id: {"source:email": 1} for n in docs}
    rows = allocate_frozen_groups(docs, groups, features)
    assert Counter(row["split"] for row in rows) == {"train": 13, "validation": 3, "test": 4}
    assert allocate_frozen_groups(docs[::-1], groups, features)[::-1] == rows


def test_new_duplicate_inherits_frozen_test(notices):
    docs = _documents(notices, 2)
    rows = allocate_frozen_groups(
        docs,
        {"0": "merged", "1": "merged"},
        {"0": {}, "1": {}},
        previous=[{"doc_id": "0", "split": "test"}],
    )
    assert [row["split"] for row in rows] == ["test", "test"]


def test_conflicting_frozen_merge_is_rejected(notices):
    docs = _documents(notices, 2)
    with pytest.raises(ValueError, match="Conflicting"):
        allocate_frozen_groups(
            docs,
            {"0": "merged", "1": "merged"},
            {"0": {}, "1": {}},
            previous=[{"doc_id": "0", "split": "train"}, {"doc_id": "1", "split": "test"}],
        )


def test_reserved_group_and_later_email_stay_outside_ordinary_pool(notices):
    docs = _documents(notices, 2)
    docs[0] = docs[0].model_copy(update={"source_type": "web", "domain_holdout": True})
    rows = allocate_frozen_groups(docs, {"0": "g", "1": "g"}, {"0": {}, "1": {}})
    assert [row["split"] for row in rows] == ["domain_test", "excluded"]


def test_rare_feature_is_balanced_when_groups_allow_it(notices):
    docs = _documents(notices, 100)
    groups = {n.doc_id: n.group_id for n in docs}
    features = {n.doc_id: {"rare": int(int(n.doc_id) < 20)} for n in docs}
    rows = allocate_frozen_groups(docs, groups, features)
    rare = Counter(row["split"] for row in rows if int(row["doc_id"]) < 20)
    for name, target in {"train": 13, "validation": 3, "test": 4}.items():
        assert abs(rare[name] - target) <= 1


def test_changed_frozen_text_is_rejected(notices):
    docs = _documents(notices, 1)
    rows = allocate_frozen_groups(docs, {"0": "g"}, {"0": {}})
    docs[0] = docs[0].model_copy(update={"text": "Changed prepared text"})
    with pytest.raises(ValueError, match="Frozen text changed"):
        allocate_frozen_groups(docs, {"0": "g"}, {"0": {}}, previous=rows)
