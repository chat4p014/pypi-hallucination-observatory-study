from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


URL = "https://pypistats.org/api/packages/{name}/recent"
UA = "HallucinatedPackageLifecycleStudy/1.0 (academic-research)"
SLEEP = 1.5

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def normalize(n: str) -> str:
    return n.strip().lower().replace("_", "-")


def fetch(session: requests.Session, name: str) -> dict:
    try:
        r = session.get(URL.format(name=normalize(name)), timeout=15)
    except requests.RequestException as e:
        return dict(status="error", error_message=str(e),
                    last_day=None, last_week=None, last_month=None)
    if r.status_code == 404:
        return dict(status="not_found", error_message=None,
                    last_day=None, last_week=None, last_month=None)
    if r.status_code != 200:
        return dict(status="error", error_message=f"HTTP {r.status_code}",
                    last_day=None, last_week=None, last_month=None)
    try:
        d = r.json().get("data", {})
        return dict(status="ok", error_message=None,
                    last_day=d.get("last_day"),
                    last_week=d.get("last_week"),
                    last_month=d.get("last_month"))
    except ValueError as e:
        return dict(status="error", error_message=f"parse: {e}",
                    last_day=None, last_week=None, last_month=None)


def read_txt(p: Path) -> list[str]:
    return [l.strip() for l in p.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def read_csv_column(p: Path, col: str, alive_only: bool = False) -> list[str]:
    out = []
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if alive_only and r.get("status") != "alive":
                continue
            v = r.get(col) or r.get("package_name") or r.get("name")
            if v:
                out.append(v.strip())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--from-txt", action="append", default=[],
                    metavar="LABEL:PATH", help="tag:path.txt (có thể lặp)")
    ap.add_argument("--from-csv-alive", action="append", default=[],
                    metavar="LABEL:PATH", help="chỉ lấy dòng status=alive")
    ap.add_argument("--from-csv", action="append", default=[],
                    metavar="LABEL:PATH")
    args = ap.parse_args()

    pairs = []
    for spec in args.from_txt:
        label, path = spec.split(":", 1)
        pairs.extend((n, label) for n in read_txt(Path(path)))
    for spec in args.from_csv_alive:
        label, path = spec.split(":", 1)
        pairs.extend((n, label) for n in read_csv_column(Path(path), "name", alive_only=True))
    for spec in args.from_csv:
        label, path = spec.split(":", 1)
        pairs.extend((n, label) for n in read_csv_column(Path(path), "name"))

    seen = {}
    for name, source in pairs:
        k = normalize(name)
        if k not in seen:
            seen[k] = (name, source)
    unique = list(seen.values())
    log.info("total unique: %d", len(unique))

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "source", "fetch_time_utc", "status",
              "last_day", "last_week", "last_month", "error_message"]
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, (name, source) in enumerate(unique, 1):
            log.info("[%d/%d] %s", i, len(unique), name)
            r = fetch(session, name)
            w.writerow({
                "name": name, "source": source,
                "fetch_time_utc": datetime.now(timezone.utc).isoformat(),
                **r,
            })
            f.flush()
            time.sleep(SLEEP)
    log.info("done → %s", args.output)


if __name__ == "__main__":
    main()
