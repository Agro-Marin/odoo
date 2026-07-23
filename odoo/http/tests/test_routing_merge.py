"""DB-free unit tests for @route decoration and the inheritance merge.

Drives :func:`odoo.http.routing._generate_routing_rules` over controllers
registered by hand — no database — to pin how ``@route`` fragments merge across
an inheritance chain. Run via ``pytest odoo/http/tests``.
"""

import contextlib
import logging

import pytest

from odoo.http.controller import Controller
from odoo.http.routing import route


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate Controller.children_classes per test (it is process-global)."""
    saved = {k: list(v) for k, v in Controller.children_classes.items()}
    Controller.children_classes.clear()
    yield
    Controller.children_classes.clear()
    for k, v in saved.items():
        Controller.children_classes[k].extend(v)


def _merge(*mod_cls):
    from odoo.http.routing import _generate_routing_rules

    Controller.children_classes.clear()
    for mod, cls in mod_cls:
        Controller.children_classes[mod].append(cls)
    mods = [m for m, _ in mod_cls]
    with contextlib.suppress(Exception):
        logging.disable(logging.CRITICAL)
    result = {url: ep.routing for url, ep in _generate_routing_rules(mods, False)}
    logging.disable(logging.NOTSET)
    return result


def test_bearer_route_is_stateless_by_default():
    class C(Controller):
        @route("/a", type="json2", auth="bearer")
        def x(self):
            return {}

    C.__module__ = "odoo.addons.ma.controllers"
    (routing,) = _merge(("ma", C)).values()
    assert routing["auth"] == "bearer"
    assert routing["save_session"] is False


def test_bearer_overridden_to_user_regains_session_persistence():
    """Regression: overriding a bearer route to auth='user' used to keep the
    inherited ``save_session=False`` and silently never persist the cookie."""

    class Parent(Controller):
        @route("/b", type="json2", auth="bearer")
        def x(self):
            return {}

    Parent.__module__ = "odoo.addons.ma.controllers"

    class Child(Parent):
        @route(auth="user")
        def x(self):
            return super().x()

    Child.__module__ = "odoo.addons.mb.controllers"

    for routing in _merge(("ma", Parent), ("mb", Child)).values():
        assert routing["auth"] == "user"
        assert routing["save_session"] is True


def test_explicit_save_session_false_is_preserved():
    class C(Controller):
        @route("/c", type="http", auth="user", save_session=False)
        def x(self):
            return None

    C.__module__ = "odoo.addons.ma.controllers"
    (routing,) = _merge(("ma", C)).values()
    assert routing["auth"] == "user"
    assert routing["save_session"] is False


def test_explicit_save_session_true_on_bearer_is_preserved():
    class C(Controller):
        @route("/d", type="json2", auth="bearer", save_session=True)
        def x(self):
            return {}

    C.__module__ = "odoo.addons.ma.controllers"
    (routing,) = _merge(("ma", C)).values()
    assert routing["save_session"] is True


def test_plain_user_route_persists_session():
    class C(Controller):
        @route("/e", type="http", auth="user")
        def x(self):
            return None

    C.__module__ = "odoo.addons.ma.controllers"
    (routing,) = _merge(("ma", C)).values()
    assert routing["save_session"] is True


def test_merge_never_mutates_declared_fragments():
    """Regression: the merge used to write its ``type``/``readonly`` corrections
    back into ``original_routing``, leaking one build's context into every later
    build (maps are rebuilt per database with different module sets)."""

    class Parent(Controller):
        @route("/m", type="http", auth="user")
        def x(self):
            return None

    Parent.__module__ = "odoo.addons.ma.controllers"

    class Child(Parent):
        @route(type="jsonrpc", readonly=True)  # both conflict with the parent
        def x(self):
            return super().x()

    Child.__module__ = "odoo.addons.mb.controllers"

    parent_decl = dict(Parent.__dict__["x"].original_routing)
    child_decl = dict(Child.__dict__["x"].original_routing)

    for routing in _merge(("ma", Parent), ("mb", Child)).values():
        assert routing["type"] == "http"  # conflicting override loses
        assert routing["readonly"] is False  # conflicting flip forced RW

    # The declarations survive the merge untouched...
    assert dict(Parent.__dict__["x"].original_routing) == parent_decl
    assert dict(Child.__dict__["x"].original_routing) == child_decl
    assert child_decl["type"] == "jsonrpc"
    assert child_decl["readonly"] is True
    # ...while the resolved type is stamped on the wrapper function itself,
    # where route_wrapper reads it at dispatch time (deterministic, so
    # re-stamping across builds is idempotent).
    assert Parent.__dict__["x"]._merged_route_type == "http"
    assert Child.__dict__["x"]._merged_route_type == "http"

    # ...so a rebuild replays identically (order-independent outcome).
    for routing in _merge(("ma", Parent), ("mb", Child)).values():
        assert routing["type"] == "http"
        assert routing["readonly"] is False
    assert dict(Child.__dict__["x"].original_routing) == child_decl


def test_options_added_to_methods_allow_list():
    from odoo.http.routing import rule_routing_kwargs

    def endpoint(self): ...

    endpoint.routing = {"methods": ["GET"], "cors": "*"}
    kwargs = rule_routing_kwargs(endpoint)
    assert "OPTIONS" in kwargs["methods"]


def test_unknown_route_parameter_warns(caplog):
    """A typo'd @route kwarg (``raedonly=True``) used to be silently stored in
    endpoint.routing and ignored; it must draw a warning at decoration."""
    import logging

    from odoo.http.routing import register_routing_parameters, route

    with caplog.at_level(logging.WARNING, logger="odoo.http.routing"):

        @route("/probe/unknown-kwarg", type="http", auth="none", raedonly=True)
        def endpoint(self):
            return ""

    assert any(
        "unknown @route parameter" in rec.message and "raedonly" in str(rec.args)
        for rec in caplog.records
    )

    # A declared extension key is accepted silently.
    register_routing_parameters("probe_extension_key")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="odoo.http.routing"):

        @route("/probe/known-kwarg", type="http", auth="none", probe_extension_key=1)
        def endpoint2(self):
            return ""

    assert not caplog.records
