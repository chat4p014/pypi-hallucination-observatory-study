from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path


def normalize(s: str) -> str:
    return s.strip().lower().replace("_", "-")


def latest_scan(watchlist_dir: Path) -> Path:
    scans = sorted(watchlist_dir.glob("scan_*.csv"))
    if not scans:
        raise SystemExit(f"no scan_*.csv in {watchlist_dir}")
    return scans[-1]


def load_releases(watchlist_dir: Path) -> dict[str, int]:
    latest = latest_scan(watchlist_dir)
    out = {}
    with latest.open(encoding="utf-8") as f:
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


def rank(a: list[float]) -> list[float]:
    n = len(a)
    idx = sorted(range(n), key=lambda i: a[i])
    r = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and a[idx[j + 1]] == a[idx[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[idx[k]] = avg
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n))
                    * sum((ry[i] - my) ** 2 for i in range(n)))
    return num / den if den else float("nan")


def spearman_p(rho: float, n: int) -> float:
    if n < 4 or abs(rho) >= 1:
        return float("nan")
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    df = n - 2
    z = abs(t) * math.sqrt(1 - 1.0 / (4 * df))
    return 2 * (0.5 * (1 - math.erf(z / math.sqrt(2))))


def bootstrap_ci(x: list[float], y: list[float], iters: int = 1000,
                  seed: int = 42) -> tuple[float, float]:
    random.seed(seed)
    n = len(x)
    rhos = []
    for _ in range(iters):
        idx = [random.randrange(n) for _ in range(n)]
        r = spearman([x[i] for i in idx], [y[i] for i in idx])
        if not math.isnan(r):
            rhos.append(r)
    if len(rhos) < 10:
        return float("nan"), float("nan")
    rhos.sort()
    return rhos[int(0.025 * len(rhos))], rhos[int(0.975 * len(rhos))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist-dir", type=Path, required=True,
                    help="dir chứa scan_YYYYMMDD_HHMMSS.csv")
    ap.add_argument("--downloads", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    rel = load_releases(args.watchlist_dir)
    dl = load_downloads(args.downloads)
    common = sorted(set(rel) & set(dl))
    print(f"releases:{len(rel)}  downloads:{len(dl)}  common:{len(common)}")

    pairs = [(n, rel[n], dl[n]) for n in common]
    x_all = [r for _, r, _ in pairs]
    y_all = [d for _, _, d in pairs]
    rho_all = spearman(x_all, y_all)
    p_all = spearman_p(rho_all, len(pairs))
    ci_all = bootstrap_ci(x_all, y_all)

    nz = [(n, r, d) for n, r, d in pairs if d > 0]
    if len(nz) >= 3:
        x_nz = [r for _, r, _ in nz]
        y_nz = [d for _, _, d in nz]
        rho_nz = spearman(x_nz, y_nz)
        p_nz = spearman_p(rho_nz, len(nz))
        ci_nz = bootstrap_ci(x_nz, y_nz)
    else:
        rho_nz = p_nz = float("nan")
        ci_nz = (float("nan"), float("nan"))

    result = {
        "n_total": len(pairs),
        "n_nonzero_downloads": len(nz),
        "spearman_all": {"rho": rho_all, "p_value": p_all,
                          "ci_95_low": ci_all[0], "ci_95_high": ci_all[1]},
        "spearman_nonzero_downloads": {"rho": rho_nz, "p_value": p_nz,
                                        "ci_95_low": ci_nz[0], "ci_95_high": ci_nz[1]},
        "top5_by_downloads": [
            {"name": n, "releases": r, "downloads_month": d}
            for n, r, d in sorted(pairs, key=lambda p: -p[2])[:5]
        ],
        "top5_by_releases": [
            {"name": n, "releases": r, "downloads_month": d}
            for n, r, d in sorted(pairs, key=lambda p: -p[1])[:5]
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    print(f"all:      rho={rho_all:.3f}  p={p_all:.4f}  CI=[{ci_all[0]:.3f},{ci_all[1]:.3f}]")
    print(f"nonzero:  rho={rho_nz:.3f}  p={p_nz:.4f}  CI=[{ci_nz[0]:.3f},{ci_nz[1]:.3f}]")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
