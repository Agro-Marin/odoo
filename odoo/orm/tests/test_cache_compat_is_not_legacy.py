"""``env.cache`` is the recordset-level cache API, and nothing may call it legacy.

ADR-0010 proposed retiring ``cache_compat.Cache`` (step 4) and **dropped that
step on reassessment**: it is not redundant with the id-level ``env._core`` but
a different abstraction level, and the proposed migration would have mishandled
context-dependent and term-translated cache layouts.

That conclusion has been lost twice already. The ADR's own *Context* and
*Consequences* sections still call ``env.cache`` legacy, because they were
written before the reassessment and an ADR is append-only;
``doc/architecture/module.md`` inherited the word from them and repeated it
until 2026-08-08; and the class docstring the ADR credits for the correction was
deleted by ``eff67f80316``'s docstring strip, so the code said nothing either
way. Three statements, and the only surviving correct one was buried in an
Implementation-status paragraph.

So this pins the conclusion where a reader will meet it, and pins the property
the conclusion rests on: the two surfaces really do sit at different levels.
"""

import ast
import inspect
import pathlib
import re

import pytest

from odoo.orm.components.core import OrmCore
from odoo.orm.runtime.cache_compat import Cache

#: Counted parents rather than found by the ``odoo-bin`` marker, unlike
#: ``test_registry_cache_buckets``: a wrong path here makes ``read_text`` raise
#: FileNotFoundError, which is a loud failure. There, a wrong root silently
#: widened a scan and the test still passed, which is the case that needs the
#: marker.
_MODULE_VIEW = (
    pathlib.Path(__file__).resolve().parents[3] / "doc" / "architecture" / "module.md"
)


def test_the_class_states_what_it_is():
    doc = inspect.getdoc(Cache)
    assert doc, (
        "cache_compat.Cache lost its docstring again. It is the third copy of "
        "ADR-0010's reassessment and the only one in the code; without it the "
        "class reads as an unexplained wrapper over env._core."
    )
    assert "recordset" in doc.lower(), "the docstring must say which level it is"
    assert re.search(r"not\b.{0,40}\blegacy|dropped that step", doc, re.IGNORECASE), (
        "the docstring must say it is NOT legacy -- that is the whole point"
    )


def test_the_module_view_does_not_call_it_legacy():
    text = _MODULE_VIEW.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert "env.cache" in flat, "module.md no longer mentions env.cache"
    # The page may (and does) explain that it *used* to carry the label.
    assert "is the legacy recordset-level wrapper" not in flat, (
        "doc/architecture/module.md calls env.cache legacy again. ADR-0010's "
        "Implementation status dropped step 4 on reassessment; the word came "
        "from its pre-reassessment Context section."
    )


def test_nothing_marks_it_deprecated():
    source = pathlib.Path(inspect.getfile(Cache)).read_text(encoding="utf-8")
    assert "@api.deprecated" not in source and "DeprecationWarning" not in source, (
        "cache_compat is marked deprecated. If that is now the intent it needs "
        "a superseding ADR and a migration for the addon call sites, not a "
        "decorator -- ADR-0010 costed that migration and dropped it."
    )


def test_the_two_surfaces_stay_at_different_levels():
    """The property the whole decision rests on, checked rather than asserted.

    ``Cache`` methods take a recordset (``record`` / ``records`` / ``model``);
    ``OrmCore`` methods take a field and a raw ``record_id``. If those ever
    converge, the "different abstraction level" argument stops holding and the
    retire-vs-keep question genuinely reopens.
    """
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
