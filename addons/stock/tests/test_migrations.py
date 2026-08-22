from unittest.mock import MagicMock, patch

from odoo.modules.module import get_module_path, load_script
from odoo.tests import BaseCase


class MigrationScriptMixin:
    allow_inherited_tests_method = True

    script_version = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module_path = get_module_path("stock")
        cls.script = load_script(
            f"{module_path}/migrations/{cls.script_version}/pre-migrate.py",
            f"stock_{cls.script_version.replace('.', '_')}_pre_migrate",
        )

    def patch_column_exists(self, existing_columns):
        def fake_column_exists(cr, table, column):
            try:
                return existing_columns[(table, column)]
            except KeyError:
                raise AssertionError(
                    f"unexpected column check: {table}.{column}"
                ) from None

        return patch.object(self.script, "column_exists", fake_column_exists)

    def statements(self, cr, keyword):
        return [
            call.args[0]
            for call in cr.execute.call_args_list
            if keyword in call.args[0]
        ]

    def test_fresh_install_is_noop(self):
        cr = MagicMock()
        self.script.migrate(cr, None)
        cr.execute.assert_not_called()


class TestStock12PreMigrate(MigrationScriptMixin, BaseCase):
    script_version = "1.2"
    expected_updates = 13

    def _patch_horizon_days(self, udt_name):
        return patch.object(
            self.script,
            "table_columns",
            return_value={"horizon_days": {"udt_name": udt_name}},
        )

    def test_migrate_is_idempotent(self):
        cr = MagicMock()
        with self._patch_horizon_days("int4"):
            self.script.migrate(cr, "1.1")
        self.assertEqual(self.statements(cr, "ALTER"), [])
        self.assertEqual(len(self.statements(cr, "UPDATE")), self.expected_updates)

    def test_migrate_converts_float_horizon_days(self):
        cr = MagicMock()
        with self._patch_horizon_days("float8"):
            self.script.migrate(cr, "1.1")
        alter_statements = self.statements(cr, "ALTER")
        self.assertEqual(len(alter_statements), 1)
        self.assertIn("horizon_days", alter_statements[0])


class TestStock13PreMigrate(MigrationScriptMixin, BaseCase):
    script_version = "1.3"
    expected_updates = 3

    def _columns(self, *, renamed):
        return {
            ("stock_move", "product_uom"): not renamed,
            ("stock_move", "product_uom_id"): renamed,
        }

    def test_migrate_is_idempotent(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=True)):
            self.script.migrate(cr, "1.2")
        self.assertEqual(self.statements(cr, "ALTER TABLE"), [])
        self.assertEqual(len(self.statements(cr, "UPDATE")), self.expected_updates)

    def test_migrate_renames_column_when_pending(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=False)):
            self.script.migrate(cr, "1.2")
        alter_statements = self.statements(cr, "ALTER TABLE")
        self.assertEqual(len(alter_statements), 1)
        self.assertIn("product_uom_id", alter_statements[0])


class TestStock14PreMigrate(MigrationScriptMixin, BaseCase):
    script_version = "1.4"
    expected_updates = 4

    def _columns(self, *, renamed):
        return {
            ("stock_move", "packaging_uom_qty"): not renamed,
            ("stock_move", "quantity_packaging_uom"): renamed,
        }

    def test_migrate_is_idempotent(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=True)):
            self.script.migrate(cr, "1.3")
        self.assertEqual(self.statements(cr, "ALTER TABLE"), [])
        self.assertEqual(len(self.statements(cr, "UPDATE")), self.expected_updates)

    def test_migrate_renames_column_when_pending(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=False)):
            self.script.migrate(cr, "1.3")
        alter_statements = self.statements(cr, "ALTER TABLE")
        self.assertEqual(len(alter_statements), 1)
        self.assertIn("quantity_packaging_uom", alter_statements[0])


class TestStock15PreMigrate(MigrationScriptMixin, BaseCase):
    script_version = "1.5"
    expected_updates = 16

    def _columns(self, *, renamed):
        return {
            ("stock_picking", "scheduled_date"): not renamed,
            ("stock_picking", "date_planned"): renamed,
            ("stock_move", "delay_alert_date"): not renamed,
            ("stock_move", "date_delay_alert"): renamed,
            ("stock_move", "reservation_date"): not renamed,
            ("stock_move", "date_reservation"): renamed,
        }

    def test_migrate_is_idempotent(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=True)):
            self.script.migrate(cr, "1.4")
        self.assertEqual(self.statements(cr, "ALTER TABLE"), [])
        self.assertEqual(len(self.statements(cr, "UPDATE")), self.expected_updates)

    def test_migrate_renames_columns_when_pending(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=False)):
            self.script.migrate(cr, "1.4")
        alter_statements = self.statements(cr, "ALTER TABLE")
        self.assertEqual(len(alter_statements), 3)
        for new_column in ("date_planned", "date_delay_alert", "date_reservation"):
            self.assertTrue(
                any(new_column in statement for statement in alter_statements),
                f"missing column rename to {new_column}",
            )

    def test_ambiguous_tokens_are_model_scoped(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=True)):
            self.script.migrate(cr, "1.4")
        for token in ("scheduled_date", "delivery_count", "virtual_available"):
            token_statements = self.statements(cr, token)
            self.assertTrue(token_statements, f"no rewrite issued for {token}")
            for statement in token_statements:
                self.assertIn(
                    "ANY(%s)",
                    statement,
                    f"rewrite of ambiguous token {token} must be model-scoped",
                )
                self.assertNotIn(
                    "ir_act_server",
                    statement,
                    f"ambiguous token {token} must not be rewritten in "
                    "server-action code",
                )

    def test_global_tokens_swept_in_server_actions(self):
        cr = MagicMock()
        with self.patch_column_exists(self._columns(renamed=True)):
            self.script.migrate(cr, "1.4")
        server_action_statements = self.statements(cr, "ir_act_server")
        self.assertEqual(len(server_action_statements), 1)
        for old in (
            "delay_alert_date",
            "reservation_date",
            "forecast_expected_date",
            "packages_count",
        ):
            self.assertIn(old, server_action_statements[0])
