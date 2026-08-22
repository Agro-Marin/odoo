from lxml import html

from odoo.tests import HttpCase, tagged

from odoo.addons.portal.controllers.portal import CustomerPortal

PROBE_COUNTER = "probe_doc_count"


@tagged("-at_install", "post_install")
class TestPortalHomeCounters(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = cls.env["res.users"].create(
            {
                "login": "portal_counters",
                "password": "portal_counters",
                "partner_id": cls.env["res.partner"]
                .create({"name": "Counters Customer"})
                .id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )
        cls.env["ir.ui.view"].create(
            {
                "name": "portal probe counter card",
                "type": "qweb",
                "mode": "extension",
                "inherit_id": cls.env.ref("portal.portal_my_home").id,
                "arch": f"""
                    <xpath expr="//div[@id='portal_common_category']" position="inside">
                        <t t-call="portal.portal_docs_entry">
                            <t t-set="title">Probe Documents</t>
                            <t t-set="url" t-value="'/my/probe'"/>
                            <t t-set="placeholder_count" t-value="'{PROBE_COUNTER}'"/>
                        </t>
                    </xpath>
                """,
            }
        )

    def setUp(self):
        super().setUp()
        self.probe_value = 0
        outer = self

        def _prepare_home_portal_values(self, counters):
            values = {}
            if PROBE_COUNTER in counters:
                values[PROBE_COUNTER] = outer.probe_value
            return values

        self.patch(
            CustomerPortal, "_prepare_home_portal_values", _prepare_home_portal_values
        )


    def _get_home(self):
        response = self.url_open("/my/home")
        self.assertEqual(response.status_code, 200)
        doc = html.fromstring(response.content)
        has_placeholder = bool(
            doc.xpath(f"//*[@data-placeholder_count='{PROBE_COUNTER}']")
        )
        card = doc.xpath(
            f"//*[@data-placeholder_count='{PROBE_COUNTER}']"
            "/ancestor::div[contains(@class, 'o_portal_index_card')]"
        )
        if not card:
            card = doc.xpath(
                "//a[@href='/my/probe']"
                "/ancestor::div[contains(@class, 'o_portal_index_card')]"
            )
        self.assertTrue(card, "the probe card should be rendered either way")
        card_visible = "d-none" not in card[0].get("class", "")
        return has_placeholder, card_visible

    def _fetch_counters(self):
        return self.make_jsonrpc_request("/my/counters", {"counters": [PROBE_COUNTER]})


    def test_counter_card_stays_refreshable_after_being_cached(self):
        self.authenticate("portal_counters", "portal_counters")

        has_placeholder, card_visible = self._get_home()
        self.assertTrue(has_placeholder, "a cold card must publish its placeholder")
        self.assertFalse(card_visible, "a cold card starts hidden")

        self.probe_value = 3
        self.assertEqual(self._fetch_counters(), {PROBE_COUNTER: 3})

        has_placeholder, card_visible = self._get_home()
        self.assertTrue(card_visible, "a cached non-zero card is revealed up front")
        self.assertTrue(
            has_placeholder,
            "a revealed card must still publish its placeholder, otherwise the "
            "counter is never re-fetched and the session hint is frozen",
        )

        self.probe_value = 0
        self.assertEqual(self._fetch_counters(), {PROBE_COUNTER: 0})

        has_placeholder, card_visible = self._get_home()
        self.assertFalse(
            card_visible,
            "once the counter drops to zero the card must be hidden again, not "
            "left as a permanent link to an empty page",
        )
        self.assertTrue(has_placeholder)

    def test_counters_route_clears_a_stale_hint(self):
        self.authenticate("portal_counters", "portal_counters")

        self.probe_value = 7
        self._fetch_counters()
        _, card_visible = self._get_home()
        self.assertTrue(card_visible, "a cached non-zero counter reveals its card")

        self.probe_value = 0
        self._fetch_counters()
        _, card_visible = self._get_home()
        self.assertFalse(card_visible, "a zeroed counter must not stay revealed")
