from pathlib import Path

from smartnotice.cli import main
from smartnotice.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]


def test_offline_demo_exercises_data_and_annotation_pipeline():
    result = run_demo(ROOT)
    assert result["document_count"] == result["synthetic_count"] == 9
    assert result["applicability_pair_count"] == 30
    assert result["split_group_leaks"] == []


def test_cli_annotation_validation(notices, tmp_path, capsys):
    from smartnotice.io import write_jsonl

    path = tmp_path / "notices.jsonl"
    write_jsonl(path, [notice.model_dump(mode="json") for notice in notices])
    main(
        [
            "validate-labels",
            "--notices",
            str(path),
            "--annotations",
            str(ROOT / "data/annotations/examples/events.jsonl"),
        ]
    )
    assert "Validated 5 annotations" in capsys.readouterr().out
