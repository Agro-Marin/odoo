import ast
import pathlib

import pytest

# PEP 649 (Python 3.14) made annotations lazily *evaluated* rather than stored
# as strings.  `inspect.signature(fn)` therefore evaluates the annotations, and
# a name that exists only under `if TYPE_CHECKING:` raises NameError.
#
# That is not an exotic case here: `ARCHITECTURE.md` prescribes exactly this
# style for cross-layer references ("Cross-layer references for *typing* are
# allowed when guarded by `if TYPE_CHECKING:`"), every architecture gate exempts
# such imports, and the core itself has ~626 functions whose signatures cannot
# be introspected at runtime for this reason.
#
# Wherever the framework calls `inspect.signature()` on a callable it does not
# own -- a controller endpoint, a migration script's `migrate()`, an addon's
# model `__init__`, an overridden `_read_group_fill_temporal` -- the default
# VALUE format turns "the author used the documented typing style" into a hard
# NameError.  Passing FORWARDREF degrades an unresolvable annotation to a
# ForwardRef and leaves concrete types (int, str, list[int]) untouched.

_CORE = pathlib.Path(__file__).resolve().parents[2]

# Call sites allowed to use the default VALUE format, with the reason.  Empty
# for now: every core call site inspects a callable it does not own.
VALUE_FORMAT_ALLOWED: dict[tuple[str, int], str] = {}


def _signature_call_sites() -> list[tuple[str, int, bool]]:
    sites: list[tuple[str, int, bool]] = []
    for path in sorted(_CORE.rglob("*.py")):
        rel = path.relative_to(_CORE).as_posix()
        if (
            rel.startswith("addons/")
            or "tests/" in rel
            or path.name.startswith("test_")
        ):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "signature"):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "inspect"):
                continue
            guarded = any(kw.arg == "annotation_format" for kw in node.keywords)
            sites.append((rel, node.lineno, guarded))
    return sites


def test_every_signature_call_site_is_forwardref_guarded():
    unguarded = [
        (rel, lineno)
        for rel, lineno, guarded in _signature_call_sites()
        if not guarded and (rel, lineno) not in VALUE_FORMAT_ALLOWED
    ]
    assert not unguarded, (
        f"inspect.signature() without annotation_format at {unguarded}. Under "
        f"PEP 649 this raises NameError when the inspected callable annotates a "
        f"parameter with a TYPE_CHECKING-only name -- the typing style this "
        f"fork's own ARCHITECTURE.md prescribes. Pass "
        f"annotation_format=annotationlib.Format.FORWARDREF, or add the site to "
        f"VALUE_FORMAT_ALLOWED with a reason it genuinely needs evaluated "
        f"annotations."
    )


def test_at_least_one_site_is_scanned():
    # Guard against the scan silently matching nothing (a vacuous pass).
    assert len(_signature_call_sites()) >= 5


def _make_callable(body: str):
    src = (
        "import typing\n"
        "if typing.TYPE_CHECKING:\n"
        "    from odoo.api import Environment\n"
        f"{body}\n"
    )
    ns: dict = {"__name__": "odoo.addons.probe.models.probe"}
    exec(compile(src, "<probe>", "exec"), ns)  # noqa: S102  fixture, not input
    return ns


def test_route_param_filter_survives_type_checking_annotation():
    from odoo.http.routing import _route_param_filter

    ns = _make_callable(
        "def endpoint(self, thing: Environment, limit: int = 10):\n    return thing"
    )
    accepts_kw, named, bound = _route_param_filter(ns["endpoint"])
    assert named == frozenset({"thing", "limit"})
    assert bound == "self"
    assert accepts_kw is False


def test_build_param_specs_leaves_unresolvable_annotation_uncoerced():
    from odoo.http._params import build_param_specs

    ns = _make_callable(
        "def endpoint(self, thing: Environment, limit: int = 10):\n    return thing"
    )
    specs = build_param_specs(ns["endpoint"])
    # The concrete annotation still coerces...
    assert specs["limit"].target is int
    # ...and the unresolvable one is skipped rather than exploding.
    assert "thing" not in specs


def test_model_with_type_checking_annotated_init_can_be_defined():
    ns = _make_callable(
        "from odoo import models\n"
        "class ProbeModel(models.Model):\n"
        "    _name = 'probe.model'\n"
        "    _register = False\n"
        "    def __init__(self, env: Environment, ids, prefetch_ids):\n"
        "        super().__init__(env, ids, prefetch_ids)"
    )
    assert ns["ProbeModel"]._name == "probe.model"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
