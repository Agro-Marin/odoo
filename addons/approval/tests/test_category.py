from odoo.tests import common, tagged


class TestCategoryApproverCompute(common.TransactionCase):
    def test_existing_user_ids_with_no_category(self):
        approver_record = self.env["approval.category.approver"].new(
            {
                "user_id": self.env.ref("base.user_admin").id,
            }
        )

        self.assertFalse(
            approver_record.existing_user_ids,
            "Should return empty when no category",
        )


@tagged("post_install", "-at_install")
class TestCategorySequenceCodeDerivation(common.TransactionCase):
    def test_derived_code_skips_a_code_held_by_an_archived_category(self):
        category = self.env["approval.category"].create(
            {"name": "Archived Holder", "sequence_code": "ARCHHOLD"},
        )
        category.active = False
        self.env.flush_all()

        fresh = self.env["approval.category"].create({"name": "ARCHHOLD"})

        self.assertNotEqual(
            fresh.sequence_code,
            "ARCHHOLD",
            "The derived code must step past the archived category's code.",
        )
        self.assertTrue(fresh.sequence_code.startswith("ARCHHOLD"))

    def test_derived_code_skips_a_code_held_by_an_active_category(self):
        self.env["approval.category"].create(
            {"name": "Active Holder", "sequence_code": "ACTVHOLD"},
        )
        self.env.flush_all()

        fresh = self.env["approval.category"].create({"name": "ACTVHOLD"})

        self.assertNotEqual(fresh.sequence_code, "ACTVHOLD")
