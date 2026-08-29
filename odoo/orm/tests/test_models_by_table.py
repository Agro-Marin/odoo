from odoo.orm.runtime._registry_models import _RegistryModelsMixin


class _Reg(_RegistryModelsMixin):
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
    assert _winner([(CHILD._name, CHILD), (ROOT._name, ROOT)]) == "ir.actions.actions"


def test_a_table_with_one_model_is_unaffected():
    solo = _model("res.partner", "res_partner")
    reg = _Reg({"res.partner": solo})
    assert reg.models_by_table["res_partner"]._name == "res.partner"


def test_models_without_a_table_are_skipped():
    abstract = type("mixin", (), {"_name": "mixin", "_table": None, "_inherit": []})
    reg = _Reg({"mixin": abstract})
    assert reg.models_by_table == {}
