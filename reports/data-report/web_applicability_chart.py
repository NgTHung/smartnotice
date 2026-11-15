"""Plot measured event-level diagnostics, preserving denominators and label origin.

Run from the repository root after ``web_applicability_stats.py``:

    uv run python reports/data-report/web_applicability_chart.py

The script reads ``reports/generated/data-report/web-applicability/summary.json``
and saves ``reports/data-report/figures/web_email_applicability.png``. Rates are
silver-label diagnostics, not model accuracy.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "reports/generated/data-report/web-applicability/summary.json"
FIGURES = ROOT / "reports/data-report/figures"
summary = json.loads(SUMMARY.read_text(encoding="utf-8"))["summaries"]
names = {
    key: f"{source} · {summary[key]['documents']} tài liệu"
    for key, source in [("web_development", "Web"), ("email_development", "Email")]
}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
fig, axes = plt.subplots(2, 1, figsize=(9, 4.6), layout="constrained")
for ax, (field, title) in zip(
    axes,
    [
        ("dependent_events", "Sự kiện đổi nhãn giữa các hồ sơ"),
        ("applies_not_applies_events", "Sự kiện có cả APPLIES và NOT_APPLIES"),
    ],
    strict=True,
):
    for y, (key, color) in enumerate(
        [("web_development", "#287f9b"), ("email_development", "#788494")]
    ):
        entry = summary[key]
        n, total = entry["default_on"][field], entry["events"]
        rate = 100 * n / total
        ax.barh(y, rate, color=color, height=0.48)
        ax.text(rate + 0.35, y, f"{rate:.2f}%  ({n}/{total})", va="center")
    ax.set_yticks([0, 1], [names["web_development"], names["email_development"]])
    ax.set_xlim(0, 31)
    ax.set_xticks([0, 5, 10, 15, 20, 25, 30])
    ax.set_xlabel("Tỷ lệ sự kiện (%)")
    ax.set_title(title, loc="left", fontsize=12)
    ax.invert_yaxis()
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="x", alpha=0.18)
fig.suptitle("v3.1 · train + validation · cùng 722 hồ sơ sinh từ train", fontsize=12)
FIGURES.mkdir(parents=True, exist_ok=True)
fig.savefig(FIGURES / "web_email_applicability.png", dpi=170, facecolor="white")
print("Saved chart from summary.json; these are silver-label diagnostics.")
