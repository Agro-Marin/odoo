"""The cycle guard in `depends_audit._read_is_safe`, which did not guard.

`_read_is_safe` walks a compute's declared dependencies through the registry to
decide whether a read is covered. Its guard keyed on `(model, field, prefix)` --
and `prefix` GROWS by one segment on every recursion, so a field revisited one
hop deeper got a fresh key, the guard never fired, and the walk ran until the
interpreter stopped it:

    RecursionError: maximum recursion depth exceeded

on a registry no larger than `loyalty` and its dependencies. The tool crashed
for anyone who ran it as its own commit message describes.

No database here: the walk only needs `_fields`, `_name` and
`registry.field_depends`, so a pair of stub models reproduces the cycle exactly
and costs nothing.
"""

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
        # `_comodel` reaches the comodel with `env.get(...)`, not `env[...]`.
        return self._models.get(name)


def _cyclic_env():
    """`a.x` depends on `peer.y`, `b.y` depends on `peer.x`. A two-node cycle."""
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
    # Before the fix this raised RecursionError rather than answering.
    assert depends_audit._read_is_safe(env, model, "peer.y", ()) is False


def test_the_guard_does_not_fire_on_a_diamond():
    """A field reached twice down two different branches is not a cycle.

    The guard is an on-stack marker for exactly this reason: a visited-set would
    answer False for the second branch and invent a finding.
    """
    leaf = _Field("leaf", compute=None, store=True, readonly=False)
    left = _Field("left", compute="_compute_left")
    right = _Field("right", compute="_compute_right")
    top = _Field("top", compute="_compute_top")
    model = _Model("m", {"leaf": leaf, "left": left, "right": right, "top": top})
    depends = {top: ("left", "right"), left: ("leaf",), right: ("leaf",)}
    env = _Env({"m": model}, depends)
    # `leaf` is declared, so both branches are covered and the answer is True --
    # which it cannot be if reaching `leaf` twice counted as a cycle.
    assert depends_audit._read_is_safe(env, model, "top", ("leaf",)) is True


@pytest.mark.parametrize("depth", [5, 50, 400])
def test_a_long_chain_does_not_exhaust_the_stack(depth):
    """Depth alone, kept separate from the cycle.

    This one passes on the OLD guard too -- a linear chain terminates whatever
    the key is -- and is here to say so: the defect was cycles specifically, not
    depth, and a test that failed for both would not have told them apart.
    """
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
