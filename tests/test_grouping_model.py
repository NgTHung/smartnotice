"""Check symmetric grouping features, source binding and model replay."""

import pytest
from smartnotice.labeling.grouping_model import (
    FEATURES,
    fit_grouping_classifier,
    grouping_probability,
    pair_features,
    validate_grouping_mention,
)
from smartnotice.schemas import GroupingLinearModel, GroupingModelMention
from test_group_assembly import assemble, make_notice


def test_grouping_features_are_symmetric_and_source_bound():
    items = [make_notice("a"), make_notice("b", action="Kiểm tra lịch học")]
    assembly = assemble(items, [])
    a, b = [
        GroupingModelMention(
            mention_id=m.version.event_ref,
            doc_id=m.version.event_ref.split(":")[0],
            **m.model_dump(exclude={"annotation_origin"}),
        )
        for m in assembly.mentions
    ]
    validate_grouping_mention(a, items[0][0])
    assert pair_features(a, b) == pair_features(b, a)
    assert pair_features(a, a)[0] > pair_features(a, b)[0]
    stale = items[0][0].model_copy(update={"text": "Văn bản đã sửa."})
    with pytest.raises(ValueError, match="Stale grouping mention"):
        validate_grouping_mention(a, stale)


def test_grouping_model_learns_and_replays_from_json():
    pytest.importorskip("sklearn")
    near = (1.0,) * len(FEATURES)
    far = (0.0,) * len(FEATURES)
    model = fit_grouping_classifier([near, near, far, far], [True, True, False, False], seed=42)
    restored = GroupingLinearModel.model_validate_json(model.model_dump_json())
    assert grouping_probability(restored, near) > restored.threshold
    assert grouping_probability(restored, far) < restored.threshold
