from odoo.modules.module import get_module_path, load_script
from odoo.tests.common import TransactionCase


class TestBlockedLocationMigration(TransactionCase):
    """stock 1.13 carries the absorbed addon's data fixes. It is the only place
    that repairs a database the addon left inconsistent, and the repair it makes
    is one raw SQL cannot: the gates all read effective_block_type, a stored
    recursive compute, so clearing block_type without recomputing the subtree
    leaves a location enforcing a block it no longer declares.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = load_script(
            f"{get_module_path('stock')}/migrations/1.13/post-migrate.py",
            "stock_1_13_post_migrate",
        )
        cls.Location = cls.env["stock.location"]

    def _force(self, location, **values):
        assignments = ", ".join(f"{name} = %s" for name in values)
        self.env.cr.execute(
            f"UPDATE stock_location SET {assignments} WHERE id = %s",
            [*values.values(), location.id],
        )
        location.invalidate_recordset()

    def _migrate(self, version="1.12"):
        self.script.migrate(self.env.cr, version)

    def test_fresh_install_is_noop(self):
        customers = self.env.ref("stock.stock_location_customers")
        self._force(customers, block_type="hard", effective_block_type="hard")

        self._migrate(version=None)

        customers.invalidate_recordset()
        self.assertEqual(customers.block_type, "hard")

    def test_a_block_on_a_non_internal_location_is_cleared(self):
        customers = self.env.ref("stock.stock_location_customers")
        self._force(
            customers,
            block_type="hard",
            effective_block_type="hard",
            block_reason="bad import",
        )

        self._migrate()

        customers.invalidate_recordset()
        self.assertEqual(customers.block_type, "none")

    def test_clearing_a_block_recomputes_the_whole_subtree(self):
        customers = self.env.ref("stock.stock_location_customers")
        child = self.Location.create(
            {"name": "Migration Child", "location_id": customers.id},
        )
        self._force(customers, block_type="hard", effective_block_type="hard")
        self._force(child, effective_block_type="hard")

        self._migrate()

        (customers | child).invalidate_recordset()
        self.assertEqual(customers.effective_block_type, "none")
        self.assertEqual(
            child.effective_block_type,
            "none",
            "a descendant left reading 'hard' keeps refusing every operation "
            "under a block its ancestor no longer declares",
        )

    def test_a_stale_effective_block_type_is_resynced(self):
        stock_location = self.env.ref("stock.stock_location_stock")
        shelf = self.Location.create(
            {"name": "Migration Shelf", "location_id": stock_location.id},
        )
        # The block a raw writer applied without the compute ever running: the
        # location declares a quarantine that nothing enforces.
        self._force(shelf, block_type="hard", effective_block_type="none")

        self._migrate()

        shelf.invalidate_recordset()
        self.assertEqual(shelf.effective_block_type, "hard")

    def test_an_internal_block_is_left_alone(self):
        stock_location = self.env.ref("stock.stock_location_stock")
        shelf = self.Location.create(
            {
                "name": "Migration Quarantine",
                "location_id": stock_location.id,
                "block_type": "soft_out",
                "block_reason": "quality hold",
            },
        )

        self._migrate()

        shelf.invalidate_recordset()
        self.assertEqual(shelf.block_type, "soft_out")
        self.assertEqual(shelf.effective_block_type, "soft_out")
