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
* **It flags the assemble verbs unconditionally.** They are payload-only in
  `ABOLISHED` because the sibling reads a name and not a receiver, and widening
  that shared table would move the addon floor by names nobody has looked at.
  Here the population is small enough to have been read.
* **It reads the abolished table as families rather than as a word list.**
  §2.4.20's argument is that a row's printed entry can drain to zero while the
  operation goes on being performed under a word nobody listed, and that the
  drained entry then reads as a finished family. `SYNONYMS` is that reading made
  blocking, and the comment above it argues the exclusions as well as the
  entries.
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

The floor was six when this was written, all of them in `odoo/tests`: the second
sweep took every other part of core to zero and left the framework tree to a
sweep already running inside it, because colliding with a live rename is worse
than a floor. That sweep landed and the six are gone, so the gate is a hard zero
held by `test_naming_core_vocabulary` and by no baseline file -- which is why
every assertion in that module is aimed at a scan that has stopped looking
rather than at a count.
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

# §2.4.3's Payload row prints four verbs; the operation has more spellings than
# the row has entries. `assemble`, `craft` and `forge` name the same act under a
# word nobody listed, so they are read here on the same terms as the four -- flagged
# whatever the tail, and flagged bare.
ASSEMBLE = frozenset(
    {"build", "make", "compose", "construct", "assemble", "craft", "forge"}
)

# §2.4.20: read the table as families, not as a word list. `naming_vocabulary.py`
# matches the literal token by construction, so a row's entry can drain to zero
# while the operation goes on being performed under a synonym -- and the drained
# entry then reads as a finished family. Each key below is a word the table does
# not print whose body satisfies one of its rows; the value is that row's
# canonical and the reason, which is what the renamer needs and the count is not.
#
# This table is a core-only reading and belongs here rather than in the shared
# `ABOLISHED`: the addon floor would move by names nobody has looked at, which is
# the same argument the assemble verbs are carved out on. What is NOT here is as
# argued as what is:
#
# * `determine` is §2.4.20's own example and is left out, because core's
#   population is not the derivation the section describes -- `Field.determine*`
#   dispatches a hook by name or callable, which is a §2.4.9 question, and §2.4.9
#   is provisional and says no mechanical rewrite exists.
# * `collect` and `emit` need a discriminator this gate does not have. Most of
#   core's `collect_*` accumulate into a caller's container and return nothing,
#   which is not the Read row; `emit` is `logging.Handler.emit`, and an override
#   whose name is the contract is a rename that silently unhooks it.
# * `reap` and `probe` are terms of art from a layer below, on §2.4.3's
#   "reserved, not abolished" terms: `reap` is the POSIX wait-for-a-child, and
#   `probe` is a named subsystem in `odoo/db/`.
SYNONYMS: dict[str, tuple[str, str]] = {
    "populate": ("_update_", "populating is filling -- the Mutation row"),
    "prune": ("_remove_", "pruning is purging -- the Removal row"),
    "sweep": ("_remove_", "sweeping is purging -- the Removal row"),
    "seed": ("create", "seeding is creating"),
    "scan": ("_get_ or _read_", "reading a source and returning what is in it"),
    "refresh": (
        "_reset_ / _invalidate_ / _rebuild_",
        "names neither the drop nor the rebuild, which is what §2.4.17 exists to say",
    ),
}

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


# §2.4.3's Read row canonical is `_get_`, and its discriminator is the RETURN --
# "the return value feeds anything else". A `collect_*` is that row exactly when
# the value it returns is the value it produced. Where it fills a container it
# did not create -- a parameter, an attribute of its receiver, a closure variable
# of the function around it -- the product is that container and the return is
# bookkeeping: a loop variable, a recursion handle, a token-stream state. That is
# the Addition row acting on somebody else's object, and no rename this gate can
# name would improve it.
#
# The distinction is why `collect` was held out of `SYNONYMS` when the synonym
# table landed. It is not cosmetic: of core's twenty-six `collect_*`, eleven
# return a value and only seven of those own it. A rule that stopped at "returns
# something" would have demanded `_get_` from all eleven, and four of the answers
# would have been lies.
ACCUMULATE_VERBS = frozenset({"collect", "gather"})

_MUTATING_METHODS = frozenset(
    {
        "append",
        "appendleft",
        "add",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _names_bound_in(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every name the function itself creates, parameters included.

    A container is the function's own product when the function made it. The
    parameters count as bound but NOT as created -- `_owns_its_return` subtracts
    them, because a container handed in belongs to the caller.
    """
    bound: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            bound.add(child.id)
    return bound


def _mutated_roots(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    roots: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _MUTATING_METHODS
            and (root := _root_name(child.func.value)) is not None
        ):
            roots.add(root)
        targets: list[ast.expr] = []
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
        elif isinstance(child, ast.AugAssign | ast.AnnAssign):
            targets = [child.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute | ast.Subscript)
                and (root := _root_name(target)) is not None
            ):
                roots.add(root)
    return roots


def returns_a_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            if not (
                isinstance(child.value, ast.Constant) and child.value.value is None
            ):
                return True
        if isinstance(child, ast.Yield | ast.YieldFrom):
            return True
    return False


def raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(child, ast.Raise) for child in ast.walk(node))


def owns_its_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The value it returns is a value it made, not one it was handed."""
    if not returns_a_value(node):
        return False
    args = node.args
    parameters = {
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if a is not None
    }
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            parameters.add(extra.arg)
    created = _names_bound_in(node) - parameters
    return not (_mutated_roots(node) - created)


# §2.4.8's three predicate prefixes, plus the modal §2.4.20 reads onto them.
# A predicate does not perform the operation its tail names -- it answers a
# question ABOUT it -- so the verb behind one of these is the subject and not a
# §2.4.4 hiding place. `can_scan_identity` asks whether a field's cache admits an
# identity scan; renaming its middle token would be renaming the question.
PREDICATE_PREFIXES = frozenset({"is", "has", "can", "should"})


def infix_synonym(name: str) -> str | None:
    """A synonym parked behind a noun -- §2.4.4's hiding place, one table over.

    `nv.infix_abolished_verb` asks the same question of the shared table. A
    synonym hides in the same position for the same reason: `classify` partitions
    on the first token, so a noun in front of the verb is invisible to it.
    """
    tokens = name.lstrip("_").split("_")
    if tokens[0] in PREDICATE_PREFIXES:
        return None
    for token in tokens[1:-1]:
        if token in SYNONYMS:
            return token
    return None


# §2.4.20: a public `check_*` that returns instead of raising is the Validation
# row's blind spot, and the row's discriminator is what the method does ON
# FAILURE. `_check_*` promises a raise; where the answer is *returns something*,
# the prefix is wrong whatever the underscore, and no gate aimed at internals
# sees it because no @api.constrains binds it.
#
# The proxy is mechanical -- the body returns a value and raises nothing -- and
# it IS a proxy: a check whose failure path is a helper's raise reads from here
# exactly like a read. Those are argued into the allowlist rather than renamed,
# which is the honest shape for a rule whose test is one frame deep.
def classify_definition(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str] | None:
    """Return (kind, why) for a definition the vocabulary refuses, else None.

    The name alone settles most of it; two rules need the body, because their
    discriminator is a claim about behaviour rather than about spelling.
    """
    if (hit := classify_name(node.name)) is not None:
        return hit
    stem = node.name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if not rest:
        return None
    if verb in ACCUMULATE_VERBS and owns_its_return(node):
        why = (
            f"{verb} -> _get_ -- it returns the value it made, which is the "
            f"Read row; a collector that fills a caller's container is not"
        )
        return ("accumulate", why)
    if verb == "check" and returns_a_value(node) and not raises(node):
        why = (
            "`check_` promises a raise on failure and this returns instead -- "
            "§2.4.20; take the row the body satisfies (_get_, _is_, _parse_)"
        )
        return ("check-returns", why)
    return None


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
    if (entry := SYNONYMS.get(verb)) is not None:
        return "synonym", f"{verb} -> {entry[0]} -- {entry[1]}"
    if (token := nv.infix_abolished_verb(name)) is not None:
        return "infix", f"`{token}` behind a noun -- §2.4.4, unless it is a noun"
    if (token := infix_synonym(name)) is not None:
        canonical, why = SYNONYMS[token]
        return "infix-synonym", f"`{token}` behind a noun -> {canonical} -- {why}"
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


def measure(
    root: Path | None = None, *, apply_allowlist: bool = True
) -> list[Violation]:
    """Every definition the vocabulary refuses.

    `apply_allowlist=False` is what the allowlist's own test needs: two of the
    rules read a body, so "would this name be reported" cannot be answered from
    the name, and an entry that hides nothing has to be caught by rescanning
    without it.
    """
    files = core_files(root)
    if not files:
        raise RuntimeError(
            f"no Python files under {root or CORE} -- refusing to report a count "
            f"from an empty scan"
        )
    allowed = load_allowlist() if apply_allowlist else {}
    found: list[Violation] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in allowed or nv._overrides_same_name(node):
                continue
            if (hit := classify_definition(node)) is None:
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
