from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

ADR = "0079"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="module_suite_lane")

MANIFEST = "__manifest__.py"

# CLAUDE.md 9.6 and the decision it records: both ship substantial suites that
# no lane runs, deliberately, and the cost is stated there. Exempt by name so
# the gate reports the decision rather than re-opening it, and so a third
# module cannot join them silently.
EXEMPT: dict[str, str] = {
    "credential": "no lane, by the decision recorded in CLAUDE.md 9.6",
    "api_transport": "no lane, by the decision recorded in CLAUDE.md 9.6",
}

_TAG = re.compile(r"[-+]?/([a-z0-9_]+)")
_TEST_TAGS = re.compile(r"--test-tags[= ]+[\"']?([^\"'\n\\]+)")


@dataclass(frozen=True)
class Offence:
    module: str
    module_path: str
    tests: int

    def __str__(self) -> str:
        return (
            f"{self.module_path}  ships {self.tests} test method(s) that no lane runs"
        )


def _read_manifest(path: Path) -> dict | None:
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except SyntaxError, ValueError, UnicodeDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _test_methods(directory: Path) -> int:
    total = 0
    for path in sorted(directory.glob("tests/**/*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        total += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return total


def modules_with_tests(roots: list[Path]) -> dict[str, tuple[Path, int]]:
    found: dict[str, tuple[Path, int]] = {}
    for root in roots:
        for manifest in sorted(root.glob(f"*/{MANIFEST}")):
            data = _read_manifest(manifest)
            if data is None or not data.get("installable", True):
                continue
            directory = manifest.parent
            count = _test_methods(directory)
            if count:
                found[directory.name] = (directory, count)
    return found


def modules_a_lane_runs(workflows: Path) -> set[str]:
    # A module's suite runs because a lane NAMES it in --test-tags, not because
    # something installed it: `sale` is installed by the base_order lane and its
    # own tests do not run there. Tags are the predicate; installs are not.
    named: set[str] = set()
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "--test-enable" not in text:
            continue
        for value in _TEST_TAGS.findall(text):
            for entry in value.split(","):
                entry = entry.strip()
                if entry.startswith("-"):
                    continue
                match = _TAG.match(entry)
                if match:
                    named.add(match.group(1))
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.endswith("_TEST_TAGS:") and "_TEST_TAGS:" in stripped:
                value = stripped.split("_TEST_TAGS:", 1)[1]
                for entry in value.split(","):
                    match = _TAG.match(entry.strip())
                    if match:
                        named.add(match.group(1))
    return named


def default_roots() -> list[Path]:
    return [ROOT / "addons", ROOT / "odoo" / "addons"]


def measure(
    roots: list[Path] | None = None, workflows: Path | None = None
) -> list[Offence]:
    roots = roots or default_roots()
    workflows = workflows or (ROOT / ".github" / "workflows")

    missing = [root for root in roots if not root.is_dir()]
    if missing:
        raise RuntimeError(
            "no such directory: " + ", ".join(str(root) for root in missing)
        )
    if not workflows.is_dir():
        raise RuntimeError(f"no such directory: {workflows}")

    with_tests = modules_with_tests(roots)
    if not with_tests:
        raise RuntimeError(
            "no module with tests under "
            + ", ".join(str(root) for root in roots)
            + " — refusing to report a result measured over nothing"
        )

    covered = modules_a_lane_runs(workflows)
    if not covered:
        raise RuntimeError(
            f"no lane in {workflows} names a module in --test-tags — the scan "
            "found nothing to compare against, and every module would report "
            "as uncovered. A lane that passes --test-enable and no --test-tags "
            "runs whatever it installs, which is a real shape (agromarin's "
            "tests.yml discovers its module list at run time and tags nothing) "
            "and one this gate cannot read: what such a lane covers is not in "
            "the file. Point --workflows at a directory whose lanes name their "
            "modules, or measure that repository some other way"
        )

    offences = [
        Offence(module=name, module_path=str(directory), tests=count)
        for name, (directory, count) in with_tests.items()
        if name not in covered and name not in EXEMPT
    ]
    return sorted(offences, key=lambda o: (-o.tests, o.module))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero if any offence is found"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of the odoo checkout"
    )
    parser.add_argument(
        "--workflows", help="read lanes from here instead of .github/workflows"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    workflows = Path(args.workflows).resolve() if args.workflows else None
    try:
        found = measure(roots, workflows)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(o) for o in found], indent=2))
        return 0

    print("Modules whose tests no CI lane runs")
    print("=" * 72)
    for offence in found:
        print(f"  {offence}")
    if not found:
        print("  none")
    for name, reason in sorted(EXEMPT.items()):
        print(f"  ({name}: {reason})")
    print("-" * 72)
    print(f"\n{len(found)} module(s) testing themselves into silence")
    if found:
        print(
            "\nEach ships a suite that passes or fails and is read by nobody. "
            "Give it a\nlane in .github/workflows -- naming the module in "
            "--test-tags, and installing\nwhatever its tests reach past its own "
            "depends -- or record a decision not to\nand add it to EXEMPT with "
            "the reason."
        )

    if args.check and found:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
