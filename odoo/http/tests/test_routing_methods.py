"""DB-free tests for the werkzeug ``methods`` allow-list built by
:func:`odoo.http.routing.rule_routing_kwargs`.

The allow-list is what makes ``@route(methods=[...])`` an actual restriction, so
these pin exactly which verbs the framework adds on the author's behalf. Run via
``pytest odoo/http/tests``.
"""

from types import MappingProxyType

from odoo.http.routing import rule_routing_kwargs


class _Endpoint:
    """Minimal stand-in for the ``functools.partial`` endpoints the routing map
    holds: all ``rule_routing_kwargs`` reads is ``.routing``."""

    def __init__(self, **routing):
        self.routing = MappingProxyType(routing)


def test_options_is_not_added_to_a_cors_less_route():
    """A ``methods=`` allow-list without ``cors`` must stay exactly as declared.

    Regression: OPTIONS used to be appended to *every* restricted route. Nothing
    short-circuits an OPTIONS request on a CORS-less route (only
    ``Dispatcher.pre_dispatch``'s 204 preflight does, and it requires ``cors``),
    so the verb reached the endpoint — and since OPTIONS is a
    ``SAFE_HTTP_METHODS`` member, CSRF validation was skipped on the way there.
    A ``@route(methods=["POST"], csrf=True)`` handler therefore executed for
    ``OPTIONS /path?injected=1``.
    """
    kwargs = rule_routing_kwargs(_Endpoint(methods=("POST",), csrf=True))
    assert kwargs["methods"] == ("POST",)


def test_options_is_added_to_a_cors_route():
    kwargs = rule_routing_kwargs(_Endpoint(methods=("POST",), cors="*"))
    assert set(kwargs["methods"]) == {"POST", "OPTIONS"}


def test_explicitly_declared_options_is_preserved():
    kwargs = rule_routing_kwargs(_Endpoint(methods=("POST", "OPTIONS"), cors="*"))
    assert list(kwargs["methods"]).count("OPTIONS") == 1


def test_no_allow_list_is_left_alone():
    assert "methods" not in rule_routing_kwargs(_Endpoint(cors="*"))


def test_declared_methods_are_not_mutated_in_place():
    declared = ["POST"]
    endpoint = _Endpoint(methods=declared, cors="*")
    rule_routing_kwargs(endpoint)
    rule_routing_kwargs(endpoint)
    assert declared == ["POST"]
