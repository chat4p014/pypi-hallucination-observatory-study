from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd


TOP_URL = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json"


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def load_top(cache: Path, refresh: bool = False) -> list[str]:
    if cache.exists() and not refresh:
        age = (datetime.now().timestamp() - cache.stat().st_mtime) / 86400
        if age < 30:
            return [normalize(r["project"])
                    for r in json.loads(cache.read_text())["rows"]]

    cache.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(TOP_URL, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    cache.write_text(raw)
    return [normalize(r["project"]) for r in json.loads(raw)["rows"]]


def filter_overlap(df: pd.DataFrame, top: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["_n"] = df["name"].apply(normalize)
    mask = df["_n"].isin(top)
    return df[~mask].drop(columns=["_n"]), df[mask].drop(columns=["_n"])


def filter_age(df: pd.DataFrame, scan: pd.DataFrame, max_age: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    alive = scan[scan["status"] == "alive"].dropna(subset=["first_seen_utc"]).copy()
    alive["fs"] = pd.to_datetime(alive["first_seen_utc"], utc=True,
                                  format="ISO8601", errors="coerce")
    alive = alive.dropna(subset=["fs"])
    now = pd.Timestamp.now(tz="UTC")
    alive["age"] = (now - alive["fs"]).dt.total_seconds() / 86400
    age_map = dict(zip(alive["package_name"], alive["age"]))

    df = df.copy()
    df["_age"] = df["name"].map(age_map)
    mask = df["_age"] > max_age
    return df[~mask].drop(columns=["_age"]), df[mask].drop(columns=["_age"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--top-n", type=int, default=10000)
    ap.add_argument("--scan", type=Path, default=None,
                    help="PyPI scan CSV (từ 03_monitor_pypi.py) để lọc theo tuổi")
    ap.add_argument("--max-age-days", type=float, default=365)
    ap.add_argument("--cache", type=Path, default=Path("data/top_pypi_cache.json"))
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    df = pd.read_csv(args.input)
    n0 = len(df)

    protected_mask = df["source"].isin(
        ["disclosed_incident", "hallucination_sample", "control"])
    protected = df[protected_mask].copy()
    synthetic = df[~protected_mask].copy()

    top = set(load_top(args.cache, args.refresh)[:args.top_n])
    synthetic, removed1 = filter_overlap(synthetic, top)
    print(f"[top-{args.top_n} overlap] kept={len(synthetic)} removed={len(removed1)}")

    if args.scan and args.scan.exists():
        scan = pd.read_csv(args.scan)
        synthetic, removed2 = filter_age(synthetic, scan, args.max_age_days)
        print(f"[age > {args.max_age_days:.0f}d] kept={len(synthetic)} removed={len(removed2)}")

    final = pd.concat([protected, synthetic], ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(args.output, index=False)
    print(f"input={n0} → output={len(final)}  ({args.output})")


if __name__ == "__main__":
    main()
