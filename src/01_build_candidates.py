from __future__ import annotations

import argparse
import csv
import random
import re
from pathlib import Path


FAMOUS = [
    "requests", "numpy", "pandas", "torch", "tensorflow", "scikit-learn",
    "matplotlib", "seaborn", "flask", "django", "fastapi", "pydantic",
    "sqlalchemy", "celery", "redis", "kafka", "boto3", "openai",
    "transformers", "langchain", "anthropic", "huggingface-hub",
    "lightning", "wandb", "mlflow", "ray", "dask", "polars",
    "pillow", "opencv", "scipy", "statsmodels", "xgboost", "lightgbm",
    "catboost", "spacy", "nltk", "gensim", "pytest", "tox",
    "black", "ruff", "mypy", "isort", "pre-commit", "poetry",
    "setuptools", "wheel", "pip", "virtualenv", "twine",
    "aiohttp", "httpx", "uvicorn", "gunicorn", "starlette",
    "websockets", "asyncio", "pytest-asyncio", "click", "typer",
]

SUFFIX = [
    "helper", "utils", "tools", "pro", "plus", "extra", "extended",
    "lite", "client", "sdk", "api", "core", "common", "cli", "addon",
    "ext", "extras", "kit", "toolkit", "fast", "easy", "simple",
    "wrapper", "binding", "bindings", "py", "python", "official",
    "v2", "next", "modern", "async", "sync", "compat", "fix",
]

PREFIX = [
    "py", "pip", "ai", "ml", "deep", "fast", "easy", "simple",
    "modern", "next", "auto", "smart", "pro", "plus", "open",
    "neo", "x", "z", "ultra", "super", "hyper",
]

NAME_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?")


def valid(name: str) -> bool:
    return bool(name) and len(name) <= 214 and bool(NAME_RE.fullmatch(name))


def pattern_a(rng):
    return f"{rng.choice(FAMOUS)}-{rng.choice(SUFFIX)}"


def pattern_b(rng):
    lib = rng.choice(FAMOUS).replace("-", "")
    return f"{rng.choice(PREFIX)}{lib[0].upper()}{lib[1:]}"


def pattern_c(rng):
    return f"{rng.choice(FAMOUS)}{rng.choice([2, 3, 4, '2024', '2025', '-next', '-v2'])}"


def pattern_d(rng):
    lib = rng.choice(FAMOUS).replace("-", "_")
    return f"{lib}_{rng.choice(['python', 'py', 'core', 'main'])}"


def pattern_e(rng):
    lib = rng.choice(FAMOUS)
    if len(lib) < 3:
        return lib + "s"
    op = rng.choice(["swap", "drop", "insert", "double"])
    i = rng.randrange(1, len(lib) - 1)
    if op == "swap" and lib[i] != lib[i - 1]:
        return lib[:i - 1] + lib[i] + lib[i - 1] + lib[i + 1:]
    if op == "drop":
        return lib[:i] + lib[i + 1:]
    if op == "insert":
        return lib[:i] + rng.choice("aeio") + lib[i:]
    return lib[:i] + lib[i] + lib[i:]


def sample(rng):
    r = rng.random()
    if r < 0.60: return pattern_a(rng), "slopsquatting"
    if r < 0.75: return pattern_b(rng), "slopsquatting"
    if r < 0.85: return pattern_c(rng), "typosquatting"
    if r < 0.95: return pattern_d(rng), "slopsquatting"
    return pattern_e(rng), "typosquatting"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-csv", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260526)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    seed_rows = list(csv.DictReader(args.seed_csv.open(encoding="utf-8")))
    famous = set(FAMOUS)
    seen = {r["name"].lower() for r in seed_rows}

    synthetic = []
    tries = 0
    while len(synthetic) < args.n and tries < args.n * 5:
        tries += 1
        name, cls = sample(rng)
        low = name.lower()
        if low in famous or low in seen or not valid(name):
            continue
        seen.add(low)
        synthetic.append({
            "name": name,
            "source": "synthetic_population",
            "expected_attack_class": cls,
            "disclosure_date": "",
            "notes": "Spracklen pattern",
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(seed_rows[0].keys()))
        w.writeheader()
        w.writerows(seed_rows)
        w.writerows(synthetic)

    print(f"seed={len(seed_rows)} synthetic={len(synthetic)} total={len(seed_rows)+len(synthetic)}")
    print(f"→ {args.output}")


if __name__ == "__main__":
    main()
