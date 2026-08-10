import ast
import pathlib

import pytest

from odoo.orm.components.core import OrmCore

_CORE = pathlib.Path(__file__).resolve().parents[2]
_COMPONENTS = _CORE / "orm" / "components"

# ADR-0010 calls `env._core` (OrmCore) a "curated id-level facade" over
# FieldCache/ComputeEngine, and ARCHITECTURE.md states that "the raw objects
# stay private to Transaction (`_cache_store`/`_compute_engine`)".
#
# That was not true. OrmCore's slots were named `cache` and `engine`, so
# `env._core.cache` **was** `transaction._cache_store` -- the exact object the
# facade exists to wrap, reachable through a public attribute on the wrapper.
# Two addon tests used it, both for `get_value`, which the facade did not
# expose: the hole existed because the curated surface was incomplete, which is
# how curated surfaces usually acquire holes.
#
# The slots are now `_cache`/`_engine` (the constructor keywords stay
# `cache=`/`engine=`, because collaborator injection is ADR-0002's contract and
# Transaction passes them). These tests keep the claim true.


def _reaches_raw_collaborator() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in sorted(_CORE.rglob("*.py")):
        try:
            rel = path.relative_to(_CORE).as_posix()
        except ValueError:  # pragma: no cover
            continue
        if rel.startswith("orm/components/"):
            continue  # the owner may touch its own internals
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr not in ("_cache", "_engine"):
                continue
            owner = node.value
            if isinstance(owner, ast.Attribute) and owner.attr == "_core":
                hits.append((rel, node.lineno, node.attr))
    return hits


def _core_member_reaches() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in sorted(_CORE.rglob("*.py")):
        try:
            rel = path.relative_to(_CORE).as_posix()
        except ValueError:  # pragma: no cover
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue

        # Names bound to the facade anywhere in this module. Module-scoped
        # rather than per-function: an over-wide alias set can only make the
        # check stricter, never blind, which is the safe direction here.
        aliases = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "_core"
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            owner = node.value
            reached = (isinstance(owner, ast.Attribute) and owner.attr == "_core") or (
                isinstance(owner, ast.Name) and owner.id in aliases
            )
            if reached:
                hits.append((rel, node.lineno, node.attr))
    return hits


def test_every_member_reached_through_the_facade_exists_on_it():
    known = set(dir(OrmCore))
    missing = [
        (rel, lineno, attr)
        for rel, lineno, attr in _core_member_reaches()
        if attr not in known and not attr.startswith("__")
    ]
    assert not missing, (
        f"code reaches OrmCore members that do not exist: {missing}. Either the "
        f"facade lost a method its callers still use, or a caller was not "
        f"updated when it was renamed — both are AttributeError at runtime."
    )


def test_the_member_scan_sees_the_addon_tests_that_broke():
    reached = _core_member_reaches()
    assert reached, "the _core member scan found nothing at all"
    addon_files = {rel for rel, _, _ in reached if rel.startswith("addons/")}
    assert addon_files, (
        "the scan no longer reaches odoo/addons/**, which is where the callers "
        "that broke live — the missing-member test above is now vacuous"
    )


def test_raw_collaborators_are_not_reachable_as_public_attributes():
    public = [n for n in OrmCore.__slots__ if not n.startswith("_")]
    assert not public, (
        f"OrmCore exposes {public} publicly. Those slots hold the very "
        f"FieldCache/ComputeEngine that Transaction keeps private, so a public "
        f"name here makes `env._core.<x>` a pass-through to the raw object and "
        f"makes ARCHITECTURE.md's 'the raw objects stay private' false."
    )


def test_nothing_outside_components_reaches_the_raw_collaborators():
    hits = _reaches_raw_collaborator()
    assert not hits, (
        f"code outside orm/components/ reaches OrmCore's raw collaborators: "
        f"{hits}. Add the method it needs to OrmCore instead — that is what the "
        f"facade is for, and a missing method is why the previous hole existed."
    )


def test_the_facade_still_covers_what_callers_needed():
    # Regression pin for the specific gap that caused the breach: two addon
    # tests wanted a cached value by (field, id) and the facade had no way to
    # give it to them.
    assert callable(OrmCore.get_value)


def test_constructor_injection_still_works():
    # ADR-0002: collaborators are injected. Making the *attributes* private must
    # not make the *keywords* private, or Transaction and the component unit
    # tests break.
    from odoo.orm.components.cache import FieldCache
    from odoo.orm.components.compute import ComputeEngine

    cache, engine = FieldCache(), ComputeEngine()
    core = OrmCore(cache=cache, engine=engine)
    assert core._cache is cache
    assert core._engine is engine


def test_scan_is_not_vacuous():
    # The scan must actually be walking the tree; if `_CORE` or the filter ever
    # breaks, `_reaches_raw_collaborator()` returns [] and the gate above
    # passes while checking nothing.
    assert (_COMPONENTS / "core.py").is_file()
    assert len(list(_CORE.rglob("*.py"))) > 500


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
