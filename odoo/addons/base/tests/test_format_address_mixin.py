from lxml import etree

from odoo.addons.base.tests.test_views import ViewCase


class FormatAddressCase(ViewCase):
    def assertAddressView(self, model):
        # pe_partner_address_form
        address_arch = (
            """<form><div class="o_address_format"><field name="city"/></div></form>"""
        )
        address_view = self.View.create(
            {
                "name": "view",
                "model": model,
                "arch": address_arch,
                "priority": 900,
            }
        )

        # view can be created without address_view
        form_arch = """<form><field name="id"/><div class="o_address_format"><field name="street"/></div></form>"""
        view = self.View.create(
            {
                "name": "view",
                "model": model,
                "arch": form_arch,
            }
        )

        # default view, no address_view defined
        arch = self.env[model].get_view(view.id)["arch"]
        self.assertIn('"street"', arch)
        self.assertNotIn('"city"', arch)

        # custom view, address_view defined
        self.env.company.country_id.address_view_id = address_view
        arch = self.env[model].get_view(view.id)["arch"]
        self.assertNotIn('"street"', arch)
        self.assertIn('"city"', arch)
        self.assertRegex(
            arch, r'<form>.*<div class="o_address_format">.*</div>.*</form>'
        )
        # no_address_format context
        arch = (
            self.env[model]
            .with_context(no_address_format=True)
            .get_view(view.id)["arch"]
        )
        self.assertIn('"street"', arch)
        self.assertNotIn('"city"', arch)

        belgium = self.env.ref("base.be")
        france = self.env.ref("base.fr")

        belgium.address_view_id = None
        france.address_view_id = address_view

        company_a, company_b = self.env["res.company"].create(
            [
                {"name": "foo", "country_id": belgium.id},
                {"name": "bar", "country_id": france.id},
            ]
        )

        arch = self.env[model].with_company(company_a).get_view(view.id)["arch"]
        self.assertIn('"street"', arch)
        self.assertNotIn('"city"', arch)

        arch = self.env[model].with_company(company_b).get_view(view.id)["arch"]
        self.assertNotIn('"street"', arch)
        self.assertIn('"city"', arch)


class TestPartnerFormatAddress(FormatAddressCase):
    def test_address_view(self):
        self.env.company.country_id = self.env.ref("base.us")
        self.assertAddressView("res.partner")

    def test_address_format_reorder_branch(self):
        """The address_format elif branch reorders zip/city/state fields in the
        o_address_format div to follow the country's address_format order."""
        country = self.env["res.country"].create(
            {
                "name": "Reorder Land",
                "code": "RL",
                # No address_view_id: forces the address_format reorder branch.
                # City line orders fields zip -> city -> state.
                "address_format": "%(street)s\n%(zip)s %(city)s %(state_code)s\n",
            }
        )
        self.env.company.country_id = country

        # DOM order (city, zip, state_id) differs from the format order.
        form_arch = (
            "<form>"
            '<div class="o_address_format">'
            '<field name="city"/><field name="zip"/><field name="state_id"/>'
            "</div>"
            "</form>"
        )
        view = self.View.create(
            {"name": "view", "model": "res.partner", "arch": form_arch}
        )

        arch = self.env["res.partner"].get_view(view.id)["arch"]
        tree = etree.fromstring(arch)
        order = [
            node.get("name")
            for node in tree.xpath("//div[hasclass('o_address_format')]//field[@name]")
        ]
        # zip is first (it leads the city line), then city, then state_id.
        self.assertEqual(order.index("zip"), 0)
        self.assertLess(order.index("zip"), order.index("city"))
        self.assertLess(order.index("city"), order.index("state_id"))

    def test_non_partner_model_postprocess_fallback(self):
        """When a non-res.partner model uses an address_view referencing fields
        absent on the model, the postprocess_and_fields ValueError is caught and
        the original arch is returned unchanged."""
        # res.country.state has no o_address_format / partner address fields.
        model = "res.country.state"

        # An address_view authored against res.partner referencing a field
        # (city) that does not exist on res.country.state.
        address_view = self.View.create(
            {
                "name": "addr",
                "model": "res.partner",
                "arch": '<form><div class="o_address_format"><field name="city"/></div></form>',
                "priority": 900,
            }
        )
        self.env.company.country_id.address_view_id = address_view

        form_arch = (
            '<form><field name="name"/>'
            '<div class="o_address_format"><field name="name"/></div></form>'
        )
        view = self.View.create({"name": "view", "model": model, "arch": form_arch})

        # Must not raise; falls back to the original arch (no city injected).
        arch = self.env[model].get_view(view.id)["arch"]
        self.assertNotIn('"city"', arch)

    def test_display_name_address_formatting(self):
        france = self.env.ref("base.fr")

        partner = self.env["res.partner"].create(
            {
                "name": "John Doe",
                "street": "123 Main Street",
                "street2": "",
                "city": "Paris",
                "country_id": france.id,
            }
        )

        # Default display_name without context
        self.assertIn("John Doe", partner.display_name)

        # display_name with show_address context
        display_name = partner.with_context(show_address=True).display_name
        self.assertIn("123 Main Street", display_name)
        self.assertIn("Paris", display_name)
        self.assertNotIn("\n\n", display_name)


class TestFormatVatLabel(ViewCase):
    def test_vat_label_cache_key_is_company_keyed(self):
        """format.vat.label.mixin extends _get_view_cache_key with the company,
        so the company-dependent vat relabel cannot be served stale across
        companies (isolated: the mixin's own override, not the address mixin)."""
        mixin = self.env["format.vat.label.mixin"]
        base_key = self.env["ir.ui.view"]._get_view_cache_key("form")
        vat_key = mixin._get_view_cache_key("form")

        # The override appends exactly the current company.
        self.assertEqual(vat_key, base_key + (self.env.company,))

        # Two companies yield distinct keys -> no cross-company cache sharing.
        company_b = self.env["res.company"].create({"name": "VAT Co B"})
        key_a = mixin._get_view_cache_key("form")
        key_b = mixin.with_company(company_b)._get_view_cache_key("form")
        self.assertNotEqual(key_a, key_b)

    def test_vat_label_relabels_field_per_company_country(self):
        """The vat field/label string follows the rendering company's country
        vat_label (end-to-end through a real consumer, res.company)."""
        # res.company mixes in format.vat.label.mixin.
        country_rfc = self.env["res.country"].create(
            {"name": "VAT RFC Land", "code": "VR", "vat_label": "RFC"}
        )
        country_tin = self.env["res.country"].create(
            {"name": "VAT TIN Land", "code": "VT", "vat_label": "TIN"}
        )
        company_a, company_b = self.env["res.company"].create(
            [
                {"name": "Co RFC", "country_id": country_rfc.id},
                {"name": "Co TIN", "country_id": country_tin.id},
            ]
        )

        view = self.View.create(
            {
                "name": "vat view",
                "model": "res.company",
                "arch": '<form><field name="vat"/></form>',
            }
        )

        arch_a = (
            self.env["res.company"].with_company(company_a).get_view(view.id)["arch"]
        )
        arch_b = (
            self.env["res.company"].with_company(company_b).get_view(view.id)["arch"]
        )
        self.assertIn('string="RFC"', arch_a)
        self.assertIn('string="TIN"', arch_b)
