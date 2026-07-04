from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def normalize(s: str) -> str:
    return s.strip().lower().replace("_", "-")


def latest_scan(d: Path) -> Path:
    scans = sorted(d.glob("scan_*.csv"))
    if not scans:
        raise SystemExit(f"no scans in {d}")
    return scans[-1]


def load_releases(watchlist_dir: Path) -> dict[str, int]:
    out = {}
    with latest_scan(watchlist_dir).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "alive":
                continue
            try:
                out[normalize(r["package_name"])] = int(r["release_count"])
            except (KeyError, ValueError):
                pass
    return out


def load_downloads(p: Path) -> dict[str, int]:
    out = {}
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[normalize(r["name"])] = int(r.get("last_month") or 0)
            except ValueError:
                out[normalize(r["name"])] = 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist-dir", type=Path, required=True)
    ap.add_argument("--downloads", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    rel = load_releases(args.watchlist_dir)
    dl = load_downloads(args.downloads)
    pairs = [(n, rel[n], dl.get(n, 0)) for n in rel if n in dl]

    zero = [(r,) for _, r, d in pairs if d == 0]
    nz = [(r, d) for _, r, d in pairs if d > 0]

    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    if nz:
        ax.scatter([r for r, _ in nz], [d for _, d in nz],
                    s=45, color="#2c7fb8", edgecolor="black", linewidth=0.5,
                    label=f"Gói có lượt tải > 0 (n={len(nz)})")
    if zero:
        ax.scatter([z[0] for z in zero], [0.5] * len(zero),
                    s=45, color="#c0392b", marker="x", linewidth=1.5,
                    label=f"Gói không lượt tải (n={len(zero)})")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Số phiên bản phát hành (thang logarit)", fontsize=9)
    ax.set_ylabel("Lượt tải tháng gần nhất (thang logarit)", fontsize=9)
    ax.set_title("Tương quan số phiên bản và lượt tải trên tập theo dõi",
                  fontsize=9)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    plt.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=200, bbox_inches="tight")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
