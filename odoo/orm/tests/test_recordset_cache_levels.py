import ast
import inspect
import pathlib

import pytest

from odoo.orm.components.core import OrmCore
from odoo.orm.runtime.recordset_cache import Cache


def test_the_class_states_which_level_it_is():
    doc = inspect.getdoc(Cache)
    assert doc, (
        "Cache lost its docstring. Without it the class reads as an unexplained "
        "second cache surface beside env._core."
    )
    assert "recordset" in doc.lower(), "the docstring must say which level it is"


def test_the_module_is_not_named_for_what_it_is_not():
    path = pathlib.Path(inspect.getfile(Cache))
    assert path.name == "recordset_cache.py", (
        f"the module is named {path.name!r}. A name describing what the class is "
        f"NOT (compat / legacy / shim) is what made three separate documents "
        f"restate the same correction, twice each."
    )


def test_nothing_marks_it_deprecated():
    source = pathlib.Path(inspect.getfile(Cache)).read_text(encoding="utf-8")
    assert "@api.deprecated" not in source and "DeprecationWarning" not in source, (
        "env.cache is marked deprecated. If that is now the intent it needs "
        "a superseding ADR and a migration for the addon call sites, not a "
        "decorator -- ADR-0010 costed that migration and dropped it."
    )


def test_the_two_surfaces_stay_at_different_levels():
    tree = ast.parse(pathlib.Path(inspect.getfile(Cache)).read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Cache"
    )
    recordset_params = {"record", "records", "model"}
    public = [
        n
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    ]
    assert public, "Cache has no public methods; the collector has rotted"

    takes_recordset = [
        n.name for n in public if recordset_params & {a.arg for a in n.args.args}
    ]
    assert takes_recordset, (
        "no Cache method takes a recordset any more -- it has become id-level, "
        "which is what env._core already is"
    )

    # OrmCore is the other half of the claim: id-level, never recordset-level.
    core_src = pathlib.Path(inspect.getfile(OrmCore)).read_text(encoding="utf-8")
    core_tree = ast.parse(core_src)
    core_cls = next(
        n for n in core_tree.body if isinstance(n, ast.ClassDef) and n.name == "OrmCore"
    )
    core_recordset = [
        n.name
        for n in core_cls.body
        if isinstance(n, ast.FunctionDef)
        and not n.name.startswith("_")
        and recordset_params & {a.arg for a in n.args.args}
    ]
    assert not core_recordset, (
        f"OrmCore method(s) now take a recordset: {core_recordset}. It is the "
        f"id-level facade; if it grows recordset-level entry points it starts "
        f"duplicating env.cache, and ADR-0010's reasoning needs revisiting."
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
