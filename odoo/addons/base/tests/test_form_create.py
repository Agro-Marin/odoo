from odoo.tests import Form, TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestFormCreate(TransactionCase):
    def test_create_res_partner(self):
        if hasattr(self.env["res.partner"], "property_account_payable_id"):
            self.env.user.group_ids += self.env.ref("account.group_account_readonly")
            self.env.user.group_ids += self.env.ref("account.group_account_user")
        partner_form = Form(self.env["res.partner"])
        partner_form.name = "a partner"
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
        lang_form.name = "a lang name"
        lang_form.code = "a lang code"
        lang_form.save()

    def test_modifier_merge_semantics(self):
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
        self.assertEqual(partner_form._view["modifiers"]["name"]["readonly"], "False")
        partner_form.name = "a partner"

        self.assertFalse(partner_form._get_modifier("email", "invisible"))
        partner_form.phone = "x"
        self.assertTrue(partner_form._get_modifier("email", "invisible"))
        partner_form.phone = "y"
        partner_form.ref = "y"
        self.assertTrue(partner_form._get_modifier("email", "invisible"))

    def test_create_o2m_mode_form(self):
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


NESTED_O2M_ARCH = """
<form>
  <field name="name"/>
  <field name="child_ids">
    <form>
      <field name="name"/>
      <field name="child_ids">
        <form>
          <field name="name"/>
          <field name="child_ids"><form><field name="name"/></form></field>
        </form>
      </field>
    </form>
  </field>
</form>
"""


@tagged("-at_install", "post_install")
class TestFormNestedX2many(TransactionCase):
    def _nested_form(self):
        view = self.env["ir.ui.view"].create(
            {
                "name": "nested o2m probe",
                "model": "res.partner",
                "arch": NESTED_O2M_ARCH,
            }
        )
        return Form(self.env["res.partner"], view=view)

    def test_outer_o2m_keeps_its_type(self):
        form = self._nested_form()
        self.assertEqual(form._view["fields"]["child_ids"]["type"], "one2many")

    def test_field_info_is_not_aliased_into_models_info(self):
        form = self._nested_form()
        self.assertIsNot(
            form._view["fields"]["child_ids"],
            form._models_info["res.partner"]["fields"]["child_ids"],
        )

    def test_outer_o2m_is_still_editable(self):
        form = self._nested_form()
        form.name = "root"
        with form.child_ids.new() as line:
            line.name = "child"
        record = form.save()
        self.assertEqual(record.child_ids.mapped("name"), ["child"])


@tagged("-at_install", "post_install")
class TestFormAttributeAccess(TransactionCase):
    def test_unknown_private_attribute_raises_attribute_error(self):
        form = Form(self.env["res.partner"])
        with self.assertRaises(AttributeError):
            _ = form._not_a_field
        self.assertFalse(hasattr(form, "_not_a_field"))

    def test_unknown_field_still_reports_the_view(self):
        form = Form(self.env["res.partner"])
        with self.assertRaises(AssertionError):
            _ = form.definitely_not_a_field

    def test_half_built_form_does_not_recurse(self):
        form = Form.__new__(Form)
        with self.assertRaises(AttributeError):
            _ = form._view
