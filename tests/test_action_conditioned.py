import re
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
runner = runpy.run_path(str(Path(__file__).parents[1] / "tools/run_action_conditioned.py"))


def test_role_selectors_share_a_date_across_actions_and_keep_sentence_offsets():
    text = "Nộp đơn. Gửi bản sao. 20/11."
    first = (0, 7, "ACTION")
    second = (9, 20, "ACTION")
    date = (22, 27, "TIME")
    doc = {
        "id": "fixture",
        "text": text,
        "sentences": [(0, 8), (9, 21), (22, 28)],
        "spans": [first, second, date],
        "links": [(first, date, "START"), (second, date, "DEADLINE")],
    }
    offsets = [m.span() for m in re.finditer(r"\w+|[^\w\s]", text)]
    tokens = SimpleNamespace(offsets=offsets, ids=list(range(4, 4 + len(offsets))))
    runner["_windows"]([doc], SimpleNamespace(encode=lambda s, add_special_tokens: tokens))
    examples = runner["_examples"]([doc], "role")
    assert {ex[1] for ex in examples} == {first, second}
    for example in examples:
        i, j, role = example[-1][0]
        assert (offsets[i][0], offsets[j][1]) == date[:2]
        assert runner["ROLES"][role] == ("START" if example[1] == first else "DEADLINE")
        _, mask, _ = runner["_batch"]([example], torch.device("cpu"))
        assert mask[0, i, j] and not mask[0, 0, j]
