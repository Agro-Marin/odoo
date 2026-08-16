#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ODOO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="check_vendored_libs")
LIB_DIR = ODOO_ROOT / "addons" / "web" / "static" / "lib"
MANIFEST = LIB_DIR / "versions.json"
OSV_ENDPOINT = "https://api.osv.dev/v1/query"
OSV_TIMEOUT_S = 30


def _load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())["libs"]
    except FileNotFoundError:
        sys.exit(f"FATAL: no manifest at {MANIFEST}")
    except (json.JSONDecodeError, KeyError) as exc:
        sys.exit(f"FATAL: malformed manifest {MANIFEST}: {exc}")


OK, FAIL, UNVERIFIED = "ok", "fail", "unverified"


def _check_rebuild(name: str, script: Path) -> tuple[str, str]:

    if not script.is_file():
        return FAIL, f"rebuild script {script} is missing"
    try:
        done = subprocess.run(
            [str(script), "--check"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return UNVERIFIED, f"could not run {script.name} ({exc})"
    if done.returncode == 0:
        return OK, "generated artefact is up to date"
    if done.returncode == 127:
        return UNVERIFIED, "build toolchain unavailable"
    return FAIL, (done.stderr or done.stdout).strip() or "stale artefact"


def check_drift(libs: dict) -> tuple[int, list[str]]:

    failures = 0
    unverified: list[str] = []
    for name, spec in sorted(libs.items()):
        version = spec["version"]
        directory = LIB_DIR / name
        if not directory.is_dir():
            print(f"  FAIL {name}: no such directory {directory}")
            failures += 1
            continue

        rebuild = spec.get("rebuild")
        if rebuild:
            verdict, detail = _check_rebuild(name, directory / rebuild)
            marker = {OK: "  OK  ", FAIL: "  FAIL", UNVERIFIED: "  ??? "}[verdict]
            print(f"{marker} {name}: {detail}")
            if verdict == FAIL:
                failures += 1
            elif verdict == UNVERIFIED:
                unverified.append(name)
            continue

        probe = spec.get("probe")
        if not probe:
            print(f"  --   {name}: {version} (no probe — nothing to re-derive)")
            unverified.append(name)
            continue

        target = directory / probe["file"]
        try:
            content = target.read_text(errors="replace")
        except OSError as exc:
            print(f"  FAIL {name}: cannot read probe file {target}: {exc}")
            failures += 1
            continue

        pattern = probe["pattern"].replace("{version}", re.escape(version))  # noqa: RUF027
        if re.search(pattern, content, re.MULTILINE):
            print(f"  OK   {name}: {version}")
        else:
            print(
                f"  FAIL {name}: manifest says {version} but {probe['file']} "
                f"does not match /{pattern}/"
            )
            failures += 1
    return failures, unverified


def _osv_query(package: str, version: str) -> list[dict] | None:

    payload = json.dumps(
        {
            "package": {"name": package, "ecosystem": "npm"},
            "version": version,
        }
    ).encode()
    request = urllib.request.Request(
        OSV_ENDPOINT, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=OSV_TIMEOUT_S) as response:  # noqa: S310
            return json.loads(response.read()).get("vulns", [])
    except urllib.error.URLError, TimeoutError, json.JSONDecodeError:
        return None


def audit(libs: dict) -> int:

    vulnerable = 0
    unreachable = []
    not_on_npm = []
    for name, spec in sorted(libs.items()):
        package = spec.get("npm")
        if not package or spec.get("upstream") is False:
            not_on_npm.append(name)
            continue
        version = spec["version"]
        vulns = _osv_query(package, version)
        if vulns is None:
            unreachable.append(name)
            print(f"  ???  {name}: OSV unreachable")
            continue
        if not vulns:
            print(f"  OK   {name} {version}: no known advisories")
            continue
        vulnerable += 1
        print(f"  VULN {name} {version}: {len(vulns)} advisory(ies)")
        for vuln in vulns:
            summary = (vuln.get("summary") or "").strip() or "(no summary)"
            print(f"         {vuln['id']}: {summary}")

    if not_on_npm:
        print(f"\nNOTE: no npm coordinates for: {', '.join(not_on_npm)}")
        print("OSV cannot be queried for these; they are outside the audit.")
    if unreachable:
        print(f"\nWARNING: OSV not reached for: {', '.join(unreachable)}")
        print("These were NOT audited -- do not read this run as a clean result.")
    return vulnerable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drift", action="store_true", help="check manifest against shipped bytes"
    )
    parser.add_argument(
        "--audit", action="store_true", help="query OSV for known advisories"
    )
    args = parser.parse_args()
    if not args.drift and not args.audit:
        args.drift = True

    libs = _load_manifest()
    status = 0

    if args.drift:
        print(f"Version drift ({len(libs)} libraries):")
        failures, unverified = check_drift(libs)
        if failures:
            print(f"\n{failures} mismatch(es).")
        else:
            verified = len(libs) - len(unverified)
            print(f"\nAll {verified} verifiable pinned version(s) match.")
        if unverified:
            print(
                f"{len(unverified)} NOT verified: {', '.join(unverified)}\n"
                f"  Do not read this run as a clean result for those."
            )
        print()
        status |= 1 if failures else 0

    if args.audit:
        print("OSV audit:")
        vulnerable = audit(libs)
        print(
            f"\n{vulnerable} library(ies) with known advisories.\n"
            if vulnerable
            else "\nNo known advisories against the pinned versions.\n"
        )
        status |= 2 if vulnerable else 0

    return status


if __name__ == "__main__":
    sys.exit(main())
