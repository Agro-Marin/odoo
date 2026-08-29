import collections
import sys
from types import ModuleType

import pytest

from odoo.http import _generate_routing_rules

DIAMOND = """
from odoo.http import Controller, route

class Left(Controller):
    @route("/diamond/left", auth="none")
    def left(self):
        return "left"

class Right(Controller):
    @route("/diamond/right", auth="none")
    def right(self):
        return "right"
"""

LEAF = """
from odoo.http import route
from odoo.addons.rd_sides import Left, Right

class Both(Left, Right):
    @route("/diamond/both", auth="none")
    def both(self):
        return "both"
"""

OVERLAP = """
from odoo.http import Controller, route

class Left(Controller):
    @route("/ov/left", auth="none")
    def left(self):
        return "left"

class Right(Controller):
    @route("/ov/right", auth="none")
    def right(self):
        return "right"
"""

OVERLAP_LEAVES = """
from odoo.http import route
from odoo.addons.rd_ov import Left, Right

class OnlyLeft(Left):
    @route("/ov/only-left", auth="none")
    def only_left(self):
        return "only-left"

class Shared(Left, Right):
    @route("/ov/shared", auth="none")
    def shared(self):
        return "shared"
"""

CHAIN = """
from odoo.http import Controller, route

class Parent(Controller):
    @route("/chain/parent", auth="none")
    def parent(self):
        return "parent"

class Child(Parent):
    @route()
    def parent(self):
        return "child"
"""


def _install(monkeypatch, name, source):
    module = ModuleType(f"odoo.addons.{name}")
    monkeypatch.setitem(sys.modules, f"odoo.addons.{name}", module)
    exec(compile(source, f"<{name}>", "exec"), module.__dict__)  # noqa: S102  the source is this file's own fixture, not input
    return module


@pytest.fixture
def diamond(monkeypatch):
    _install(monkeypatch, "rd_sides", DIAMOND)
    _install(monkeypatch, "rd_leaf", LEAF)
    yield


@pytest.fixture
def overlap(monkeypatch):
    _install(monkeypatch, "rd_ov", OVERLAP)
    _install(monkeypatch, "rd_ov_leaves", OVERLAP_LEAVES)
    yield


@pytest.fixture
def chain(monkeypatch):
    _install(monkeypatch, "rd_chain", CHAIN)
    yield


def _cls(name):
    return type(name, (), {})


def _urls(mods):
    return collections.Counter(url for url, _ in _generate_routing_rules(mods, False))


def test_a_diamond_leaf_yields_each_route_once(diamond):
    urls = _urls(["rd_sides", "rd_leaf"])
    assert urls == {
        "/diamond/left": 1,
        "/diamond/right": 1,
        "/diamond/both": 1,
    }


def test_the_diamond_leafs_own_route_is_still_reachable(diamond):
    endpoints = dict(_generate_routing_rules(["rd_sides", "rd_leaf"], False))
    assert endpoints["/diamond/both"].routing["auth"] == "none"


def test_a_diamond_without_its_leaf_installed_keeps_both_sides(diamond):
    assert _urls(["rd_sides"]) == {"/diamond/left": 1, "/diamond/right": 1}


def test_a_plain_override_chain_is_unaffected(chain):
    urls = _urls(["rd_chain"])
    assert urls == {"/chain/parent": 1}


def test_an_override_chain_still_resolves_to_the_child(chain):
    endpoints = dict(_generate_routing_rules(["rd_chain"], False))
    endpoint = endpoints["/chain/parent"]
    assert endpoint.func.__self__.parent().get_data() == b"child"


def test_overlapping_leaf_sets_are_fused_into_one_tree(overlap):
    assert _urls(["rd_ov", "rd_ov_leaves"]) == {
        "/ov/left": 1,
        "/ov/right": 1,
        "/ov/only-left": 1,
        "/ov/shared": 1,
    }


def test_the_fused_tree_carries_every_leaf(overlap):
    from odoo.http.routing import _get_controllers

    controllers = list(_get_controllers(["rd_ov", "rd_ov_leaves"]))
    assert len(controllers) == 1
    mro_names = {cls.__name__ for cls in type(controllers[0]).mro()}
    assert {"OnlyLeft", "Shared", "Left", "Right"} <= mro_names


def test_fusion_is_transitive():
    from odoo.http.routing import _group_controller_trees

    A = _cls("A")
    B = _cls("B")
    C = _cls("C")
    L1 = _cls("L1")
    L2 = _cls("L2")
    L3 = _cls("L3")

    grouped = _group_controller_trees([(A, [L1, L2]), (C, [L3]), (B, [L2, L3])])
    assert len(grouped) == 1
    top, leaves = grouped[0]
    assert top is A
    assert set(leaves) == {L1, L2, L3}


def test_unrelated_trees_stay_apart():
    from odoo.http.routing import _group_controller_trees

    A = _cls("A")
    B = _cls("B")
    L1 = _cls("L1")
    L2 = _cls("L2")

    grouped = _group_controller_trees([(A, [L1]), (B, [L2])])
    assert [(top, list(leaves)) for top, leaves in grouped] == [(A, [L1]), (B, [L2])]


def test_a_tree_with_no_leaf_contributes_nothing():
    from odoo.http.routing import _group_controller_trees

    A = _cls("A")
    L1 = _cls("L1")

    assert _group_controller_trees([(A, []), (A, [L1])]) == [(A, [L1])]


def test_leaf_order_survives_fusion():
    from odoo.http.routing import _group_controller_trees

    A = _cls("A")
    B = _cls("B")
    L1 = _cls("L1")
    L2 = _cls("L2")
    L3 = _cls("L3")

    grouped = _group_controller_trees([(A, [L1, L2]), (B, [L2, L3])])
    assert grouped == [(A, [L1, L2, L3])]
