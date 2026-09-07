#!/usr/bin/env python3
"""Ratchet assertions that a test can never be sure ran.

`js_vacuous_assertions.py` catches an assertion that cannot FAIL --
`expect(".o_x").toHaveCount(0)` where nothing declares `.o_x`. This one catches
an assertion that may never EXECUTE, which is the same defect one level down and
was gated by nothing.

The shape, from `t_custom_click.test.js` before `9e26c220cdf`:

    plop(ev) {
        expect(ev.currentTarget).toBe(document);      // runs only if the
    }                                                 // handler is invoked
    ...
    expect(".clickMe").toHaveText("text from props"); // runs always
    await contains(".clickMe").click();

One assertion executes, the test is green, and the assertion naming the
behaviour never ran. That test was the only coverage in `addons/web` for the
`.synthetic` modifier and it stayed green through the entire life of the defect
fixed in `800c9912f02`, where every synthetic handler after the first in a file
was silently dead.

MASKING IS THE DEFECT, NOT DEFERRAL. Hoot already fails a test that runs no
assertion at all, so a test whose ONLY assertions sit in a dead handler is caught
today. What is not caught is a dead handler masked by an assertion in the test's
own straight-line flow. This gate reports only the masked case; without that
condition it reports 112 sites in `addons/web`, most of them already covered.

Three things count as proof the deferred function ran, and none is reported:
`expect.assertions(n)` or the `verifySteps` protocol; a sentinel the function
assigns that is asserted outside it (`let clicked = false` ... `clicked = true`
... `expect(clicked).toBe(true)`, which is idiomatic here and correct); and the
result of the call the function was handed to, when that result is asserted.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_unreached_assertions")
WEB_TESTS = ROOT / "addons" / "web" / "static" / "tests"

GOVERNED_ADDONS = ("web", "mail", "account", "stock")
DEFAULT_ADDON = "web"

ANALYZER = Path(__file__).with_suffix(".mjs")


def addon_tests(addon: str = DEFAULT_ADDON) -> Path:
    return (
        WEB_TESTS
        if addon == DEFAULT_ADDON
        else ROOT / "addons" / addon / "static" / "tests"
    )


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    test: str
    method: str | None

    def __str__(self) -> str:
        where = f"{self.method}()" if self.method else "callback"
        return f"  {self.file}:{self.line}  {where}  <- {self.test}"


def iter_test_files(tests: Path) -> list[Path]:
    if not tests.is_dir():
        return []
    return sorted(tests.rglob("*.test.js"))


def analyse(files: list[Path], tests: Path) -> list[Finding]:
    if not files:
        return []
    proc = subprocess.run(
        ["node", str(ANALYZER), *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"unreached-assertion analyzer failed: {proc.stderr.strip()}"
        )
    found = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rel = Path(raw["file"])
        with contextlib.suppress(ValueError):
            rel = rel.resolve().relative_to(tests.resolve())
        found.append(
            Finding(rel.as_posix(), raw["line"], raw["test"], raw.get("method"))
        )
    return sorted(found, key=lambda f: (f.file, f.line))


def measure(tests: Path = WEB_TESTS) -> list[Finding]:
    files = iter_test_files(tests)
    if not files:
        raise RuntimeError(
            f"no test files under {tests} -- the scan found nothing, which is "
            f"not the same as finding nothing wrong"
        )
    return analyse(files, tests)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=20, help="0 for all")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        choices=GOVERNED_ADDONS,
        help="which addon's static/tests to measure (default: web)",
    )
    args = parser.parse_args(argv)

    try:
        found = measure(tests=addon_tests(args.addon))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print(f"Assertions that may never execute ({args.addon}/static/tests)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"{len(found)} masked assertion site(s)")
    print("\nRatchet this number:")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = "jsunreached" if args.addon == DEFAULT_ADDON else f"jsunreached_{args.addon}"
    print(
        f"  python tooling/architecture/js_unreached_assertions.py{suffix} --count \\"
    )
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
