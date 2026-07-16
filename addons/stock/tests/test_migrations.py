from unittest.mock import MagicMock

from odoo.modules.module import get_module_path, load_script
from odoo.tests import BaseCase


class TestStock14PreMigrate(BaseCase):
    """Unit tests for ``stock/migrations/1.4/pre-migrate.py``.

    Loaded directly via :func:`~odoo.modules.module.load_script` (the same
    loader Odoo itself uses) with a mocked cursor — no registry/DB needed,
    since the script's own SQL is what's under test, not its execution
    against real data.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module_path = get_module_path("stock")
        cls.script = load_script(
            f"{module_path}/migrations/1.4/pre-migrate.py", "stock_1_4_pre_migrate"
        )

    def test_fresh_install_is_noop(self):
        """A falsy ``version`` (fresh install) must not touch the cursor."""
        cr = MagicMock()
        self.script.migrate(cr, None)
        cr.execute.assert_not_called()

    def test_migrate_is_idempotent(self):
        """A second run (old column already renamed) must not error and must
        skip the ``ALTER TABLE`` — only the guarded rename is conditional, the
        four ``UPDATE`` sweeps are naturally idempotent (no matches, no-op)."""
        cr = MagicMock()
        # column_exists(cr, "stock_move", "packaging_uom_qty") -> False (already renamed)
        # column_exists(cr, "stock_move", "quantity_packaging_uom") -> True
        with self._patch_column_exists(renamed=True):
            self.script.migrate(cr, "1.3")
        # No ALTER TABLE should have been issued once the rename already happened.
        alter_calls = [
            call for call in cr.execute.call_args_list if "ALTER TABLE" in call.args[0]
        ]
        self.assertEqual(alter_calls, [])
        # The four UPDATE sweeps still run unconditionally (safe no-ops).
        update_calls = [
            call for call in cr.execute.call_args_list if "UPDATE" in call.args[0]
        ]
        self.assertEqual(len(update_calls), 4)

    def test_migrate_renames_column_when_pending(self):
        """When the old column exists and the new one doesn't, the rename
        must run before the four ``UPDATE`` sweeps."""
        cr = MagicMock()
        with self._patch_column_exists(renamed=False):
            self.script.migrate(cr, "1.3")
        alter_calls = [
            call for call in cr.execute.call_args_list if "ALTER TABLE" in call.args[0]
        ]
        self.assertEqual(len(alter_calls), 1)
        self.assertIn("quantity_packaging_uom", alter_calls[0].args[0])

    def _patch_column_exists(self, *, renamed):
        """Patch ``column_exists`` as imported into the migration module
        under test (the module object returned by :func:`load_script`).

        :param bool renamed: simulate the post-rename (``True``) or
            pre-rename (``False``) column state
        :return: context manager patching the migration module's reference
        """
        from unittest.mock import patch

        def fake_column_exists(cr, table, column):
            if column == "packaging_uom_qty":
                return not renamed
            if column == "quantity_packaging_uom":
                return renamed
            raise AssertionError(f"unexpected column check: {table}.{column}")

        return patch.object(
            self.script, "column_exists", side_effect=fake_column_exists
        )
