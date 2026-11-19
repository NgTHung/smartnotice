"""Check source-item reranking and its abstentions on synthetic reply items."""

import math
from dataclasses import replace

import pytest
from smartnotice.labeling.grouping_alignment import FollowupAlignment
from smartnotice.labeling.grouping_followup import RoutingComparison
from smartnotice.labeling.grouping_rerank import (
    FEATURES,
    FollowupRerankModel,
    followup_rerank_features,
    followup_rerank_score,
    rerank_followup_mentions,
)
from test_followup_alignment import _profiles

DIRECT = RoutingComparison(1, 600, False, True)


def _checkpoint(*, intercept: float = -0.8, weight: float = 9.0) -> FollowupRerankModel:
    coefficients = [0.0] * len(FEATURES)
    coefficients[FEATURES.index("evidence_concept_jaccard")] = weight
    return FollowupRerankModel(
        features=list(FEATURES),
        mean=[0.0] * len(FEATURES),
        scale=[1.0] * len(FEATURES),
        weights=coefficients,
        intercept=intercept,
    )


def test_reranker_picks_scoped_paraphrase_over_other_parent_action():
    parent = _profiles(
        "parent",
        ["1. Kiểm tra cổng đăng ký sau sự cố.", "2. Nộp phiếu đề nghị thanh toán."],
        [0, 1],
    )
    reply = _profiles("reply", ["Hệ thống đăng ký hoạt động trở lại."], [0])
    matches = rerank_followup_mentions(parent, reply, DIRECT, _checkpoint(), {})
    assert matches == {
        ("parent:a0", "reply:a0"): FollowupAlignment("reranked_reply_match", (("s0",), ("s0",)))
    }
    reverse = RoutingComparison(0, 600, False, True)
    assert set(rerank_followup_mentions(reply, parent, reverse, _checkpoint(), {})) == {
        ("reply:a0", "parent:a0")
    }


def test_competing_items_or_existing_alignment_reserve_the_reply():
    parent = _profiles("parent", ["1. Kiểm tra cổng đăng ký sau sự cố."], [0])
    reply = _profiles("reply", ["Hệ thống đăng ký hoạt động trở lại."], [0])
    equivalent_runner_up = replace(parent[0], mention_id="parent:other")
    assert not rerank_followup_mentions(
        [*parent, equivalent_runner_up], reply, DIRECT, _checkpoint(), {}
    )
    existing = {("parent:a0", "reply:a0"): FollowupAlignment("prior", (("s0",), ("s0",)))}
    assert not rerank_followup_mentions(parent, reply, DIRECT, _checkpoint(), existing)


def test_scope_conflict_and_unverified_parent_abstain_at_high_score():
    parent = _profiles("parent", ["Kiểm tra cổng đăng ký sau sự cố, đợt 1."], [0])
    reply = _profiles("reply", ["Hệ thống đăng ký hoạt động trở lại. Đợt 2."], [0])
    checkpoint = _checkpoint(intercept=3.0)
    assert not rerank_followup_mentions(parent, reply, DIRECT, checkpoint, {})
    separate = RoutingComparison(1, 600, True, False)
    assert not rerank_followup_mentions(parent, reply, separate, checkpoint, {})
    unrelated = _profiles("other", ["Nhận biên lai đóng phí."], [0])
    assert not rerank_followup_mentions(parent, unrelated, DIRECT, checkpoint, {})


def test_checkpoint_rejects_bad_feature_order_and_non_finite_state():
    checkpoint = _checkpoint()
    model_dict = checkpoint.model_dump()
    model_dict["features"] = model_dict["features"][::-1]
    with pytest.raises(ValueError, match="version mismatch"):
        FollowupRerankModel.model_validate(model_dict)
    checkpoint.weights[0] = math.nan
    parent = _profiles("parent", ["Kiểm tra cổng đăng ký sau sự cố."], [0])
    reply = _profiles("reply", ["Hệ thống đăng ký hoạt động trở lại."], [0])
    features = followup_rerank_features(parent[0], reply[0])
    with pytest.raises(ValueError, match="finite"):
        followup_rerank_score(checkpoint, features)
