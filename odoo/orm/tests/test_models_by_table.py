"""`models_by_table` must pick the root model, not whichever loaded first.

A table is not owned by exactly one model: `ir.actions.actions` and
`ir.actions.act_window_close` both declare `_table = "ir_actions"`. The index
still answers with one model because its consumer wants one -- it names a model
when turning a constraint violation into a user-facing message -- so the
tie-break has to be stated instead of falling out of dict insertion order.

These tests build the collision in BOTH orders. Under the old `setdefault` the
second ordering returned the child; the point of the rule is that ordering stops
mattering.
"""

from odoo.orm.runtime._registry_models import _RegistryModelsMixin


class _Reg(_RegistryModelsMixin):
    """Just enough registry to exercise the index.

    `cached_property` needs a real `__dict__`, which the mixin's `__slots__`
    would otherwise deny.
    """

    def __init__(self, models):
        self.models = models


def _model(name, table, inherit=()):
    return type(name, (), {"_name": name, "_table": table, "_inherit": list(inherit)})


ROOT = _model("ir.actions.actions", "ir_actions")
CHILD = _model("ir.actions.act_window_close", "ir_actions", ["ir.actions.actions"])


def _winner(pairs):
    return _Reg(dict(pairs)).models_by_table["ir_actions"]._name


def test_root_wins_when_it_is_registered_first():
    assert _winner([(ROOT._name, ROOT), (CHILD._name, CHILD)]) == "ir.actions.actions"


def test_root_wins_when_the_child_is_registered_first():
    """The ordering that the old `setdefault` got wrong."""
    assert _winner([(CHILD._name, CHILD), (ROOT._name, ROOT)]) == "ir.actions.actions"


def test_a_table_with_one_model_is_unaffected():
    solo = _model("res.partner", "res_partner")
    reg = _Reg({"res.partner": solo})
    assert reg.models_by_table["res_partner"]._name == "res.partner"


def test_models_without_a_table_are_skipped():
    abstract = type("mixin", (), {"_name": "mixin", "_table": None, "_inherit": []})
    reg = _Reg({"mixin": abstract})
    assert reg.models_by_table == {}
