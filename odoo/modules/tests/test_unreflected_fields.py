import types
import unittest

from odoo.modules import loading
from odoo.tools import OrderedSet


def _field(*, store=True, manual=False):
    return types.SimpleNamespace(
        store=store, column_type=("varchar", "varchar"), manual=manual
    )


def _model(table, fields):
    return types.SimpleNamespace(
        _table=table, _fields=fields, _abstract=False, _table_query=None, _auto=True
    )


class _Cursor:
    sql_log_count = 0

    def __init__(self, reflected, columns):
        self.reflected = reflected
        self.columns = columns
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append(query)
        self.last = query
        if params:
            self.tables = set(params[0])

    def fetchall(self):
        if "ir_model_fields" in self.last:
            return [(model, list(names)) for model, names in self.reflected.items()]
        return [(t, c) for t, c in self.columns if t in self.tables]


def _loader(models, reflected, columns, update_module):
    return types.SimpleNamespace(
        update_module=update_module,
        registry=types.SimpleNamespace(models=models),
        cr=_Cursor(reflected, columns),
        models_to_check=OrderedSet(),
    )


def _collect(models, reflected, columns, *, update_module=True):
    loader = _loader(models, reflected, columns, update_module)
    loading._ModuleLoader.collect_models_with_unreflected_fields(loader)
    return loader


class TestCollectModelsWithUnreflectedFields(unittest.TestCase):
    def test_a_model_whose_field_has_no_row_is_queued(self):
        loader = _collect(
            {"probe.thing": _model("probe_thing", {"id": _field(), "b": _field()})},
            {"probe.thing": ["id"]},
            [("probe_thing", "id"), ("probe_thing", "b")],
        )
        self.assertEqual(list(loader.models_to_check), ["probe.thing"])

    def test_a_stored_field_without_its_column_is_queued(self):
        loader = _collect(
            {"probe.thing": _model("probe_thing", {"id": _field(), "b": _field()})},
            {"probe.thing": ["id", "b"]},
            [("probe_thing", "id")],
        )
        self.assertEqual(list(loader.models_to_check), ["probe.thing"])

    def test_a_reflected_model_and_a_manual_field_queue_nothing(self):
        loader = _collect(
            {
                "probe.thing": _model(
                    "probe_thing", {"id": _field(), "x_custom": _field(manual=True)}
                )
            },
            {"probe.thing": ["id"]},
            [("probe_thing", "id")],
        )
        self.assertEqual(list(loader.models_to_check), [])

    def test_a_plain_load_does_not_look(self):
        loader = _collect(
            {"probe.thing": _model("probe_thing", {"id": _field()})},
            {},
            [],
            update_module=False,
        )
        self.assertEqual(loader.cr.queries, [])
        self.assertEqual(list(loader.models_to_check), [])
