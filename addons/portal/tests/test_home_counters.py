"""Regression guards for the ``/my/home`` document-counter cards.

The cards on the portal home are rendered hidden and revealed by
``portal.portal_home_counters`` (JS), which asks ``/my/counters`` for exactly
the counters it finds in the DOM as ``[data-placeholder_count]`` elements. The
server keeps a ``portal_counters`` session hint of which counters were non-zero
last time, so a returning customer's cards can be shown immediately instead of
flashing in after the round-trip.

That hint is written by :meth:`CustomerPortal.counters` and read by the
``portal.portal_docs_entry`` template. The two have to agree on one thing: a
card that the hint reveals must still publish its placeholder, otherwise the
client stops asking about that counter and the hint can never be corrected.
"""

from lxml import html

from odoo.tests import HttpCase, tagged

from odoo.addons.portal.controllers.portal import CustomerPortal

#: Counter name used by the probe card installed below. Must end in ``_count``
#: -- that suffix is what ``counters()`` uses to decide what to cache.
PROBE_COUNTER = "probe_doc_count"


@tagged("-at_install", "post_install")
class TestPortalHomeCounters(HttpCase):
    """The session counter hint must not make a card unrefreshable."""

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
        # A card driven by a counter, added to the stock portal home. Mirrors
        # what sale/purchase/account contribute, minus their dependencies.
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
        # The counter value the patched controller reports, mutable per-test.
        self.probe_value = 0
        outer = self

        def _prepare_home_portal_values(self, counters):
            """Same contract as sale/purchase: only answer what was asked."""
            values = {}
            if PROBE_COUNTER in counters:
                values[PROBE_COUNTER] = outer.probe_value
            return values

        self.patch(
            CustomerPortal, "_prepare_home_portal_values", _prepare_home_portal_values
        )

    # -- helpers ---------------------------------------------------------

    def _get_home(self):
        """Fetch /my/home and report how the probe card was rendered.

        :return: ``(has_placeholder, card_visible)`` -- whether the card
                 publishes a ``data-placeholder_count`` for the JS to pick up,
                 and whether it is revealed server-side.
        """
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
            # No placeholder: locate the card by its link instead.
            card = doc.xpath(
                "//a[@href='/my/probe']"
                "/ancestor::div[contains(@class, 'o_portal_index_card')]"
            )
        self.assertTrue(card, "the probe card should be rendered either way")
        card_visible = "d-none" not in card[0].get("class", "")
        return has_placeholder, card_visible

    def _fetch_counters(self):
        """Do what the JS does: ask /my/counters for the placeholders on the page."""
        return self.make_jsonrpc_request("/my/counters", {"counters": [PROBE_COUNTER]})

    # -- tests -----------------------------------------------------------

    def test_counter_card_stays_refreshable_after_being_cached(self):
        """A card revealed from the session hint must still be refreshable.

        Sequence: the customer has documents (card gets cached as non-zero),
        then loses them all. The card must not survive as a permanently
        revealed link to an empty page.
        """
        self.authenticate("portal_counters", "portal_counters")

        # 1. First visit: nothing cached, so the card is hidden and publishes
        #    its placeholder for the client to resolve.
        has_placeholder, card_visible = self._get_home()
        self.assertTrue(has_placeholder, "a cold card must publish its placeholder")
        self.assertFalse(card_visible, "a cold card starts hidden")

        # 2. The customer has documents; the client resolves the counter and
        #    the server remembers that it was non-zero.
        self.probe_value = 3
        self.assertEqual(self._fetch_counters(), {PROBE_COUNTER: 3})

        # 3. Second visit: the hint reveals the card immediately. It must still
        #    publish its placeholder, otherwise the client will never ask about
        #    this counter again and the hint can never be corrected.
        has_placeholder, card_visible = self._get_home()
        self.assertTrue(card_visible, "a cached non-zero card is revealed up front")
        self.assertTrue(
            has_placeholder,
            "a revealed card must still publish its placeholder, otherwise the "
            "counter is never re-fetched and the session hint is frozen",
        )

        # 4. The documents are gone. The client re-asks (it still has the
        #    placeholder) and the hint must flip back to falsy.
        self.probe_value = 0
        self.assertEqual(self._fetch_counters(), {PROBE_COUNTER: 0})

        # 5. Third visit: the card is hidden again, as on a cold session.
        has_placeholder, card_visible = self._get_home()
        self.assertFalse(
            card_visible,
            "once the counter drops to zero the card must be hidden again, not "
            "left as a permanent link to an empty page",
        )
        self.assertTrue(has_placeholder)

    def test_counters_route_clears_a_stale_hint(self):
        """A hint written as non-zero must be erasable by a later zero answer."""
        self.authenticate("portal_counters", "portal_counters")

        self.probe_value = 7
        self._fetch_counters()
        _, card_visible = self._get_home()
        self.assertTrue(card_visible, "a cached non-zero counter reveals its card")

        self.probe_value = 0
        self._fetch_counters()
        _, card_visible = self._get_home()
        self.assertFalse(card_visible, "a zeroed counter must not stay revealed")
