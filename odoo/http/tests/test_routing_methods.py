from types import MappingProxyType

from odoo.http.routing import rule_routing_kwargs


class _Endpoint:
    def __init__(self, **routing):
        self.routing = MappingProxyType(routing)


def test_options_is_added_to_a_cors_less_route():
    kwargs = rule_routing_kwargs(_Endpoint(methods=("POST",), csrf=True))
    assert set(kwargs["methods"]) == {"POST", "OPTIONS"}


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
