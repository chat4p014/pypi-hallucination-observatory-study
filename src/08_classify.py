from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


ORDER = {
    "confirmed_malicious_high_confidence": 0,
    "needs_manual_verification": 1,
    "namespace_squat_no_payload": 2,
    "poc_or_educational": 3,
    "empty_or_placeholder": 4,
    "undetermined": 5,
    "likely_legitimate_framework": 6,
    "false_positive_legitimate": 7,
}


def normalize(s: str) -> str:
    return s.strip().lower().replace("_", "-")


def load_downloads(p: Path) -> dict[str, int]:
    out = {}
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[normalize(r["name"])] = int(r.get("last_month") or 0)
            except ValueError:
                out[normalize(r["name"])] = 0
    return out


def refine(auto: str, loc: int, downloads: int, has_hook: bool,
            reason: str) -> tuple[str, str]:
    if downloads >= 100_000:
        return "likely_legitimate_framework", \
               f"{downloads} downloads/month"
    if loc >= 50_000 and downloads >= 1_000:
        return "likely_legitimate_framework", \
               f"{loc} LOC + {downloads} downloads/month"
    if "install hook" in reason and has_hook:
        return "confirmed_malicious_high_confidence", \
               f"high-severity in install hook: {reason}"
    if auto == "confirmed_malicious" and downloads < 500 and loc < 10_000:
        return "confirmed_malicious_high_confidence", \
               f"low downloads ({downloads}) + small LOC ({loc}) + {reason}"
    if auto == "confirmed_malicious":
        return "needs_manual_verification", \
               f"auto flagged but {downloads} dl/mo + {loc} LOC ambiguous"
    return auto, reason


def apply_overrides(rows: list[dict], overrides: dict) -> None:
    for r in rows:
        k = normalize(r["name"])
        if k in overrides:
            new_cls, ev = overrides[k]
            r["final_classification"] = new_cls
            r["rationale"] = f"MANUAL: {ev}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-classification", type=Path, required=True,
                    help="Kết quả từ src/07_static_analysis.py")
    ap.add_argument("--downloads", type=Path, required=True)
    ap.add_argument("--manual", type=Path, default=None,
                    help="CSV: name, manual_classification, evidence")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    downloads = load_downloads(args.downloads)

    rows = []
    with args.auto_classification.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = r["name"].strip()
            dl = downloads.get(normalize(name), 0)
            loc = int(r.get("total_python_loc") or 0)
            has_hook = r.get("has_install_hook") == "True"
            reason = r.get("classification_reason", "")
            auto = r.get("classification", "undetermined")
            final, rationale = refine(auto, loc, dl, has_hook, reason)
            rows.append({
                "name": name,
                "advisory_age_days": r.get("advisory_age_days", ""),
                "downloads_last_month": dl,
                "total_python_loc": loc,
                "high_severity_count": int(r.get("high_severity_count") or 0),
                "auto_classification": auto,
                "final_classification": final,
                "rationale": rationale,
            })

    if args.manual and args.manual.exists():
        overrides = {}
        with args.manual.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                overrides[normalize(r["name"])] = (
                    r["manual_classification"], r.get("evidence", ""))
        apply_overrides(rows, overrides)

    rows.sort(key=lambda x: (ORDER.get(x["final_classification"], 99),
                              -x["downloads_last_month"]))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "advisory_age_days", "downloads_last_month",
              "total_python_loc", "high_severity_count",
              "auto_classification", "final_classification", "rationale"]
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    c = Counter(r["final_classification"] for r in rows)
    print(f"n = {len(rows)}")
    for cls, n in sorted(c.items(), key=lambda x: ORDER.get(x[0], 99)):
        print(f"  {cls}: {n}")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
