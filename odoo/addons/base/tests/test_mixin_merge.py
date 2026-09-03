from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestMixinMergeSidecars(TransactionCase):
    def setUp(self):
        super().setUp()
        self.wizard = self.env["base.partner.merge.automatic.wizard"].create({})

    def test_the_sidecar_list_comes_from_the_registry(self):
        sidecars = self.wizard._get_sidecar_reference_fields()
        self.assertIn(("ir.attachment", "res_model", "res_id"), sidecars)
        self.assertIn(("ir.model.data", "model", "res_id"), sidecars)
        for model, field_model, field_id in sidecars:
            field = self.env[model]._fields[field_id]
            self.assertTrue(field.store and field.is_many2one_reference)
            self.assertEqual(field.model_field, field_model)

    def test_a_unique_index_counts_as_a_clash_guard(self):
        self.env.cr.execute(
            "CREATE TABLE test_merge_uix (id serial PRIMARY KEY, partner_id int)"
        )
        self.assertFalse(
            self.wizard._has_check_or_unique_constraint("test_merge_uix", "partner_id")
        )
        self.env.cr.execute(
            "CREATE UNIQUE INDEX test_merge_uix_partner ON test_merge_uix (partner_id)"
        )
        self.assertTrue(
            self.wizard._has_check_or_unique_constraint("test_merge_uix", "partner_id")
        )

    @mute_logger("odoo.addons.base.merge")
    def test_a_clashing_follower_drops_only_itself(self):
        if "mail.followers" not in self.env.registry:
            self.skipTest("mail is not installed")
        Partner = self.env["res.partner"]
        dst, src, shared, only_src = (
            Partner.create({"name": name})
            for name in ("merge dst", "merge src", "follower shared", "follower src")
        )
        dst.message_subscribe(partner_ids=shared.ids)
        src.message_subscribe(partner_ids=(shared + only_src).ids)
        self.env.flush_all()

        self.wizard._update_reference_fields_generic("res.partner", src, dst)

        self.assertEqual(
            dst.message_partner_ids,
            shared + only_src,
            "the follower src alone had must move; only the duplicate is dropped",
        )
        self.assertFalse(src.message_partner_ids)
