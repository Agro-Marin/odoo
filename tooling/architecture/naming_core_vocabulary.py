"""The method vocabulary over every function in the core package.

`naming_vocabulary.py` implements §2.4.13's scope as a class-membership test, so
it reports on methods declared on `models.Model` and its siblings and on nothing
else. That is the right population for the addon floor it feeds -- an addon is
model classes and little else -- and it is the wrong one for `odoo/`, which is
overwhelmingly module-level functions and plain classes. Core was swept by hand
for exactly that reason when the vocabulary was extended to every function in
it, and swept again three days later -- the assemble verbs losing their
carve-out -- over a population the first sweep's measurement could not see.

This gate is the checker the first sweep sketched and the second argued had
become owed. It differs from its sibling in three ways, each of which is why a
`--roots` flag on the sibling would not have done:

* **It reads every function**, not the methods of model classes.
* **It flags the four assemble verbs unconditionally.** They are payload-only in
  `ABOLISHED` because the sibling reads a name and not a receiver, and widening
  that shared table would move the addon floor by names nobody has looked at.
  Here the population is small enough to have been read.
* **It flags a bare assemble verb.** `classify` partitions on the first token
  and returns `None` when there is no remainder, so `make()` and `_build()` are
  invisible to every rule in §2.4. Seven of the second sweep's forty-five were
  spelled that way.

Bare verbs from the rest of the abolished table are **not** flagged, and the
line is drawn there on purpose. There is no reading under which a bare `make()`
is right -- the Payload row has no exception for it. A bare `delete` often is:
`orm/runtime/backend.py` declares one on a Protocol, `libs/password.py` has a
`verify` beside a `hash` and an `identify`, and in both the bare name IS the
contract being implemented. Those are §2.4.6's `[review]` tier and stay there.
`--candidates` prints them, so the population is visible without being blocking.

What survives the vocabulary in core is a list and not a package boundary, so the
survivors are an allowlist naming each one and why, never a floor. A floor would
let the next one in silently; an entry has to be argued.

The floor is not zero and the difference matters. It stands at six, all of them
in `odoo/tests`: the second sweep took every other part of core to zero and left
the framework tree to a sweep already running inside it, because colliding with a live
rename is worse than a floor. That is the one population here that is debt
rather than a survivor, it is one commit from gone, and the allowlist is not the
place to put it -- `test_naming_core_vocabulary` pins the six by NAME so a new
finding in `orm/` cannot hide behind one of them going away.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ast_cache
import _sources
import naming_vocabulary as nv
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve())
CORE = ROOT / "odoo"

# `_sources.is_test_path` calls any path with a `tests` component a test path.
# That is right for odoo/orm/tests and its siblings and wrong for exactly one
# tree: odoo/tests is the test FRAMEWORK -- TransactionCase, HttpCase, the CDP
# driver, the suite runner -- production code every addon test runs on, excluded
# by the name of its directory rather than by anything about it. The same
# reasoning `test_excluded_trees_stay_empty.py` records, applied to a gate that
# can act on it: TestCursor lives in a file called test_cursor.py and is a
# cursor, not a suite.
FRAMEWORK = CORE / "tests"

ALLOWLIST = Path(__file__).with_name("naming_core_allowlist.json")

ASSEMBLE = frozenset({"build", "make", "compose", "construct"})

# Vendored code is not ours to rename. `nv.SKIP_DIRS` carries "vendored"; this
# tree spells it with the underscore.
SKIP_DIRS = nv.SKIP_DIRS | {"_vendor"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    kind: str
    why: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.name}  [{self.kind}] {self.why}"


def load_allowlist() -> dict[str, str]:
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))["names"]


def is_suite(path: Path) -> bool:
    if path.is_relative_to(FRAMEWORK):
        return False
    return "tests" in path.parts or path.name.startswith("test_")


def core_files(root: Path | None = None) -> list[Path]:
    scan = root or CORE
    return [
        path
        for path in sorted(scan.rglob("*.py"))
        if not (set(path.parts) & SKIP_DIRS) and not is_suite(path)
    ]


def classify_name(name: str) -> tuple[str, str] | None:
    """Return (kind, why) for a name the vocabulary refuses, else None."""
    if name.startswith("__") and name.endswith("__"):
        return None
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if not rest:
        if verb in ASSEMBLE:
            return "bare", f"`{verb}` alone -- abolished, and §2.4.6 wants a noun"
        return None
    if (hit := nv.classify(name)) is not None:
        return "leading", f"{hit[0]} -> {hit[1]}*"
    if verb in ASSEMBLE:
        return "assemble", f"{verb} -> _prepare_* or _get_*, on the consumer test"
    if (token := nv.infix_abolished_verb(name)) is not None:
        return "infix", f"`{token}` behind a noun -- §2.4.4, unless it is a noun"
    return None


def is_bare_abolished(name: str) -> bool:
    """A bare abolished verb that is not an assemble verb -- §2.4.6 [review].

    The gate does not report these; `candidates` does. The allowlist covers
    both, which is why `fetch` earns an entry: nothing would flag it, and
    without the entry it would read as an open question rather than a
    reservation.
    """
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    return not rest and verb not in ASSEMBLE and verb in nv.ABOLISHED


def measure(root: Path | None = None) -> list[Violation]:
    files = core_files(root)
    if not files:
        raise RuntimeError(
            f"no Python files under {root or CORE} -- refusing to report a count "
            f"from an empty scan"
        )
    allowed = load_allowlist()
    found: list[Violation] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in allowed or nv._overrides_same_name(node):
                continue
            if (hit := classify_name(node.name)) is None:
                continue
            found.append(
                Violation(
                    path=_sources.display(path, ROOT),
                    line=node.lineno,
                    name=node.name,
                    kind=hit[0],
                    why=hit[1],
                )
            )
    found.sort(key=lambda v: (v.path, v.line))
    return found


def candidates(root: Path | None = None) -> list[Violation]:
    """Bare abolished verbs that are not assemble verbs -- a population to read.

    Not a violation count: several are the contract they implement, and telling
    those apart is what §2.4.6's `[review]` tier is for.
    """
    allowed = load_allowlist()
    found: list[Violation] = []
    for path in core_files(root):
        tree = _ast_cache.parse_file(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in allowed or not is_bare_abolished(node.name):
                continue
            verb = node.name.lstrip("_").partition("_")[0]
            found.append(
                Violation(
                    path=_sources.display(path, ROOT),
                    line=node.lineno,
                    name=node.name,
                    kind="bare-review",
                    why=f"`{verb}` alone -- read the body before renaming",
                )
            )
    found.sort(key=lambda v: (v.path, v.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--allowed", action="store_true", help="print the survivors and why"
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="print bare non-assemble verbs -- §2.4.6 [review], not gated",
    )
    args = parser.parse_args(argv)

    if args.candidates:
        for item in candidates():
            print(f"  {item}")
        return 0

    if args.allowed:
        for name, why in sorted(load_allowlist().items()):
            print(f"  {name:34} {why}")
        return 0

    try:
        found = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Method vocabulary over every function in odoo/")
    print("=" * 72)
    for item in found if args.top == 0 else found[: args.top]:
        print(f"  {item}")
    print(f"\n{len(found)} definition(s); {len(load_allowlist())} allowed by name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
