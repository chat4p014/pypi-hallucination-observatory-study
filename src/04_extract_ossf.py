from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class Record:
    name: str
    ecosystem: str
    osv_id: str
    published_utc: str
    modified_utc: str
    ttr_hours: float | None
    source_advisory: str
    summary: str


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def extract(osv: dict) -> list[Record]:
    pub = parse_iso(osv.get("published", ""))
    mod = parse_iso(osv.get("modified", ""))
    ttr = None
    if pub and mod:
        h = (mod - pub).total_seconds() / 3600
        if h >= 0:
            ttr = h

    src = ""
    for ref in osv.get("references") or []:
        if ref.get("type") in ("ADVISORY", "WEB"):
            src = ref.get("url", "")
            break

    summary = (osv.get("summary") or "")[:200].replace("\n", " ")
    out = []
    for aff in osv.get("affected") or []:
        pkg = aff.get("package") or {}
        if (pkg.get("ecosystem") or "").lower() != "pypi":
            continue
        name = pkg.get("name")
        if not name:
            continue
        out.append(Record(
            name=normalize(name),
            ecosystem="PyPI",
            osv_id=osv.get("id", ""),
            published_utc=pub.isoformat() if pub else "",
            modified_utc=mod.isoformat() if mod else "",
            ttr_hours=ttr,
            source_advisory=src,
            summary=summary,
        ))
    return out


def dedupe(records: list[Record]) -> list[Record]:
    keep: dict[tuple[str, str], Record] = {}
    for r in records:
        k = (r.name, r.osv_id)
        cur = keep.get(k)
        if cur is None or (r.ttr_hours is not None and cur.ttr_hours is None):
            keep[k] = r
    return list(keep.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True,
                    help="dir chứa OSV JSON")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"input not found: {args.input}")

    files = list(args.input.rglob("*.json"))
    print(f"scanning {len(files)} json files ...")

    records = []
    bad = 0
    for i, fp in enumerate(files, 1):
        try:
            records.extend(extract(json.loads(fp.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            bad += 1
        if i % 1000 == 0:
            print(f"  {i}/{len(files)} ({len(records)} records so far)")

    print(f"raw records: {len(records)}  bad files: {bad}")
    records = dedupe(records)
    print(f"after dedupe: {len(records)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "ecosystem", "osv_id", "published_utc", "modified_utc",
              "ttr_hours", "source_advisory", "summary"]
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            row = asdict(r)
            row["ttr_hours"] = f"{r.ttr_hours:.2f}" if r.ttr_hours is not None else ""
            w.writerow(row)
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
