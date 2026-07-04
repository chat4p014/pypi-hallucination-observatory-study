from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import logging
import math
import re
import shutil
import tarfile
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

UA = "HallucinatedPackageLifecycleStudy/1.0 (academic-research)"

DYNAMIC_EXEC = {"exec", "eval", "compile", "__import__"}
SUBPROCESS_MOD = {"subprocess", "os", "pty", "shlex"}
SUBPROCESS_FN = {"system", "popen", "spawn", "spawnl", "spawnv", "spawnvp",
                 "exec", "execv", "execvp", "execve",
                 "call", "check_call", "check_output", "run", "Popen"}
CREDENTIAL_PATHS = [r"\.ssh", r"\.aws", r"\.npm", r"\.gitconfig", r"\.gnupg",
                    r"\.docker", r"\.kube", r"\.netrc", r"keychain",
                    r"passwd", r"shadow",
                    r"AppData[/\\]Roaming", r"AppData[/\\]Local",
                    r"Library[/\\]Keychains",
                    r"\.bash_history", r"\.zsh_history",
                    r"wallet\.dat", r"keystore"]
SENSITIVE_ENV = ["AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "GITHUB_TOKEN", "GITLAB_TOKEN", "NPM_TOKEN",
                 "PYPI_TOKEN", "TWINE_PASSWORD",
                 "SLACK_TOKEN", "DISCORD_TOKEN",
                 "DATABASE_URL", "MONGO_URI"]
EXFIL_DOMAINS = [r"webhook\.site", r"requestbin",
                 r"discord(?:app)?\.com/api/webhooks",
                 r"pastebin\.com", r"hastebin",
                 r"ngrok", r"localtunnel", r"\.onion",
                 r"transfer\.sh", r"0x0\.st",
                 r"telegra\.ph", r"ipinfo\.io"]
POC_MARKERS = [r"\bproof[- ]of[- ]concept\b", r"\bp\.o\.c\.\b", r"\bpoc\b",
               r"\bfor educational purposes\b",
               r"\bdemo(?:nstration)? package\b",
               r"\btest(?:ing)? upload\b", r"\bdummy package\b",
               r"\bplaceholder\b", r"\bharmless\b",
               r"\bsafe\b.{0,30}\bdummy\b"]


@dataclass
class Finding:
    category: str
    severity: str
    location: str
    snippet: str
    note: str = ""


@dataclass
class Report:
    name: str
    fetched_url: str | None = None
    archive_sha256: str | None = None
    file_count: int = 0
    total_python_loc: int = 0
    has_setup_py: bool = False
    has_pyproject: bool = False
    has_install_hook: bool = False
    poc_self_declared: bool = False
    high_entropy_strings: int = 0
    findings: list[Finding] = field(default_factory=list)
    classification: str = "undetermined"
    classification_reason: str = ""
    error: str | None = None


def download_sdist(name: str, workdir: Path) -> tuple[Path | None, str | None]:
    dest = workdir / "downloads" / name
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": UA}

    try:
        req = urllib.request.Request(
            f"https://pypi.org/pypi/{name}/json", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return None, None
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log.error("PyPI JSON %s: %s", name, e)
        return None, None

    sdist = wheel = None
    for u in data.get("urls", []):
        kind = u.get("packagetype", "")
        fn = u.get("filename", "")
        url = u.get("url", "")
        if kind == "sdist" and not sdist:
            sdist = (url, fn)
        elif (kind == "bdist_wheel" or fn.endswith(".whl")) and not wheel:
            wheel = (url, fn)
    chosen = sdist or wheel
    if not chosen:
        return None, None

    url, fn = chosen
    out = dest / fn
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk)
    except Exception as e:
        log.error("download %s: %s", name, e)
        return None, None
    return out, url


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _safe_tar(tf: tarfile.TarFile, dest: Path):
    root = dest.resolve()
    for m in tf.getmembers():
        if m.issym() or m.islnk() or m.isdev() or m.isfifo():
            continue
        try:
            (dest / m.name).resolve().relative_to(root)
        except ValueError:
            continue
        yield m


def _safe_zip(zf: zipfile.ZipFile, dest: Path):
    root = dest.resolve()
    for i in zf.infolist():
        try:
            (dest / i.filename).resolve().relative_to(root)
        except ValueError:
            continue
        yield i


def extract(archive: Path, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if archive.suffix in (".whl", ".zip"):
            with zipfile.ZipFile(archive) as zf:
                for i in _safe_zip(zf, dest):
                    zf.extract(i, dest)
        elif archive.name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
            with tarfile.open(archive, "r:*") as tf:
                tf.extractall(dest, members=list(_safe_tar(tf, dest)))
        else:
            return False
    except Exception as e:
        log.error("extract %s: %s", archive.name, e)
        return False
    return True


def entropy(s: str) -> float:
    if not s:
        return 0.0
    c = Counter(s)
    n = len(s)
    return -sum((k / n) * math.log2(k / n) for k in c.values())


def suspicious_string(s: str) -> bool:
    return len(s) >= 80 and entropy(s) > 4.5


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _attr_root(node: ast.Attribute) -> str:
    cur = node.value
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else ""


def scan_py(py: Path, root: Path, rep: Report, is_setup: bool) -> int:
    try:
        src = py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(py))
    except SyntaxError as e:
        rep.findings.append(Finding("syntax_error", "low",
                                     f"{py.relative_to(root)}:{e.lineno or 0}", str(e)))
        return src.count("\n") if 'src' in locals() else 0
    except Exception:
        return 0

    rel = str(py.relative_to(root))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _call_name(node)
            if fn in DYNAMIC_EXEC:
                rep.findings.append(Finding(
                    "dynamic_exec", "high" if is_setup else "medium",
                    f"{rel}:{node.lineno}", ast.unparse(node)[:200],
                    "in setup hook" if is_setup else ""))
            if isinstance(node.func, ast.Attribute):
                mod = _attr_root(node.func)
                attr = node.func.attr
                if mod in SUBPROCESS_MOD and attr in SUBPROCESS_FN:
                    rep.findings.append(Finding(
                        "subprocess_call", "high" if is_setup else "medium",
                        f"{rel}:{node.lineno}", ast.unparse(node)[:200],
                        f"{mod}.{attr}" + (" in setup hook" if is_setup else "")))

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if suspicious_string(v):
                rep.high_entropy_strings += 1
                rep.findings.append(Finding(
                    "high_entropy_string", "medium",
                    f"{rel}:{node.lineno}", v[:80] + "...",
                    f"len={len(v)}, H={entropy(v):.2f}"))
            for pat in CREDENTIAL_PATHS:
                if re.search(pat, v, re.IGNORECASE):
                    rep.findings.append(Finding(
                        "credential_path", "high",
                        f"{rel}:{node.lineno}", v[:200], f"matched: {pat}"))
                    break
            for var in SENSITIVE_ENV:
                if var in v:
                    rep.findings.append(Finding(
                        "sensitive_env_var", "high",
                        f"{rel}:{node.lineno}", v[:200], f"matched: {var}"))
                    break
            for pat in EXFIL_DOMAINS:
                if re.search(pat, v, re.IGNORECASE):
                    rep.findings.append(Finding(
                        "suspicious_domain", "high",
                        f"{rel}:{node.lineno}", v[:200], f"matched: {pat}"))
                    break

        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in ("base64", "codecs", "zlib", "marshal", "pickle"):
                    rep.findings.append(Finding(
                        "encoding_import",
                        "low" if a.name in ("base64", "codecs") else "medium",
                        f"{rel}:{node.lineno}", ast.unparse(node),
                        f"imports {a.name}"))
    return src.count("\n")


def detect_install_hook(root: Path, rep: Report) -> bool:
    found = False
    for sf in root.rglob("setup.py"):
        rep.has_setup_py = True
        try:
            tree = ast.parse(sf.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef,
                                  ast.Assign, ast.If)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                if _call_name(node.value) == "setup":
                    continue
            rep.findings.append(Finding(
                "install_hook", "medium",
                f"{sf.relative_to(root)}:{node.lineno}",
                ast.unparse(node)[:200], "module-level in setup.py"))
            found = True
    return found


def check_poc_marker(root: Path) -> bool:
    for pat in ("README.md", "README.rst", "README.txt", "README",
                "PKG-INFO", "setup.cfg", "pyproject.toml"):
        for p in root.rglob(pat):
            try:
                text = p.read_text(encoding="utf-8", errors="replace").lower()
            except Exception:
                continue
            for m in POC_MARKERS:
                if re.search(m, text):
                    return True
    return False


def classify(rep: Report) -> tuple[str, str]:
    by_cat = Counter(f.category for f in rep.findings)
    high = [f for f in rep.findings if f.severity == "high"]
    high_in_setup = [f for f in high
                     if "setup hook" in f.note or "setup.py" in f.location]

    if high_in_setup:
        return "confirmed_malicious", f"high in install hook: {len(high_in_setup)}"
    if by_cat.get("credential_path"):
        return "confirmed_malicious", "credential path access"
    if by_cat.get("sensitive_env_var"):
        return "confirmed_malicious", "sensitive env var read"
    if by_cat.get("suspicious_domain"):
        return "confirmed_malicious", "exfil domain reference"

    if rep.poc_self_declared:
        return "poc_or_educational", "self-declared PoC marker"
    if rep.total_python_loc < 20 and not rep.has_install_hook:
        return "empty_or_placeholder", f"{rep.total_python_loc} LOC, no hook"
    if rep.has_install_hook and not high and rep.total_python_loc < 200:
        return "namespace_squat_no_payload", "small pkg with hook, no indicator"
    if rep.total_python_loc > 500 and not high:
        return "false_positive_legitimate", f"{rep.total_python_loc} LOC, no indicator"
    return "undetermined", f"findings={len(rep.findings)}, LOC={rep.total_python_loc}"


def analyze(name: str, workdir: Path) -> Report:
    rep = Report(name=name)
    arc, url = download_sdist(name, workdir)
    if arc is None:
        rep.error = "download_failed"
        return rep
    rep.fetched_url = url
    rep.archive_sha256 = sha256(arc)

    ext = workdir / "extracted" / name
    if not extract(arc, ext):
        rep.error = "extract_failed"
        return rep

    py_files = list(ext.rglob("*.py"))
    rep.file_count = sum(1 for _ in ext.rglob("*") if _.is_file())
    rep.has_install_hook = detect_install_hook(ext, rep)
    rep.has_pyproject = any(ext.rglob("pyproject.toml"))
    rep.poc_self_declared = check_poc_marker(ext)

    for py in py_files:
        rep.total_python_loc += scan_py(py, ext, rep, py.name == "setup.py")

    rep.classification, rep.classification_reason = classify(rep)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True,
                    help="CSV có cột `name` và `advisory_age_days`")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--details-dir", type=Path, required=True)
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--min-age-days", type=float, default=30)
    ap.add_argument("--cleanup", action="store_true",
                    help="xoá downloads/extracted sau mỗi gói")
    args = ap.parse_args()

    args.details_dir.mkdir(parents=True, exist_ok=True)
    args.workdir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    subset = []
    with args.input.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                age = float(r.get("advisory_age_days", 0))
            except (TypeError, ValueError):
                age = 0.0
            if age >= args.min_age_days:
                subset.append((r["name"], age))

    log.info("subset (age ≥ %.0fd): %d", args.min_age_days, len(subset))

    fields = ["name", "advisory_age_days", "classification",
              "classification_reason", "total_python_loc", "file_count",
              "has_setup_py", "has_install_hook", "poc_self_declared",
              "high_entropy_strings", "findings_count",
              "high_severity_count", "archive_sha256", "error"]
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, (name, age) in enumerate(subset, 1):
            log.info("[%d/%d] %s (age %.1fd)", i, len(subset), name, age)
            rep = analyze(name, args.workdir)

            (args.details_dir / f"{name}.json").write_text(json.dumps({
                **{k: v for k, v in asdict(rep).items() if k != "findings"},
                "findings": [asdict(x) for x in rep.findings],
                "advisory_age_days": age,
                "analysis_time_utc": datetime.now(timezone.utc).isoformat(),
            }, indent=2, ensure_ascii=False), encoding="utf-8")

            high = sum(1 for x in rep.findings if x.severity == "high")
            w.writerow({
                "name": name, "advisory_age_days": f"{age:.1f}",
                "classification": rep.classification,
                "classification_reason": rep.classification_reason,
                "total_python_loc": rep.total_python_loc,
                "file_count": rep.file_count,
                "has_setup_py": rep.has_setup_py,
                "has_install_hook": rep.has_install_hook,
                "poc_self_declared": rep.poc_self_declared,
                "high_entropy_strings": rep.high_entropy_strings,
                "findings_count": len(rep.findings),
                "high_severity_count": high,
                "archive_sha256": rep.archive_sha256 or "",
                "error": rep.error or "",
            })
            f.flush()

            if args.cleanup:
                for sub in ("downloads", "extracted"):
                    tgt = args.workdir / sub / name
                    if tgt.exists():
                        shutil.rmtree(tgt, ignore_errors=True)

            log.info("→ %s (%s)", rep.classification, rep.classification_reason)

    log.info("done → %s", args.output)


if __name__ == "__main__":
    main()
