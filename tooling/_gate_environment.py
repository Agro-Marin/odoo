"""Check the selected gate interpreter against the complete requirements file."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def check(requirements: Path) -> int:
    # Let pip interpret version ranges, extras and platform markers. Reimplementing
    # its requirement language here would give the installer and checker two rules.
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--isolated",
            "install",
            "--dry-run",
            "--no-index",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "--no-input",
            "--quiet",
            "--report",
            "-",
            "-r",
            str(requirements),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PIP_CONFIG_FILE": os.devnull},
    )
    if process.returncode:
        detail = process.stderr.strip() or process.stdout.strip()
    else:
        try:
            report = json.loads(process.stdout)
            pending = report["install"]
            if not isinstance(pending, list):
                raise ValueError("install report is not a list")
        except (ValueError, KeyError, TypeError) as exc:
            detail = f"pip did not produce a valid installation report: {exc}"
        else:
            if not pending:
                return 0
            detail = "pip would install or replace packages; the environment is stale"

    print(f"gate: installed packages do not satisfy {requirements}", file=sys.stderr)
    print(detail, file=sys.stderr)
    repair = [
        "env",
        f"PIP_CONFIG_FILE={os.devnull}",
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "install",
        "-r",
        str(requirements),
    ]
    print(f"gate: repair with {shlex.join(repair)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(check(Path(sys.argv[1])))
