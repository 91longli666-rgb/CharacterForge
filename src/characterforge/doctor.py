"""Project environment checks, retained from P0. No model inference here."""

import json
import os
import shutil
import site
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from characterforge.config import ROOT, configure_storage


def main() -> int:
    storage = configure_storage()
    checks: list[dict] = []

    def check(name, action):
        try:
            detail = action()
            checks.append({"name": name, "passed": True, "detail": detail})
        except Exception as exc:
            checks.append({"name": name, "passed": False, "detail": str(exc)})

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)
        return message

    check("python_3_12", lambda: require(sys.version_info[:2] == (3, 12), sys.version))
    check("isolated_environment", lambda: require(
        Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
        and sys.prefix != sys.base_prefix and not site.ENABLE_USER_SITE,
        f"venv={sys.prefix}; base={sys.base_prefix}; user_site={site.ENABLE_USER_SITE}"))
    check("d_drive_storage", lambda: require(
        ROOT.drive.upper() == "D:" and all(
            Path(value).resolve().is_relative_to(ROOT) for value in storage.values()),
        "All configured storage is inside the D-drive project."))
    check("temporary_directory", lambda: require(
        Path(tempfile.gettempdir()).resolve() == (ROOT / "cache" / "tmp").resolve(),
        tempfile.gettempdir()))

    def persistence():
        with tempfile.TemporaryDirectory(prefix="cf-p0-") as directory:
            folder = Path(directory)
            sample = {"english": "Hello, CharacterForge!", "中文": "环境检查"}
            json_path = folder / "roundtrip.json"
            json_path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
            require(json.loads(json_path.read_text(encoding="utf-8")) == sample, "JSON roundtrip")
            db = folder / "roundtrip.sqlite3"
            with closing(sqlite3.connect(db)) as connection:
                connection.execute("CREATE TABLE smoke (value TEXT)")
                connection.execute("INSERT INTO smoke VALUES (?)", (sample["english"],))
                connection.commit()
            with closing(sqlite3.connect(db)) as connection:
                require(connection.execute("SELECT value FROM smoke").fetchone()[0] == sample["english"],
                        "SQLite data survives reconnect")
        return "UTF-8 JSON and SQLite disk roundtrips passed; temporary files removed."

    check("disk_persistence", persistence)

    def command(args):
        result = subprocess.run(args, text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    check("pip_dependencies", lambda: command([sys.executable, "-m", "pip", "check"]))
    check("pip_cache_directory", lambda: require(
        Path(command([sys.executable, "-m", "pip", "cache", "dir"])).resolve()
        == (ROOT / "cache" / "pip").resolve(), "pip cache is on D drive"))
    check("gpu_driver", lambda: command([
        "nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
        "--format=csv,noheader"]))
    check("project_disk_headroom", lambda: require(
        shutil.disk_usage(ROOT).free >= 40 * 1024**3, "At least 40 GiB free on project drive"))
    report = {
        "stage": "environment_check", "time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "python": sys.version, "executable": sys.executable,
        "storage": storage, "checks": checks,
        "passed": all(item["passed"] for item in checks),
        "limitations": ["This environment checker does not run LLM, TTS or ASR inference.",
                        "This environment checker does not test microphones or speakers.",
                        "Read the current stage checkpoint for separate model tests."],
    }
    evidence = ROOT / ".local" / "p0-smoke.json"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in checks:
        print(f"[{'PASS' if item['passed'] else 'FAIL'}] {item['name']}: {item['detail']}")
    print(f"\nEvidence: {evidence}")
    print("Environment checks passed. See docs for the current stage and next checkpoint."
          if report["passed"] else "Environment check failed. See evidence before proceeding.")
    return 0 if report["passed"] else 1
