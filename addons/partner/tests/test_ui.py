from lxml import etree

import odoo.tests


@odoo.tests.tagged("-at_install", "post_install")
class TestUi(odoo.tests.HttpCase):
    def test_set_defaults(self):
        """Tests the "Set Defaults" feature of the debug menu on the res.partner form.

        The tour saves a user-defined default for `website` and checks the next
        new contact picks it up. The field has to be one the action does not
        already default: `default_get` reads the context before `ir.default`
        (odoo/orm/models/mixins/create.py), so a field named in the action's own
        context can never show the saved default. It also has to carry a truthy
        value when the dialog opens, because the debug menu only offers fields
        that do (`getDefaultFields` in web/static/src/views/debug_items.js) --
        which is why the tour types an address before saving it as the default.
        """
        # Ensure the requirements of the test:
        # `website` must stay editable, absent from the action context, and the
        # form must keep defaulting `is_company` to True through that context.
        # If any of this changes, the tour needs to be adapted along with these
        # assertions.
        website_field = self.env["res.partner"]._fields["website"]
        self.assertFalse(website_field.readonly)
        action_context = self.env["ir.actions.actions"]._eval_action_context(
            self.env.ref("partner.action_partner").context
        )
        self.assertNotIn("default_website", action_context)
        self.assertTrue(action_context.get("default_is_company"))
        # Make sure there is currently no user-defined default on res.partner.website
        # so the tour's own default is the only one in play
        self.env["ir.default"].search(
            [
                ("field_id", "=", self.env.ref("base.field_res_partner__website").id),
            ]
        ).unlink()
        self.assertFalse(
            self.env["res.partner"].with_context(**action_context).new().website
        )

        self.start_tour("/odoo", "debug_menu_set_defaults", login="admin")

    def test_vat_label_string(self):
        """Test changing the vat_label field of the user company_id.
        It be immediately reflected on partners views.
        """
        partner = self.env["res.partner"].create({"name": "Jean"})
        # call get view to warm the cache
        partner.get_view()

        self.env.user.company_id.country_id = self.env.ref("base.us")
        self.env.user.company_id.country_id.vat_label = "TVA"
        view = partner.get_view()

        arch = etree.fromstring(view["arch"])
        for node in arch.iterfind(".//field[@name='vat']"):
            self.assertEqual(node.get("string"), "TVA")
        for node in arch.iterfind(".//label[@for='vat']"):
            self.assertEqual(node.get("string"), "TVA")
