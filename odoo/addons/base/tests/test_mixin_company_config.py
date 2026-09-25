from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestCompanyConfigDelegation(TransactionCase):
    def test_a_root_write_reaches_every_branch(self):
        Config = self.env["report.config"]
        first, second = self.env["report.paperformat"].search([], limit=2)
        with patch.object(
            type(Config),
            "_get_field_names_delegated_to_root",
            lambda self: ["paperformat_id"],
        ):
            Company = self.env["res.company"]
            root = Company.create({"name": "Delegating Root"})
            Config._for(root).paperformat_id = first
            branch = Company.create({"name": "Delegating Branch", "parent_id": root.id})
            leaf = Company.create({"name": "Delegating Leaf", "parent_id": branch.id})
            configs = Config._for_each(branch + leaf)
            self.assertEqual(configs.paperformat_id, first)

            Config._for(root).write({"paperformat_id": second.id})

            self.assertEqual(configs.paperformat_id, second)
            configs._check_delegated_fields_match_root()
