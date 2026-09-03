import odoo.tests


@odoo.tests.tagged("-at_install", "post_install", "mail_alias")
class TestAliasUi(odoo.tests.HttpCase):
    def test_copy_alias_email(self):
        """The alias form must offer the full address as one copyable value:
        reading `alias_name` and `alias_domain_id` out of two separate fields
        and retyping them by hand is what this replaces."""
        domain = self.env["mail.alias.domain"].search([], limit=1) or self.env[
            "mail.alias.domain"
        ].create({"name": "test.mycompany.com"})
        self.env.company.alias_domain_id = domain
        alias = self.env["mail.alias"].create(
            {
                "alias_domain_id": domain.id,
                "alias_model_id": self.env["ir.model"]._get_id("res.partner"),
                "alias_name": "test-alias-copy",
            }
        )
        self.start_tour(
            f"/odoo/action-mail.mail_alias_action/{alias.id}",
            "mail_alias_copy_email_tour",
            login="admin",
        )
        # what the button carries is the composed address, not either half
        self.assertEqual(alias.alias_name, "jobs")
        self.assertEqual(alias.alias_full_name, f"jobs@{domain.name}")
