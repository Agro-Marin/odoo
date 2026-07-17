from unittest.mock import MagicMock, patch

from odoo.modules.module import get_module_path, load_script
from odoo.tests import BaseCase


class MigrationScriptMixin:
    """Shared harness for the ``stock/migrations/*/pre-migrate.py`` scripts.

    Each script is loaded directly via :func:`~odoo.modules.module.load_script`
    (the same loader Odoo itself uses) with a mocked cursor — no registry/DB
    needed, since the script's own SQL is what's under test, not its execution
    against real data.

    Concrete classes set :attr:`script_version` (the migrations subdirectory)
    and must patch the ``odoo.tools.sql`` helpers the script imports
    (``column_exists`` / ``table_columns``) before calling ``migrate`` with a
    truthy version, so the mocked cursor never reaches those helpers' SQL.
    """

    # Odoo's test loader only collects methods from the class __dict__;
    # opt in so the shared tests defined on this mixin run on every subclass.
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
        """Patch ``column_exists`` as imported into the migration module.

        :param dict existing_columns: ``{(table, column): bool}`` — any lookup
            not in the mapping is a test bug and raises
        :return: context manager patching the migration module's reference
        """

        def fake_column_exists(cr, table, column):
            try:
                return existing_columns[(table, column)]
            except KeyError:
                raise AssertionError(
                    f"unexpected column check: {table}.{column}"
                ) from None

        return patch.object(self.script, "column_exists", fake_column_exists)

    def statements(self, cr, keyword):
        """Return the SQL strings passed to ``cr.execute`` containing ``keyword``.

        :param cr: the mocked cursor
        :param str keyword: substring to filter the executed statements on
        :rtype: list[str]
        """
        return [
            call.args[0]
            for call in cr.execute.call_args_list
            if keyword in call.args[0]
        ]

    def test_fresh_install_is_noop(self):
        """A falsy ``version`` (fresh install) must not touch the cursor."""
        cr = MagicMock()
        self.script.migrate(cr, None)
        cr.execute.assert_not_called()


class TestStock12PreMigrate(MigrationScriptMixin, BaseCase):
    """Unit tests for ``stock/migrations/1.2/pre-migrate.py``."""

    script_version = "1.2"
    # 9 view sweeps (4 method + 5 field renames) + 4 server-action sweeps.
    expected_updates = 13

    def _patch_horizon_days(self, udt_name):
        """Patch ``table_columns`` so ``res_company.horizon_days`` reports the
        given Postgres type (``int4`` = already converted)."""
        return patch.object(
            self.script,
            "table_columns",
            return_value={"horizon_days": {"udt_name": udt_name}},
        )

    def test_migrate_is_idempotent(self):
        """A re-run against an already-converted column must skip the
        ``ALTER COLUMN`` table rewrite; the text sweeps are naturally
        idempotent (no matches, no-op)."""
        cr = MagicMock()
        with self._patch_horizon_days("int4"):
            self.script.migrate(cr, "1.1")
        self.assertEqual(self.statements(cr, "ALTER"), [])
        self.assertEqual(len(self.statements(cr, "UPDATE")), self.expected_updates)

    def test_migrate_converts_float_horizon_days(self):
        """A pre-rename float column must be converted exactly once."""
        cr = MagicMock()
        with self._patch_horizon_days("float8"):
            self.script.migrate(cr, "1.1")
        alter_statements = self.statements(cr, "ALTER")
        self.assertEqual(len(alter_statements), 1)
        self.assertIn("horizon_days", alter_statements[0])


class TestStock13PreMigrate(MigrationScriptMixin, BaseCase):
    """Unit tests for ``stock/migrations/1.3/pre-migrate.py``."""

    script_version = "1.3"
    # One sweep each over ir_ui_view, ir_filters and ir_exports_line.
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
    """Unit tests for ``stock/migrations/1.4/pre-migrate.py``."""

    script_version = "1.4"
    # ir_ui_view + ir_filters + ir_exports_line + ir_act_server.
    expected_updates = 4

    def _columns(self, *, renamed):
        return {
            ("stock_move", "packaging_uom_qty"): not renamed,
            ("stock_move", "quantity_packaging_uom"): renamed,
        }

    def test_migrate_is_idempotent(self):
        """A second run (old column already renamed) must not error and must
        skip the ``ALTER TABLE`` — only the guarded rename is conditional, the
        four ``UPDATE`` sweeps are naturally idempotent (no matches, no-op)."""
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
    """Unit tests for ``stock/migrations/1.5/pre-migrate.py``."""

    script_version = "1.5"
    # Per token group (1 global + 3 scoped): ir_ui_view + ir_filters = 8,
    # ir_exports_line: 1 global regexp + 6 scoped exact renames = 7,
    # ir_act_server: 1 global sweep. Total 16.
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
        """``scheduled_date``/``delivery_count`` are live fields on unrelated
        models (mail, event, sale.order, ...): every statement rewriting them
        must carry a model filter, and none may touch ``ir_act_server`` —
        rewriting arbitrary server-action code on those tokens would corrupt
        actions that legitimately reference the other models' fields."""
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
        """The unambiguous renames must reach ``ir_act_server.code``."""
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
