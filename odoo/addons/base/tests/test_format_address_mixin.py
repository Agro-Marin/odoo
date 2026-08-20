from lxml import etree

from odoo.addons.base.tests.test_views import ViewCase


class FormatAddressCase(ViewCase):
    def assertAddressView(self, model):
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

        form_arch = """<form><field name="id"/><div class="o_address_format"><field name="street"/></div></form>"""
        view = self.View.create(
            {
                "name": "view",
                "model": model,
                "arch": form_arch,
            }
        )

        arch = self.env[model].get_view(view.id)["arch"]
        self.assertIn('"street"', arch)
        self.assertNotIn('"city"', arch)

        self.env.company.country_id.address_view_id = address_view
        arch = self.env[model].get_view(view.id)["arch"]
        self.assertNotIn('"street"', arch)
        self.assertIn('"city"', arch)
        self.assertRegex(
            arch, r'<form>.*<div class="o_address_format">.*</div>.*</form>'
        )
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
        country = self.env["res.country"].create(
            {
                "name": "Reorder Land",
                "code": "RL",
                "address_format": "%(street)s\n%(zip)s %(city)s %(state_code)s\n",
            }
        )
        self.env.company.country_id = country

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
        self.assertEqual(order.index("zip"), 0)
        self.assertLess(order.index("zip"), order.index("city"))
        self.assertLess(order.index("city"), order.index("state_id"))

    def test_non_partner_model_postprocess_fallback(self):
        model = "res.country.state"

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

        arch = self.env[model].get_view(view.id)["arch"]
        self.assertNotIn('"city"', arch)

    def test_address_view_fresh_after_company_country_change(self):
        address_view = self.View.create(
            {
                "name": "addr",
                "model": "res.partner",
                "arch": '<form><div class="o_address_format"><field name="city"/></div></form>',
                "priority": 900,
            }
        )
        country_plain = self.env["res.country"].create(
            {"name": "Plain Land", "code": "P1"}
        )
        country_custom = self.env["res.country"].create(
            {"name": "Custom Land", "code": "P2", "address_view_id": address_view.id}
        )
        view = self.View.create(
            {
                "name": "view",
                "model": "res.partner",
                "arch": '<form><div class="o_address_format"><field name="street"/></div></form>',
            }
        )

        self.env.company.country_id = country_plain
        arch = self.env["res.partner"].get_view(view.id)["arch"]
        self.assertIn('"street"', arch)
        self.assertNotIn('"city"', arch)

        self.env.company.country_id = country_custom
        arch = self.env["res.partner"].get_view(view.id)["arch"]
        self.assertNotIn('"street"', arch)
        self.assertIn('"city"', arch)

        self.env.company.country_id = country_plain
        arch = self.env["res.partner"].get_view(view.id)["arch"]
        self.assertIn('"street"', arch)
        self.assertNotIn('"city"', arch)

    def test_address_view_fresh_after_country_address_format_change(self):
        country = self.env["res.country"].create(
            {
                "name": "Fresh Format Land",
                "code": "F1",
                "address_format": "%(street)s\n%(zip)s %(city)s %(state_code)s\n",
            }
        )
        self.env.company.country_id = country
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
        order = [
            node.get("name")
            for node in etree.fromstring(arch).xpath(
                "//div[hasclass('o_address_format')]//field[@name]"
            )
        ]
        self.assertEqual(order, ["zip", "city", "state_id"])

        country.address_format = "%(street)s\n%(city)s %(zip)s %(state_code)s\n"
        arch = self.env["res.partner"].get_view(view.id)["arch"]
        order = [
            node.get("name")
            for node in etree.fromstring(arch).xpath(
                "//div[hasclass('o_address_format')]//field[@name]"
            )
        ]
        self.assertEqual(order, ["city", "zip", "state_id"])

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

        self.assertIn("John Doe", partner.display_name)

        display_name = partner.with_context(show_address=True).display_name
        self.assertIn("123 Main Street", display_name)
        self.assertIn("Paris", display_name)
        self.assertNotIn("\n\n", display_name)


class TestFormatVatLabel(ViewCase):
    def test_vat_label_cache_key_is_vat_label_keyed(self):
        mixin = self.env["mixin.format.vat.label"]
        base_key = self.env["ir.ui.view"]._get_view_cache_key("form")
        vat_key = mixin._get_view_cache_key("form")

        self.assertEqual(vat_key, base_key + (self.env.company.country_id.vat_label,))

        country_b = self.env["res.country"].create(
            {"name": "VAT Key Land", "code": "X7", "vat_label": "KEYVAT"}
        )
        company_b = self.env["res.company"].create(
            {"name": "VAT Co B", "country_id": country_b.id}
        )
        key_a = mixin._get_view_cache_key("form")
        key_b = mixin.with_company(company_b)._get_view_cache_key("form")
        self.assertNotEqual(key_a, key_b)

        company_c = self.env["res.company"].create(
            {"name": "VAT Co C", "country_id": country_b.id}
        )
        key_c = mixin.with_company(company_c)._get_view_cache_key("form")
        self.assertEqual(key_b, key_c)

    def test_vat_label_relabels_field_per_company_country(self):
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

    def test_vat_label_fresh_after_country_or_label_change(self):
        country = self.env["res.country"].create(
            {"name": "VAT Fresh Land", "code": "X8", "vat_label": "OLDVAT"}
        )
        view = self.View.create(
            {
                "name": "vat view",
                "model": "res.company",
                "arch": '<form><field name="vat"/></form>',
            }
        )
        Company = self.env["res.company"]

        self.env.company.country_id = country
        arch = Company.get_view(view.id)["arch"]
        self.assertIn('string="OLDVAT"', arch)

        country.vat_label = "NEWVAT"
        arch = Company.get_view(view.id)["arch"]
        self.assertIn('string="NEWVAT"', arch)

        country_2 = self.env["res.country"].create(
            {"name": "VAT Fresh Land 2", "code": "X9", "vat_label": "OTHERVAT"}
        )
        self.env.company.country_id = country_2
        arch = Company.get_view(view.id)["arch"]
        self.assertIn('string="OTHERVAT"', arch)
