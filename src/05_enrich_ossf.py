from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


PYPI_JSON = "https://pypi.org/pypi/{name}/json"
UA = "HallucinatedPackageLifecycleStudy/1.0 (academic-research)"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def fetch(session: requests.Session, name: str) -> dict:
    out = dict(current_pypi_status="error", first_seen_utc="",
               last_release_utc="", current_release_count=0,
               is_yanked=False, pypi_summary="", http_status=-1)
    try:
        r = session.get(PYPI_JSON.format(name=name), timeout=10)
    except requests.RequestException:
        out["current_pypi_status"] = "network_error"
        return out

    out["http_status"] = r.status_code
    if r.status_code == 404:
        out["current_pypi_status"] = "not_found_404"
        return out
    if r.status_code == 410:
        out["current_pypi_status"] = "gone_410"
        return out
    if not r.ok:
        out["current_pypi_status"] = f"http_{r.status_code}"
        return out

    try:
        data = r.json()
    except ValueError:
        out["current_pypi_status"] = "json_parse_error"
        return out

    info = data.get("info") or {}
    releases = data.get("releases") or {}
    uploads, yanked = [], False
    for files in releases.values():
        for fi in files or []:
            t = fi.get("upload_time_iso_8601") or fi.get("upload_time")
            if t:
                uploads.append(t)
            if fi.get("yanked"):
                yanked = True

    out["current_pypi_status"] = "alive"
    if uploads:
        out["first_seen_utc"] = min(uploads)
        out["last_release_utc"] = max(uploads)
    out["current_release_count"] = len(releases)
    out["is_yanked"] = yanked
    out["pypi_summary"] = (info.get("summary") or "")[:200]
    return out


def derive(status: str, first_seen: str, published: str, modified: str):
    pub = parse_iso(published)
    mod = parse_iso(modified)
    fs = parse_iso(first_seen)
    if status == "alive":
        if fs:
            return "", (datetime.now(timezone.utc) - fs).total_seconds() / 86400
        return "", None
    removed = pub or mod
    return (removed.isoformat() if removed else ""), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--qps", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"input not found: {args.input}")

    df = pd.read_csv(args.input)
    if args.limit:
        df = df.head(args.limit).copy()

    done = set()
    if args.resume and args.output.exists():
        done = set(pd.read_csv(args.output)["name"].astype(str))
        log.info("resume: %d records already done", len(done))

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json",
                            "Cache-Control": "max-age=0"})
    interval = 1.0 / args.qps
    last = 0.0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    is_new = not args.output.exists() or not args.resume
    cols = list(df.columns) + [
        "current_pypi_status", "first_seen_utc", "last_release_utc",
        "current_release_count", "is_yanked", "pypi_summary", "http_status",
        "removed_proxy_utc", "lifetime_days",
    ]
    with args.output.open("w" if is_new else "a", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        if is_new:
            w.writeheader()

        for idx, row in df.iterrows():
            name = str(row["name"]).strip()
            if name in done:
                continue

            wait = interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()

            meta = fetch(session, name)
            removed, lifetime = derive(meta["current_pypi_status"],
                                        meta["first_seen_utc"],
                                        row.get("published_utc", ""),
                                        row.get("modified_utc", ""))
            w.writerow({
                **row.to_dict(), **meta,
                "removed_proxy_utc": removed,
                "lifetime_days": lifetime if lifetime is not None else "",
            })
            fp.flush()
            if (idx + 1) % 100 == 0:
                log.info("%d/%d  last=%s (%s)", idx + 1, len(df), name,
                          meta["current_pypi_status"])

    log.info("done → %s", args.output)


if __name__ == "__main__":
    main()
