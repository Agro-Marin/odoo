from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIrModelDataCacheInvalidation(TransactionCase):
    def test_write_on_existing_groups_xmlid_clears_groups_cache(self):
        group = self.env.ref("base.group_user")
        imd = self.env["ir.model.data"].search(
            [("model", "=", "res.groups"), ("res_id", "=", group.id)], limit=1
        )
        self.assertTrue(imd, "expected an ir.model.data row for base.group_user")

        with patch.object(
            self.env.registry,
            "clear_cache",
            wraps=self.env.registry.clear_cache,
        ) as mock_clear:
            imd.write({"noupdate": True})

        cleared = [call.args for call in mock_clear.call_args_list]
        self.assertIn(
            ("groups",),
            cleared,
            "writing a res.groups xmlid must invalidate the `groups` cache even "
            "when vals does not include `model`",
        )
