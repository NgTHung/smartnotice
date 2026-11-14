from datetime import date

import pandas as pd
import pytest
from smartnotice.quality import reference_date_counts


def test_reference_dates_keep_calendar_gaps_years_and_source_totals(notices):
    rows = [
        notices[0].model_copy(update={"source_type": source, "reference_date": value})
        for source, value in [
            ("web", date(2025, 12, 31)),
            ("email", date(2026, 2, 1)),
            ("email", date(2026, 2, 28)),
            ("web", None),
            ("email", date(2026, 12, 1)),
        ]
    ]
    monthly, coverage = reference_date_counts(rows)
    assert list(monthly.index.astype(str)) == [
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
        "2026-12",
    ]
    assert monthly.loc["2026-01"].to_dict() == {"email": 0, "web": 0}
    assert monthly.loc["2026-02"].to_dict() == {"email": 2, "web": 0}
    assert monthly.sum().to_dict() == {"email": 3, "web": 1}
    assert coverage.to_dict("index") == {
        "email": {"total": 3, "dated": 3, "missing": 0},
        "web": {"total": 2, "dated": 1, "missing": 1},
    }


@pytest.mark.parametrize("empty", [False, True])
def test_missing_dates_never_use_publication_candidates(notices, empty):
    rows = (
        []
        if empty
        else [
            notices[0].model_copy(
                update={
                    "source_type": "web",
                    "reference_date": None,
                    "publication_date_candidate": date(2026, 10, 20),
                }
            )
        ]
    )
    monthly, coverage = reference_date_counts(rows)
    assert monthly.empty
    assert isinstance(monthly.index, pd.PeriodIndex)
    assert coverage.to_dict("index") == (
        {} if empty else {"web": {"total": 1, "dated": 0, "missing": 1}}
    )


def test_single_month_retains_source_with_only_missing_dates(notices):
    rows = [
        notices[0].model_copy(update={"source_type": "email", "reference_date": None}),
        notices[0].model_copy(update={"source_type": "web", "reference_date": date(2026, 1, 1)}),
    ]
    monthly, coverage = reference_date_counts(rows)
    assert monthly.index.astype(str).tolist() == ["2026-01"]
    assert monthly.iloc[0].to_dict() == {"email": 0, "web": 1}
    assert monthly.sum().equals(coverage.dated.rename_axis("source_type"))


@pytest.mark.parametrize("scenario", ["single", "sparse", "missing", "changed"])
def test_notebook_histogram_exports(notices, tmp_path, monkeypatch, scenario):
    import hashlib
    import json
    from pathlib import Path

    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    monkeypatch.setattr(plt, "show", lambda: None)
    notebook = json.loads(
        (Path(__file__).resolve().parents[1] / "notebooks/02_eda.ipynb").read_text(encoding="utf-8")
    )
    code = next(c for c in notebook["cells"] if c.get("id") == "reference-date-histogram")
    notice_path = tmp_path / "notices.jsonl"
    rows = [
        notices[0].model_copy(update={"source_type": source, "reference_date": date(2026, 10, 1)})
        for source in ["email", "web"]
    ]
    if scenario == "sparse":
        rows[0] = rows[0].model_copy(update={"reference_date": date(2024, 2, 29)})
    elif scenario == "missing":
        rows = [row.model_copy(update={"reference_date": None}) for row in rows]
    notice_path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")
    input_hash = hashlib.sha256(notice_path.read_bytes()).hexdigest()
    namespace = {
        "notices": rows,
        "pd": pd,
        "plt": plt,
        "display": lambda value: None,
        "ROOT": tmp_path,
        "NOTICE_PATH": notice_path,
        "NOTICE_SHA256": input_hash,
        "FIGURES": tmp_path,
        "DATASET": "test",
    }
    if scenario == "changed":
        notice_path.write_text("changed after setup\n", encoding="utf-8")
        with pytest.raises(ValueError, match="changed.*rerun"):
            exec(compile("".join(code["source"]), "reference-date-histogram", "exec"), namespace)
        assert not list(tmp_path.glob("eda_reference_dates*"))
        plt.close("all")
        return
    exec(compile("".join(code["source"]), "reference-date-histogram", "exec"), namespace)
    axis = namespace["axis"]
    left, right = axis.get_xlim()
    for bar in axis.patches:
        assert left <= bar.get_x() < bar.get_x() + bar.get_width() <= right
    if scenario == "single":
        assert [label.get_text() for label in axis.get_xticklabels()] == ["2026-10"]
        assert sorted(bar.get_height() for bar in axis.patches) == [1, 1]
    elif scenario == "sparse":
        assert len(namespace["monthly"]) == 33
        assert sum(bar.get_height() for bar in axis.patches) == 2
        assert len(axis.get_xticklabels()) <= 18
    else:
        assert not axis.patches
        assert "No reference dates" in axis.texts[0].get_text()
    exported_monthly = pd.read_csv(tmp_path / "eda_reference_dates_monthly.csv", index_col=0)
    exported_coverage = pd.read_csv(tmp_path / "eda_reference_dates_coverage.csv", index_col=0)
    assert int(exported_monthly.to_numpy().sum()) == (0 if scenario == "missing" else 2)
    assert int(exported_coverage.total.sum()) == len(rows)
    assert exported_coverage.dated.to_dict() == namespace["monthly"].sum().to_dict()
    record = json.loads((tmp_path / "eda_reference_dates_run.json").read_text(encoding="utf-8"))
    assert record["notice_sha256"] == input_hash
    assert record["documents"] == len(rows)
    assert record["dated_documents"] == int(exported_coverage.dated.sum())
    assert record["missing_documents"] == int(exported_coverage.missing.sum())
    assert (tmp_path / "eda_reference_dates.png").stat().st_size > 0
