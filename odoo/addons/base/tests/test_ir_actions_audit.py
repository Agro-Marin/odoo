from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIrActionsExists(TransactionCase):
    """IRA-L1: ir.actions exists() must reflect uncommitted changes in the
    current transaction. The public exists() override that read the cached
    _existing() id set (stale for NewId / just-created records) was removed; the
    cache is now used only inside the already-flushing _get_bindings.
    """

    def test_exists_reflects_uncommitted_create(self):
        model = self.env["ir.actions.act_url"]
        action = model.create({"name": "audit-ira-l1", "url": "/audit/ira-l1"})
        # Standard ORM exists() must see the just-created (uncommitted) record.
        # The removed act_window override consulted a cached id-set that could
        # exclude such records.
        self.assertEqual(action.exists(), action)

    def test_get_bindings_still_resolves(self):
        # _get_bindings filters to existing actions via _existing(); it must
        # still return a mapping without raising after the override removal.
        bindings = self.env["ir.actions.actions"]._get_bindings("res.partner")
        self.assertIsInstance(dict(bindings), dict)
