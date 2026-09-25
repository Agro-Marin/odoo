import types
import unittest

from odoo.modules import loading


def _package(name, db_version, code_version, state="installed"):
    return types.SimpleNamespace(
        name=name,
        state=state,
        db_version=db_version,
        manifest={"version": code_version},
    )


def _field(*, store=True, column_type=("varchar", "varchar"), manual=False):
    return types.SimpleNamespace(store=store, column_type=column_type, manual=manual)


def _model(table, fields, *, abstract=False, table_query=None, auto=True):
    return types.SimpleNamespace(
        _table=table,
        _fields=fields,
        _abstract=abstract,
        _table_query=table_query,
        _auto=auto,
    )


class _Cursor:
    def __init__(self, columns):
        self.columns = columns

    def execute(self, query, params=None):
        self.tables = set(params[0])

    def fetchall(self):
        return [(t, c) for t, c in self.columns if t in self.tables]


def _loader(packages, models, columns, *, update_module=False):
    return types.SimpleNamespace(
        update_module=update_module,
        graph=packages,
        registry=types.SimpleNamespace(models=models),
        cr=_Cursor(columns),
    )


class TestCodeAheadOfDatabase(unittest.TestCase):
    def _run(self, loader):
        with self.assertLogs(loading._logger, "WARNING") as logs:
            loading._logger.warning("sentinel")
            loading._ModuleLoader.warn_code_ahead_of_database(loader)
        return [record.getMessage() for record in logs.records[1:]]

    def test_a_matching_database_says_nothing(self):
        loader = _loader(
            [_package("base", "19.0.1.110", "1.110")],
            {"res.country": _model("res_country", {"id": _field(), "name": _field()})},
            [("res_country", "id"), ("res_country", "name")],
        )
        self.assertEqual(self._run(loader), [])

    def test_a_module_behind_its_code_is_named_with_its_upgrade(self):
        loader = _loader(
            [
                _package("base", "19.0.1.107", "1.110"),
                _package("web", "19.0.2.5", "2.5"),
            ],
            {},
            [],
        )
        [message] = self._run(loader)
        self.assertIn("base 19.0.1.107 < 19.0.1.110", message)
        self.assertIn("-u base", message)
        self.assertNotIn("web", message)

    def test_a_stored_field_without_its_column_is_named(self):
        loader = _loader(
            [],
            {
                "res.device": _model(
                    "res_device",
                    {
                        "id": _field(),
                        "totp_device_id": _field(),
                        "display_name": _field(store=False),
                        "x_manual": _field(manual=True),
                    },
                ),
                "report.view": _model(
                    "report_view", {"x": _field()}, table_query="SELECT 1"
                ),
            },
            [("res_device", "id")],
        )
        [message] = self._run(loader)
        self.assertIn("res_device.totp_device_id", message)
        self.assertNotIn("display_name", message)
        self.assertNotIn("x_manual", message)
        self.assertNotIn("report_view", message)

    def test_an_upgrade_run_does_not_check(self):
        loader = _loader(
            [_package("base", "19.0.1.0", "1.110")], {}, [], update_module=True
        )
        self.assertEqual(self._run(loader), [])
