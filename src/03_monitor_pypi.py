from __future__ import annotations

import argparse
import csv
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests


PYPI_JSON = "https://pypi.org/pypi/{name}/json"
UA = "HallucinatedPackageLifecycleStudy/1.0 (academic-research)"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


@dataclass
class Observation:
    package_name: str
    observation_time_utc: str
    status: str
    first_seen_utc: str | None
    last_release_utc: str | None
    release_count: int
    latest_version: str | None
    summary: str | None
    home_page: str | None
    author: str | None
    requires_python: str | None
    yanked_any: bool
    classifiers_count: int
    has_description: bool
    http_status: int


class Client:
    def __init__(self, qps: float = 2.0, timeout: float = 10.0):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json",
            "Cache-Control": "max-age=0",
        })
        self.interval = 1.0 / qps
        self.timeout = timeout
        self._last = 0.0

    def _pace(self):
        elapsed = time.monotonic() - self._last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last = time.monotonic()

    def fetch(self, name: str) -> Observation:
        self._pace()
        now = datetime.now(timezone.utc).isoformat()
        empty = dict(first_seen_utc=None, last_release_utc=None, release_count=0,
                     latest_version=None, summary=None, home_page=None,
                     author=None, requires_python=None, yanked_any=False,
                     classifiers_count=0, has_description=False)

        try:
            r = self.s.get(PYPI_JSON.format(name=name), timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("network error %s: %s", name, e)
            return Observation(name, now, "network_error", **empty, http_status=-1)

        if r.status_code == 404:
            return Observation(name, now, "not_found", **empty, http_status=404)
        if r.status_code == 410:
            return Observation(name, now, "removed", **empty, http_status=410)
        if not r.ok:
            return Observation(name, now, f"http_{r.status_code}", **empty,
                                http_status=r.status_code)

        data = r.json()
        info = data.get("info") or {}
        releases = data.get("releases") or {}
        uploads, yanked = [], False
        for files in releases.values():
            for f in files or []:
                t = f.get("upload_time_iso_8601") or f.get("upload_time")
                if t:
                    uploads.append(t)
                if f.get("yanked"):
                    yanked = True

        return Observation(
            package_name=name,
            observation_time_utc=now,
            status="alive",
            first_seen_utc=min(uploads) if uploads else None,
            last_release_utc=max(uploads) if uploads else None,
            release_count=len(releases),
            latest_version=info.get("version"),
            summary=(info.get("summary") or "")[:200],
            home_page=info.get("home_page"),
            author=info.get("author"),
            requires_python=info.get("requires_python"),
            yanked_any=yanked,
            classifiers_count=len(info.get("classifiers") or []),
            has_description=bool(info.get("description")),
            http_status=200,
        )


def scan(names: Iterable[str], out: Path, qps: float) -> None:
    client = Client(qps=qps)
    fields = list(Observation.__annotations__.keys())
    out.parent.mkdir(parents=True, exist_ok=True)
    is_new = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        if is_new:
            w.writeheader()
        for i, n in enumerate(names, 1):
            obs = client.fetch(n.strip())
            w.writerow(asdict(obs))
            if i % 25 == 0:
                log.info("%d done, last=%s (%s)", i, n, obs.status)
    log.info("done → %s", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="text file, 1 name per line")
    ap.add_argument("output", type=Path)
    ap.add_argument("--qps", type=float, default=2.0)
    args = ap.parse_args()

    names = [l.strip() for l in args.input.read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    log.info("loaded %d names", len(names))
    scan(names, args.output, args.qps)


if __name__ == "__main__":
    main()
