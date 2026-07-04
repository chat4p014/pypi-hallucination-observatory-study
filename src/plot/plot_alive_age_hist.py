from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


BUCKETS = [
    ("<90d",     0,   90,   "#c62828"),
    ("90d-1y",   90,  365,  "#f57c00"),
    ("1-2y",     365, 730,  "#fdd835"),
    ("2-5y",     730, 1825, "#7cb342"),
    (">=5y",     1825, 1e9, "#1e88e5"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    scan = pd.read_csv(args.scan)
    cands = pd.read_csv(args.candidates)[["name", "source"]] \
        .rename(columns={"name": "package_name"})
    df = scan.merge(cands, on="package_name", how="left")

    alive = df[(df["source"] != "control") & (df["status"] == "alive")].copy()
    alive = alive.dropna(subset=["first_seen_utc"])
    alive["fs"] = pd.to_datetime(alive["first_seen_utc"], utc=True,
                                  format="ISO8601", errors="coerce")
    alive = alive.dropna(subset=["fs"])
    now = pd.Timestamp.now(tz="UTC")
    alive["age"] = (now - alive["fs"]).dt.total_seconds() / 86400

    counts = [((alive["age"] >= lo) & (alive["age"] < hi)).sum()
              for _, lo, hi, _ in BUCKETS]
    labels = [b[0] for b in BUCKETS]
    colors = [b[3] for b in BUCKETS]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(labels, counts, color=colors, edgecolor="black", linewidth=0.6)
    for b, c in zip(bars, counts):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.5,
                str(int(c)), ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Số gói")
    ax.set_xlabel("Tuổi (từ first release đến nay)")
    ax.set_title(f"Phân bố tuổi {int(sum(counts))} gói alive")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=200, bbox_inches="tight")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
