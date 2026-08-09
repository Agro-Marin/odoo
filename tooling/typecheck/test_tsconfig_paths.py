"""``tsconfig.json``'s ``paths`` map must cover the aliases the tree imports.

Every Odoo addon ``X`` that ships ``static/src/`` publishes its modules as
``@X/*``. TypeScript learns that mapping from ``tsconfig.json`` alone, and the
map was hand-maintained: it had drifted to covering a minority of the aliases
actually imported, so imports through the rest resolved to nothing.

Nothing failed when they did, which is why it went unnoticed for so long. A file
that imports an unresolvable module reports ``TS2307`` **only if it is
checked**, and the addons in question carry almost no ``@ts-check`` — 40 files
across the ~5000 outside ``addons/web``. So the map could rot indefinitely while
every lane stayed green, and the cost was invisible until something tried to
*read* it: a resolver walking `class X extends Y` across addons cannot follow
``FsmProjectTaskFormController -> ProjectTaskFormController -> FormController``
without ``@project/*``.

Adding the absent entries changed the error count by zero — measured on a frozen
snapshot, both arms identical in both directions. That is the expected result,
not a disappointment: it means the map can be completed for free, *before*
``@ts-check`` is turned on outward, rather than being discovered as a wall
afterwards.

Stdlib + pytest only, like the gates it sits beside.

**Scope-honest.** Sibling checkouts may be absent — CI checks out this repo
alone — so an alias is judged only when the addon that would satisfy it is on
disk, and a pinned entry is judged stale only when its target's *checkout* is
present. Without that, a repo-alone run would demand entries it cannot verify
and reject entries it cannot see.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_tsconfig_paths")
TSCONFIG = ROOT / "tsconfig.json"

# (checkout root, the prefix a paths entry uses to reach it)
CHECKOUTS = (
    (ROOT / "addons", "addons"),
    (ROOT.parent / "enterprise", "../enterprise"),
    (ROOT.parent / "agromarin", "../agromarin"),
    (ROOT.parent / "design-themes", "../design-themes"),
)
SKIP = ("/static/lib/", "/node_modules/")
IMPORT_ALIAS = re.compile(r"""from\s*["']@([A-Za-z_0-9]+)/""")

# `@odoo/*` is owl/hoot — libraries resolved by exact entries, not addons.
NOT_ADDONS = frozenset({"odoo"})


def _load_paths() -> dict:
    """``compilerOptions.paths``. The file carries ``//`` comments, so it is
    JSON-with-comments and must be stripped before parsing — the same way
    ``tsconfig`` consumers treat it."""
    text = re.sub(r"//.*", "", TSCONFIG.read_text(encoding="utf8"))
    return json.loads(text)["compilerOptions"]["paths"]


def _addons_on_disk() -> dict[str, str]:
    """``{addon: "<prefix>/<addon>/static/src/*"}`` for every addon present."""
    found: dict[str, str] = {}
    for base, prefix in CHECKOUTS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if (entry / "static" / "src").is_dir():
                found.setdefault(entry.name, f"{prefix}/{entry.name}/static/src/*")
    return found


def _aliases_imported() -> Counter:
    """``{alias: import sites}`` over every checkout present."""
    used: Counter = Counter()
    for base, _prefix in CHECKOUTS:
        if not base.is_dir():
            continue
        for path in base.rglob("*.js"):
            text = path.as_posix()
            if any(skip in text for skip in SKIP):
                continue
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            for alias in IMPORT_ALIAS.findall(source):
                used[alias] += 1
    return used


def test_the_scan_reaches_the_tree():
    """A gate that measured nothing must fail, not pass vacuously."""
    used = _aliases_imported()
    assert used, "no `@alias/` imports found — the scan reached nothing"
    assert used["web"] > 1000, f"implausibly few @web imports: {used['web']}"


def test_every_imported_addon_alias_is_mapped():
    paths = _load_paths()
    on_disk = _addons_on_disk()
    used = _aliases_imported()
    missing = {
        alias: count
        for alias, count in used.items()
        if alias not in NOT_ADDONS and alias in on_disk and f"@{alias}/*" not in paths
    }
    assert not missing, (
        f"{len(missing)} addon alias(es) imported but absent from tsconfig paths "
        f"({sum(missing.values())} import sites): "
        + ", ".join(f"@{a}" for a in sorted(missing)[:12])
        + "\n  every addon shipping static/src must publish `@<addon>/*`"
    )


def test_no_mapped_alias_is_dead():
    """A dead entry silences nothing while looking like it does.

    Dead means **both** halves: the target directory is absent *and* nothing
    imports the alias. Either alone is legitimate.

    A missing directory is not enough, because of the `..` escape hatch:
    `@test_mail/../tests/foo` maps to `addons/test_mail/static/src/../tests/foo`
    = `addons/test_mail/static/tests/foo`, which resolves textually and works
    even though `test_mail` ships no `static/src` at all. Nine files depend on
    exactly that. An earlier version of this test flagged it, which would have
    deleted a load-bearing entry on the grounds that its directory was missing.

    Judged only for targets whose checkout is present: a repo-alone run cannot
    see `../enterprise` and must not call those entries dead.
    """
    present = {prefix for base, prefix in CHECKOUTS if base.is_dir()}
    used = _aliases_imported()
    stale = []
    for alias, targets in _load_paths().items():
        if used.get(alias.removeprefix("@").removesuffix("/*"), 0):
            continue
        for target in targets:
            prefix = target.split("/")[0]
            if prefix == "..":
                prefix = "/".join(target.split("/")[:2])
            if prefix not in present:
                continue
            # Two entry shapes: a glob (`@web/*` -> a directory) and an exact
            # file (`@odoo/hoot` -> hoot.js). Only the first strips `/*`.
            if target.endswith("/*"):
                ok = (ROOT / target.removesuffix("/*")).resolve().is_dir()
            else:
                ok = (ROOT / target).resolve().is_file()
            if not ok:
                stale.append(f"{alias} -> {target}")
    assert not stale, (
        "tsconfig paths entries that map nothing and are imported by nobody:\n  "
        + "\n  ".join(stale)
        + "\n  remove them; an entry pointing at an absent directory maps no module"
    )


@pytest.mark.parametrize("alias", ["web", "mail", "project", "point_of_sale"])
def test_the_load_bearing_aliases_are_mapped(alias):
    """Named explicitly so the general assertions above cannot go vacuous.

    `@project/*` is here because its absence is what first exposed the drift —
    it broke an inheritance chain that crossed three addons.
    """
    if alias not in _addons_on_disk():
        pytest.skip(f"{alias} not in this checkout")
    assert f"@{alias}/*" in _load_paths()
