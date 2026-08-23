"""The two maps the framework serves from are assembled by one function.

``Application.nodb_routing_map`` and ``ir.http.routing_map`` used to each spell
the same four steps: a ``Map(strict_slashes=False)``, a :class:`FasterRule` per
pair, ``rule_routing_kwargs`` for the rule's own keywords, and
``rule.merge_slashes = False``. The last one is the trap -- it is a *per-rule*
flag that werkzeug defaults to ``True``, opposite in sign to the ``Map``
keyword right above it, so a third caller reads ``strict_slashes=False`` and
has no reason to look for it.
"""

import werkzeug.routing

from odoo.http import build_routing_map
from odoo.http.routing import FasterRule


class _Endpoint:
    """A callable carrying ``.routing`` — the shape ``build_routing_map`` reads."""

    def __init__(self, url, **routing):
        self.url = url
        self.routing = {"routes": [url], "type": "http", **routing}

    def __call__(self):
        return self.url


def _endpoint(url, **routing):
    return _Endpoint(url, **routing)


def test_slash_handling_is_the_same_for_every_rule():
    routing_map = build_routing_map(
        [("/a", _endpoint("/a")), ("/b/<x>", _endpoint("/b/<x>"))]
    )
    assert routing_map.strict_slashes is False
    rules = list(routing_map.iter_rules())
    assert len(rules) == 2
    assert all(isinstance(rule, FasterRule) for rule in rules)
    assert all(rule.merge_slashes is False for rule in rules)


def test_a_double_slash_is_not_collapsed_into_a_match():
    routing_map = build_routing_map([("/a/b", _endpoint("/a/b"))])
    adapter = routing_map.bind("example.com")
    assert adapter.match("/a/b")[0]() == "/a/b"
    assert not routing_map.bind("example.com").test("/a//b")


def test_declared_methods_are_widened_to_let_options_through():
    routing_map = build_routing_map(
        [("/a", _endpoint("/a", methods=("POST",)))],
    )
    rule = next(iter(routing_map.iter_rules()))
    assert rule.methods == {"POST", "OPTIONS"}


def test_converters_are_handed_to_the_map():
    class Shouty(werkzeug.routing.BaseConverter):
        regex = r"[A-Z]+"

    routing_map = build_routing_map(
        [("/a/<shouty:x>", _endpoint("/a/<shouty:x>"))],
        converters={"shouty": Shouty},
    )
    adapter = routing_map.bind("example.com")
    assert adapter.match("/a/LOUD")[1] == {"x": "LOUD"}
    assert not adapter.test("/a/quiet")


def test_an_empty_rule_set_still_builds_a_usable_map():
    routing_map = build_routing_map([])
    assert list(routing_map.iter_rules()) == []
