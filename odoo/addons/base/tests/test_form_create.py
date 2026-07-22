from odoo.tests import Form, TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestFormCreate(TransactionCase):
    """Test that basic Odoo model records can be created from the interface."""

    def test_create_res_partner(self):
        # YTI: Clean that brol
        if hasattr(self.env["res.partner"], "property_account_payable_id"):
            # Both groups are needed to see the property account fields: account
            # requires group_account_readonly, account_accountant switches it to
            # group_account_user.
            # https://github.com/odoo/enterprise/commit/68f6c1f9fd3ff6762c98e1a405ade035129efce0
            self.env.user.group_ids += self.env.ref("account.group_account_readonly")
            self.env.user.group_ids += self.env.ref("account.group_account_user")
        partner_form = Form(self.env["res.partner"])
        partner_form.name = "a partner"
        # YTI: Clean that brol
        if hasattr(self.env["res.partner"], "property_account_payable_id"):
            property_account_payable_id = self.env["account.account"].create(
                {
                    "name": "Test Account",
                    "account_type": "liability_payable",
                    "code": "TestAccountPayable",
                    "reconcile": True,
                }
            )
            property_account_receivable_id = self.env["account.account"].create(
                {
                    "name": "Test Account",
                    "account_type": "asset_receivable",
                    "code": "TestAccountReceivable",
                    "reconcile": True,
                }
            )
            partner_form.property_account_payable_id = property_account_payable_id
            partner_form.property_account_receivable_id = property_account_receivable_id
        partner_form.save()

    def test_create_res_users(self):
        user_form = Form(self.env["res.users"])
        user_form.login = "a user login"
        user_form.name = "a user name"
        user_form.save()

    def test_create_res_company(self):
        company_form = Form(self.env["res.company"])
        company_form.name = "a company"
        company_form.save()

    def test_create_res_group(self):
        group_form = Form(self.env["res.groups"])
        group_form.name = "a group"
        group_form.save()

    def test_create_res_bank(self):
        bank_form = Form(self.env["res.bank"])
        bank_form.name = "a bank"
        bank_form.save()

    def test_create_res_country(self):
        country_form = Form(self.env["res.country"])
        country_form.name = "a country"
        country_form.code = "ZX"
        country_form.save()

    def test_create_res_lang(self):
        lang_form = Form(self.env["res.lang"])
        # lang_form.url_code = 'LANG'  # invisible field, tested in http_routing
        lang_form.name = "a lang name"
        lang_form.code = "a lang code"
        lang_form.save()

    def test_modifier_merge_semantics(self):
        """Duplicate field occurrences AND their modifiers; ancestor
        invisible ORs with the field's own; literal True/False operands are
        simplified away."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "partner modifier merge",
                "model": "res.partner",
                "type": "form",
                "arch": """
                    <form>
                        <field name="name" readonly="1"/>
                        <field name="name" readonly="0"/>
                        <field name="phone"/>
                        <field name="ref"/>
                        <group invisible="phone == 'x'">
                            <field name="email" invisible="ref == 'y'"/>
                        </group>
                    </form>
                """,
            }
        )
        partner_form = Form(self.env["res.partner"], view=view)
        # readonly="1" AND readonly="0" simplifies to plain False
        self.assertEqual(partner_form._view["modifiers"]["name"]["readonly"], "False")
        partner_form.name = "a partner"  # writable: not all occurrences readonly

        self.assertFalse(partner_form._get_modifier("email", "invisible"))
        partner_form.phone = "x"  # ancestor <group invisible="phone == 'x'">
        self.assertTrue(partner_form._get_modifier("email", "invisible"))
        partner_form.phone = "y"
        partner_form.ref = "y"  # the field's own invisible modifier
        self.assertTrue(partner_form._get_modifier("email", "invisible"))

    def test_create_o2m_mode_form(self):
        """A one2many with mode="form" used to crash Form with a bare
        StopIteration when picking the edition subview."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "partner o2m mode form",
                "model": "res.partner",
                "type": "form",
                "arch": """
                    <form>
                        <field name="name"/>
                        <field name="child_ids" mode="form">
                            <form><field name="name"/></form>
                        </field>
                    </form>
                """,
            }
        )
        partner_form = Form(self.env["res.partner"], view=view)
        partner_form.name = "a partner"
        with partner_form.child_ids.new() as child:
            child.name = "a child"
        partner = partner_form.save()
        self.assertEqual(partner.child_ids.name, "a child")
