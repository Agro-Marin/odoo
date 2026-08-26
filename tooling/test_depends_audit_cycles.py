from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import depends_audit


class _Field:
    def __init__(self, name, *, compute=None, comodel=None, store=False, readonly=True):
        self.name = name
        self.compute = compute
        self.related = None
        self.comodel_name = comodel
        self.relational = comodel is not None
        self.store = store
        self.readonly = readonly


class _Model:
    def __init__(self, name, fields):
        self._name = name
        self._fields = fields


class _Registry:
    def __init__(self, field_depends):
        self.field_depends = field_depends


class _Env:
    def __init__(self, models, field_depends):
        self._models = models
        self.registry = _Registry(field_depends)

    def __getitem__(self, name):
        return self._models[name]

    def get(self, name):
        return self._models.get(name)


def _cyclic_env():
    a_x = _Field("x", compute="_compute_x")
    a_peer = _Field("peer", comodel="b")
    b_y = _Field("y", compute="_compute_y")
    b_peer = _Field("peer", comodel="a")
    a = _Model("a", {"x": a_x, "peer": a_peer})
    b = _Model("b", {"y": b_y, "peer": b_peer})
    depends = {a_x: ("peer.y",), b_y: ("peer.x",)}
    return _Env({"a": a, "b": b}, depends), a


def test_a_dependency_cycle_terminates_instead_of_recursing():
    env, model = _cyclic_env()
    assert depends_audit._read_is_safe(env, model, "peer.y", ()) is False


def test_the_guard_does_not_fire_on_a_diamond():
    leaf = _Field("leaf", compute=None, store=True, readonly=False)
    left = _Field("left", compute="_compute_left")
    right = _Field("right", compute="_compute_right")
    top = _Field("top", compute="_compute_top")
    model = _Model("m", {"leaf": leaf, "left": left, "right": right, "top": top})
    depends = {top: ("left", "right"), left: ("leaf",), right: ("leaf",)}
    env = _Env({"m": model}, depends)
    assert depends_audit._read_is_safe(env, model, "top", ("leaf",)) is True


@pytest.mark.parametrize("depth", [5, 50, 400])
def test_a_long_chain_does_not_exhaust_the_stack(depth):
    fields = {}
    depends = {}
    for i in range(depth):
        fields[f"f{i}"] = _Field(f"f{i}", compute=f"_compute_f{i}")
    for i in range(depth - 1):
        depends[fields[f"f{i}"]] = (f"f{i + 1}",)
    depends[fields[f"f{depth - 1}"]] = ()
    model = _Model("m", fields)
    env = _Env({"m": model}, depends)
    assert depends_audit._read_is_safe(env, model, "f0", ()) is False
