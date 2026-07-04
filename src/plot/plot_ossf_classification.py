from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


LABELS = {
    "confirmed_malicious_high_confidence":
        "Mã độc\nxác nhận\n(độ tin cậy cao)",
    "false_positive_legitimate":
        "Khung công cụ\nhợp pháp\n(FP trong OSSF)",
    "likely_legitimate_framework":
        "Khung công cụ\nhợp pháp\n(FP trong OSSF)",
    "namespace_squat_no_payload":
        "Dương tính giả\ntự nhận diện",
    "undetermined":
        "Chưa kết luận",
    "empty_or_placeholder":
        "Rỗng /\nGiữ chỗ",
    "poc_or_educational":
        "PoC /\nGiáo dục",
    "needs_manual_verification":
        "Cần verify\nthủ công",
}
ORDER = [
    "confirmed_malicious_high_confidence",
    "false_positive_legitimate",
    "namespace_squat_no_payload",
    "undetermined",
    "empty_or_placeholder",
    "poc_or_educational",
    "needs_manual_verification",
]
COLORS = {
    "confirmed_malicious_high_confidence":  "#c0392b",
    "false_positive_legitimate":            "#27ae60",
    "likely_legitimate_framework":          "#27ae60",
    "namespace_squat_no_payload":           "#2980b9",
    "undetermined":                         "#7f8c8d",
    "empty_or_placeholder":                 "#95a5a6",
    "poc_or_educational":                   "#f39c12",
    "needs_manual_verification":            "#8e44ad",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classification", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    with args.classification.open(encoding="utf-8") as f:
        counts = Counter(r["final_classification"] for r in csv.DictReader(f))
    if "likely_legitimate_framework" in counts:
        counts["false_positive_legitimate"] += counts.pop("likely_legitimate_framework")

    keys = [k for k in ORDER if counts.get(k, 0) > 0]
    values = [counts[k] for k in keys]
    labels = [LABELS[k] for k in keys]
    colors = [COLORS[k] for k in keys]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.bar(range(len(keys)), values, color=colors,
                   edgecolor="black", linewidth=0.6)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3,
                f"{v}\n({v / total * 100:.1f}%)",
                ha="center", va="bottom", fontsize=9)

    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Số gói")
    ax.set_ylim(0, max(values) + 4)
    ax.set_title(f"Phân loại {total} gói OSSF alive sau phân tích tĩnh + thẩm định")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)
    plt.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=200, bbox_inches="tight")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
