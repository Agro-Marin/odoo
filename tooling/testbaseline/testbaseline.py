#!/usr/bin/env python3
"""Expected-failure baselines for odoo-bin integration suites.

Answers, without a control run, the question that costs this workspace the most
test time: *is this red mine, or was it already red?*

The alternative in use until now was prose — the "Known defects" table in the
workspace `CLAUDE.md`. Three of its properties were measured on 2026-08-22 and
each one is a design constraint here, not a preference:

1. It rots within the hour. Its `/base` row claimed 11 red of 3284; a run of its
   own repro at `ca4ee2ddd79` reported 3 of 3284, because `d669e70361c` had
   fixed five of them one hour after the row was written. That table lives at
   the workspace root, which is not a git repository, so no commit can retire an
   entry atomically — the rot is mechanical, not a discipline failure.
2. Counting failures by grepping for ERROR invents them. PostgreSQL error text
   is embedded verbatim in log records of *passing* tests, so a bad-COPY test
   that passes contributes a line reading `ERROR: descriptor 'toordinal' ...`.
   On one `/base` log, `ERROR` matched 14 lines and the truth was 3. Hence
   `RECORD` below anchors on the full structured prefix, and `evaluate` refuses
   to return a verdict when its own tally disagrees with the server's.
3. Comparing counts hides swaps. `quality_control` was "2 failed of 38" when the
   prose was written and is "2 failed of 41" today — but one name left the set
   and a different one joined it. A count comparison reads "both known" and
   ships the regression, which is worse than having no record at all.

Scope: this reads a log an operator already produced. It does not run tests, own
a workflow, or gate CI — a red suite is still red. What it removes is the second
run whose only purpose was to find out whether the first one's red was new.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINES_DIR = HERE / "baselines"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2

# `OdooTestResult.logError` emits "<flavour>: <getDescription(test)>" at ERROR
# level through the *test module's* own logger, behind odoo's standard log
# prefix. Matching the whole prefix is the point: a bare /ERROR/ also matches
# PostgreSQL's error text, which arrives as an unprefixed continuation line
# inside a record belonging to a test that passed.
RECORD = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ (?P<level>[A-Z]+) uid:\S* \S+ "
    r"(?P<logger>[\w.]+): (?P<flavour>FAIL|ERROR): (?P<desc>.+?)\s*$"
)
STARTING = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ INFO uid:\S* \S+ "
    r"(?P<logger>[\w.]+): Starting (?P<desc>\S+) \.\.\.\s*$"
)
SUMMARY = re.compile(
    r"(?P<failed>\d+) failed, (?P<errors>\d+) error\(s\) of (?P<total>\d+) tests"
)
# odoo.addons.<module>.tests.<file> — the addon that owns the test.
ADDON = re.compile(r"^odoo\.addons\.(?P<module>[^.]+)\.tests\.")
# A subtest's description is "Subtest <Class>.<method> (k=<repr>, ...)"
# (`_SubTest._subDescription`), so any param whose repr carries its address
# would give the same subtest a new id on every run. Fold those to one token.
ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,}")


def qualify(logger: str, description: str) -> str:
    """Return "<addon>/<Class>.<method>".

    `getDescription` yields `Class.method` with no module, and names collide
    across addons — `TestCommon.test_default` exists many times over. The test
    module's logger is the only thing in the record that disambiguates them.

    Memory addresses inside a subtest's parameter reprs are folded to `0xADDR`,
    so a subtest does not acquire a new identity on every run.
    """
    match = ADDON.match(logger)
    owner = match["module"] if match else logger
    return f"{owner}/{ADDRESS.sub('0xADDR', description)}"


@dataclass(frozen=True)
class Scan:
    """What one odoo-bin log says happened."""

    failures: dict[str, str] = field(default_factory=dict)
    started: frozenset[str] = frozenset()
    reported_failed: int | None = None
    reported_total: int | None = None

    @property
    def total(self) -> int:
        """Tests run — the server's own tally, which outranks counting starts.

        A retried test logs `Starting` twice and a set collapses the pair, and
        `Starting post tests` is a phase banner rather than a test.
        """
        return (
            self.started_count if self.reported_total is None else self.reported_total
        )

    @property
    def started_count(self) -> int:
        return len(self.started)

    @property
    def complete(self) -> bool:
        """Whether the run reached the end.

        `_threaded.py` logs `N failed, M error(s) of T tests` unconditionally
        once `--test-enable` stops the server — at ERROR, WARNING or INFO
        depending on the outcome, but always. Its absence means the run was
        killed or the log was cut, which is the shape a server dying mid-run
        takes: every expected failure then reads as newly-passing.
        """
        return self.reported_failed is not None

    @property
    def sound(self) -> bool:
        """Whether this parse agrees with the server's own failure count."""
        return self.complete and self.reported_failed == len(self.failures)


def scan_log(path: Path) -> Scan:
    failures: dict[str, str] = {}
    started: set[str] = set()
    reported_failed = reported_total = None
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if (record := RECORD.match(line)) and record["level"] == "ERROR":
                key = qualify(record["logger"], record["desc"])
                failures[key] = record["flavour"]
            elif start := STARTING.match(line):
                started.add(qualify(start["logger"], start["desc"]))
            elif summary := SUMMARY.search(line):
                reported_failed = (
                    (reported_failed or 0)
                    + int(summary["failed"])
                    + int(summary["errors"])
                )
                reported_total = (reported_total or 0) + int(summary["total"])
    return Scan(failures, frozenset(started), reported_failed, reported_total)


@dataclass(frozen=True)
class Baseline:
    suite: str
    expected: dict[str, str]
    run_spec: str = ""
    verified_at: str = ""
    tests_total: int = 0
    note: str = ""

    @classmethod
    def load(cls, suite: str) -> Baseline | None:
        path = baseline_path(suite)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            suite=str(data.get("suite", suite)),
            expected=dict(data.get("expected", {})),
            run_spec=str(data.get("run_spec", "")),
            verified_at=str(data.get("verified_at", "")),
            tests_total=int(data.get("tests_total", 0)),
            note=str(data.get("note", "")),
        )

    def save(self) -> Path:
        path = baseline_path(self.suite)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "expected": dict(sorted(self.expected.items())),
            "note": self.note,
            "run_spec": self.run_spec,
            "suite": self.suite,
            "tests_total": self.tests_total,
            "verified_at": self.verified_at,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path


def baseline_path(suite: str) -> Path:
    """Map a test tag to its baseline file. `/base` becomes `base.json`."""
    slug = suite.strip("/")
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise ValueError(f"invalid suite name: {suite!r}")
    return BASELINES_DIR / f"{slug}.json"


@dataclass(frozen=True)
class Verdict:
    suite: str
    new: tuple[str, ...]
    fixed: tuple[str, ...]
    held: tuple[str, ...]
    total: int
    size_drift: int
    exit_code: int
    lines: tuple[str, ...]


def evaluate(suite: str, scan: Scan, baseline: Baseline | None) -> Verdict:
    if not scan.complete:
        message = (
            f"{suite}: the log carries no `N failed, M error(s) of T tests` "
            f"summary, so the run never finished. No verdict — re-run it."
        )
        return Verdict(suite, (), (), (), scan.total, 0, EXIT_USAGE, (message,))
    if not scan.sound:
        message = (
            f"{suite}: parse saw {len(scan.failures)} failures, the server "
            f"reported {scan.reported_failed}. The log is truncated or its "
            f"format moved; no verdict."
        )
        return Verdict(suite, (), (), (), scan.total, 0, EXIT_USAGE, (message,))
    if baseline is None:
        head = f"{suite}: NO BASELINE — {len(scan.failures)} failed of {scan.total}"
        body = [f"  ?     {name}" for name in sorted(scan.failures)]
        seed = "  seed it with --update once you have confirmed these are not yours"
        return Verdict(
            suite, (), (), (), scan.total, 0, EXIT_USAGE, (head, *body, seed)
        )

    actual, expected = set(scan.failures), set(baseline.expected)
    new = tuple(sorted(actual - expected))
    fixed = tuple(sorted(expected - actual))
    held = tuple(sorted(actual & expected))
    drift = scan.total - baseline.tests_total if baseline.tests_total else 0

    headline = (
        f"{suite}: {scan.total} tests, {len(actual)} failed — "
        f"{len(held)} expected, {len(new)} new, {len(fixed)} newly-passing"
    )
    lines = [headline]
    lines += [f"  NEW   {scan.failures[name]:5} {name}" for name in new]
    lines += [f"  FIXED       {name}  (bank it: --update)" for name in fixed]
    if drift:
        lines.append(
            f"  NOTE  suite size moved {drift:+d} "
            f"({baseline.tests_total} → {scan.total}); new tests are unbaselined"
        )
    if not new and not fixed:
        lines.append("  GREEN nothing here is attributable to your change")
    code = EXIT_DRIFT if (new or fixed) else EXIT_OK
    return Verdict(suite, new, fixed, held, scan.total, drift, code, tuple(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diff an odoo-bin test log against a recorded failure set."
    )
    parser.add_argument(
        "suite", nargs="?", help="test tag, e.g. /base or /quality_control"
    )
    parser.add_argument("log", nargs="?", type=Path, help="odoo-bin output to read")
    parser.add_argument(
        "--update",
        action="store_true",
        help="record this log's failures as the expected set",
    )
    parser.add_argument(
        "--verified-at", default="", help="commit the baseline was measured at"
    )
    parser.add_argument(
        "--run-spec",
        default="",
        help="the odoo-bin arguments that produced it — order-dependent failures "
        "only reproduce under the same spec",
    )
    parser.add_argument("--note", default="", help="why these are expected")
    parser.add_argument("--list", action="store_true", help="list known baselines")
    return parser


def render_list() -> int:
    paths = sorted(BASELINES_DIR.glob("*.json"))
    if not paths:
        print("no baselines recorded")
        return EXIT_OK
    for path in paths:
        base = Baseline.load(path.stem)
        if base is None:
            continue
        print(
            f"{base.suite:24} {len(base.expected):>3} expected of "
            f"{base.tests_total:<6} {base.verified_at}"
        )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list:
        return render_list()
    if args.suite is None or args.log is None:
        parser.error("a suite and a log are required unless --list is given")
    if not args.log.exists():
        print(f"no such log: {args.log}", file=sys.stderr)
        return EXIT_USAGE

    scan = scan_log(args.log)
    if args.update:
        if not scan.complete:
            print(
                "refusing to record an unfinished run: the log carries no "
                "`N failed, M error(s) of T tests` summary",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if not scan.sound:
            print(
                f"refusing to record an unsound parse: saw {len(scan.failures)}, "
                f"server reported {scan.reported_failed}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        path = Baseline(
            suite=args.suite,
            expected=dict(scan.failures),
            run_spec=args.run_spec,
            verified_at=args.verified_at,
            tests_total=scan.total,
            note=args.note,
        ).save()
        print(f"wrote {path}: {len(scan.failures)} expected of {scan.total}")
        return EXIT_OK

    verdict = evaluate(args.suite, scan, Baseline.load(args.suite))
    for line in verdict.lines:
        print(line)
    return verdict.exit_code


if __name__ == "__main__":
    sys.exit(main())
