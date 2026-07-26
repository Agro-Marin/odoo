"""Routing-map builds must not leak state between databases.

``ir.http.routing_map`` is an ``ormcache``, so one map is built and kept per
database from that database's installed-module set. Anything the build writes on
a decorated ``route_wrapper`` -- a single process-global object shared by every
database -- therefore leaks: the last build wins for all of them, and the
databases whose maps are still cached keep serving requests through it.

Run via ``pytest odoo/http/tests``.
"""

from types import ModuleType

import pytest

from odoo.http import _generate_routing_rules
from odoo.http.routing import route


def _install(monkeypatch, name, source):
    module = ModuleType(f"odoo.addons.{name}")
    monkeypatch.setitem(__import__("sys").modules, f"odoo.addons.{name}", module)
    exec(compile(source, f"<{name}>", "exec"), module.__dict__)  # noqa: S102
    return module


BASE = """
from odoo.http import Controller, route

class Base(Controller):
    @route("/x")
    def h(self, n: int = 0, vals: list[int] | None = None):
        return f"{n!r} {vals!r}"
"""

TYPED = """
from odoo.http import route
from odoo.addons.pb_base import Base

class Typed(Base):
    @route(typed=True)
    def h(self, n: int = 0, vals: list[int] | None = None):
        return super().h(n=n, vals=vals)
"""

PLAIN = """
from odoo.http import route
from odoo.addons.pb_base import Base

class Plain(Base):
    @route()
    def h(self, n: int = 0, vals: list[int] | None = None):
        return super().h(n=n, vals=vals)
"""


@pytest.fixture
def siblings(monkeypatch):
    """Two overrides of one base route, the typed one registered FIRST.

    Registration order is class-creation order, which in a real deployment is
    decided by whichever database's registry loads first. With the typed
    override first, both module sets resolve to the SAME leaf wrapper -- the
    shape under which the leak was observable.
    """
    _install(monkeypatch, "pb_base", BASE)
    _install(monkeypatch, "pb_typed", TYPED)
    _install(monkeypatch, "pb_plain", PLAIN)
    yield


def _build(mods):
    return dict(_generate_routing_rules(mods, nodb_only=False))


def test_typed_verdict_does_not_leak_between_builds(siblings):
    untyped_db = _build(["pb_base", "pb_plain"])
    typed_db = _build(["pb_base", "pb_typed", "pb_plain"])
    rebuilt = _build(["pb_base", "pb_plain"])

    assert typed_db["/x"]._param_specs
    assert untyped_db["/x"]._param_specs is None, (
        "a database with no typed route inherited coercion from another one"
    )
    assert rebuilt["/x"]._param_specs is None

    leaf = untyped_db["/x"].func.__func__
    assert leaf is typed_db["/x"].func.__func__, (
        "precondition: both builds must share the leaf wrapper"
    )
    assert not hasattr(leaf, "_param_specs")


def test_list_params_and_specs_come_from_the_same_build(siblings):
    """The two halves of ``typed=`` must never disagree.

    ``typed_list_params`` was already read from the per-build endpoint while
    ``_param_specs`` came from the shared wrapper, so a contaminated database
    coerced a ``list[...]`` parameter yet skipped the ``getlist`` re-read --
    silently keeping only the first of the repeated values.
    """
    for mods in (["pb_base", "pb_plain"], ["pb_base", "pb_typed", "pb_plain"]):
        endpoint = _build(mods)["/x"]
        assert bool(endpoint._param_specs) == (endpoint.typed_list_params is not None)


def test_wildcard_cors_with_credentials_is_refused():
    with pytest.raises(ValueError, match="cors_credentials"):

        @route("/y", cors="*", cors_credentials=True)
        def handler(self): ...


def test_named_origin_with_credentials_is_allowed():
    @route("/y", cors="https://app.example", cors_credentials=True)
    def handler(self): ...

    assert handler.original_routing["cors"] == "https://app.example"
