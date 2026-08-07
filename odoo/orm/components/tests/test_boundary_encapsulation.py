"""``components/`` privates stay inside ``components/``.

``ModelGraph.set_inverses``'s docstring states the package's hand-off rule
outright: *"Going through a method keeps that hand-off greppable instead of an
assignment to a private attribute from outside."*  The graph then publishes
``field_depends`` / ``field_depends_context`` / ``field_inverses`` /
``field_computed`` / ``published_triggers`` as public accessors precisely so
consumers never need the underscored attribute.

The rule was not enforced, and its only consumer had drifted:
``runtime/_registry_fields.py`` read ``model_graph._depends``,
``model_graph._depends_context`` and ``graph._triggers`` directly -- past two
accessors that already existed and one that did not (``published_triggers``,
added with this test).

This is the same argument as ``mixin_coupling_check.py`` and
``env_model_surface_check.py``: an attribute poke produces the *same* import
edge as a method call, so ``layer_check.py`` reports the boundary clean either
way.  Kept as a unit test rather than a CI gate because the surface is small
and package-local; promote it to ``tooling/architecture/`` if it grows.
"""

import ast
import pathlib

CORE = pathlib.Path(__file__).resolve().parent.parent.parent.parent
COMPONENTS = CORE / "orm" / "components"

#: Names that hold a ``components/`` object.  Scanning by holder name (rather
#: than by type, which would need inference) is what keeps this cheap; adding a
#: component means adding its conventional variable name here.
COMPONENT_HOLDERS = frozenset(
    {"model_graph", "graph", "cache", "engine", "core", "unit_of_work"}
)

#: Scoped to ``orm/`` on purpose.  These holder names are only unambiguous
#: here: ``modules/loading.py`` also has a local called ``graph``, and it is a
#: :class:`~odoo.modules.module_graph.ModuleGraph` -- a different class in a
#: different package, whose ``_imported_modules`` is a legitimate
#: package-internal access from its sibling module.  A tree-wide scan reports
#: it and is simply wrong.  Every real consumer of ``components/`` lives under
#: ``orm/`` (``runtime/``, ``models/mixins/``), so nothing is lost.
SCAN_ROOT = CORE / "orm"


def _component_private_reaches():
    """Return ``file:line name._attr`` for every reach from outside the package."""
    reaches = []
    for path in SCAN_ROOT.rglob("*.py"):
        parts = path.parts
        if "components" in parts or "tests" in parts:
            continue
        if path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not node.attr.startswith("_") or node.attr.startswith("__"):
                continue
            value = node.value
            if isinstance(value, ast.Name):
                holder = value.id
            elif isinstance(value, ast.Attribute):
                holder = value.attr
            else:
                continue
            if holder in COMPONENT_HOLDERS:
                reaches.append(
                    f"{path.relative_to(CORE)}:{node.lineno} {holder}.{node.attr}"
                )
    return reaches


def test_the_scan_can_see_the_tree():
    """Guard the guard: a broken path glob would make the check below vacuous."""
    assert COMPONENTS.is_dir()
    assert any(CORE.rglob("orm/runtime/_registry_fields.py"))


def test_public_accessors_exist_for_every_published_map():
    """The accessors that make the rule followable must not be removed."""
    from odoo.orm.components.model_graph import ModelGraph

    for name in (
        "field_depends",
        "field_depends_context",
        "field_inverses",
        "field_computed",
        "published_triggers",
    ):
        assert isinstance(getattr(ModelGraph, name), property), name


def test_no_core_code_reaches_into_component_privates():
    leaking = _component_private_reaches()
    assert not leaking, (
        "reached a components/ private from outside the package; use the "
        "public accessor (see ModelGraph.set_inverses' docstring): "
        + ", ".join(leaking)
    )
