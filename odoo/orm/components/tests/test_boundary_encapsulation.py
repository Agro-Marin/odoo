import ast
import pathlib

CORE = pathlib.Path(__file__).resolve().parent.parent.parent.parent
COMPONENTS = CORE / "orm" / "components"

COMPONENT_HOLDERS = frozenset(
    {"model_graph", "graph", "cache", "engine", "core", "unit_of_work"}
)

SCAN_ROOT = CORE / "orm"


def _component_private_reaches():
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
    assert COMPONENTS.is_dir()
    assert any(CORE.rglob("orm/runtime/_registry_fields.py"))


def test_public_accessors_exist_for_every_published_map():
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
