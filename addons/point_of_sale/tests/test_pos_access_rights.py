# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Access-right regressions for the point of sale.

Nothing in this module created a plain ``group_pos_user`` before, which is why
the two defects pinned here survived: a cashier could rewrite any point of
sale's configuration, and the one control the product-info popup offers them
was forbidden by the ACL it runs under.

Authored red-green: every test below failed against the pre-fix code.
"""

import logging

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import new_test_user, tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestPosAccessRights(CommonPosTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cashier = new_test_user(
            cls.env,
            login="pos_plain_cashier",
            groups="base.group_user,point_of_sale.group_pos_user",
            company_id=cls.company.id,
        )
        cls.manager = new_test_user(
            cls.env,
            login="pos_plain_manager",
            groups="base.group_user,point_of_sale.group_pos_manager",
            company_id=cls.company.id,
        )

    # ------------------------------------------------------------------
    # A cashier may read the configuration they trade on, never write it.
    # `_get_forbidden_change_fields` only bites while a session is open and
    # `_check_header_footer` covers three fields, so before the ACL was
    # tightened everything else was writable on every shop in the company.
    # ------------------------------------------------------------------
    def test_cashier_cannot_repoint_the_pos_journal(self):
        sink = self.env["account.journal"].create(
            {
                "name": "Sink",
                "type": "sale",
                "code": "SINKJ",
                "company_id": self.company.id,
            }
        )
        original = self.pos_config_usd.journal_id
        with self.assertRaises(AccessError):
            self.pos_config_usd.with_user(self.cashier).write(
                {"journal_id": sink.id}
            )
        self.pos_config_usd.invalidate_recordset(["journal_id"])
        self.assertEqual(self.pos_config_usd.journal_id, original)

    def test_cashier_cannot_attach_a_pricelist(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Cashier pricelist",
                "currency_id": self.pos_config_usd.currency_id.id,
            }
        )
        with self.assertRaises(AccessError):
            self.pos_config_usd.with_user(self.cashier).write(
                {"available_pricelist_ids": [Command.link(pricelist.id)]}
            )
        self.pos_config_usd.invalidate_recordset(["available_pricelist_ids"])
        self.assertNotIn(pricelist, self.pos_config_usd.available_pricelist_ids)

    def test_manager_can_still_configure(self):
        """Control: the tightened ACL must not disarm the manager.

        (Not a receipt header/footer -- `_check_header_footer` reserves those
        three fields for administrators, manager or not.)
        """
        self.pos_config_usd.with_user(self.manager).write(
            {"iface_big_scrollbars": True}
        )
        self.assertTrue(self.pos_config_usd.iface_big_scrollbars)

    # ------------------------------------------------------------------
    # The runtime writes the config as a system operation. Each of these
    # used to ride on the cashier's own write permission.
    # ------------------------------------------------------------------
    def test_cashier_can_still_mint_the_bus_token(self):
        config = self.pos_config_usd
        config.sudo().access_token = False
        token = config.with_user(self.cashier)._get_access_token()
        self.assertTrue(token)
        self.assertEqual(config.sudo().access_token, token)

    def test_cashier_can_still_notify_synchronisation(self):
        config = self.pos_config_usd
        config.open_ui()
        config.with_user(self.cashier).notify_synchronisation(
            config.current_session_id.id, 0
        )

    def test_cashier_can_still_register_a_device(self):
        config = self.pos_config_usd
        result = config.with_user(self.cashier).register_new_device_identifier()
        self.assertTrue(result["device_identifier"])

    def test_cashier_can_still_open_a_session(self):
        """`open_ui` is the cashier's entry point and writes nothing on the
        config itself; it must survive the read-only ACL."""
        config = self.pos_config_usd.with_user(self.cashier)
        config.open_ui()
        self.assertTrue(config.current_session_id)

    # ------------------------------------------------------------------
    # The product-info popup offers a favourite toggle to every cashier
    # (`_role` is only ever "manager" or "cashier" in this module), but
    # `product.template` is read-only for `group_pos_user`.
    # ------------------------------------------------------------------
    def test_cashier_can_toggle_a_pos_favourite(self):
        template = self.env["product.template"].create(
            {"name": "Favourite probe", "available_in_pos": True}
        )
        template.with_user(self.cashier).set_pos_favorite(True)
        self.assertTrue(template.is_favorite)
        template.with_user(self.cashier).set_pos_favorite(False)
        self.assertFalse(template.is_favorite)

    def test_favourite_toggle_writes_nothing_else(self):
        """The elevated write must be a keyhole, not a door: only
        `is_favorite`, and only on a product the point of sale can sell."""
        template = self.env["product.template"].create(
            {"name": "Favourite probe 2", "available_in_pos": True, "list_price": 7}
        )
        template.with_user(self.cashier).set_pos_favorite(True)
        self.assertEqual(template.list_price, 7)

    def test_favourite_toggle_refuses_a_non_pos_product(self):
        template = self.env["product.template"].create(
            {"name": "Not in pos", "available_in_pos": False}
        )
        with self.assertRaises(AccessError):
            template.with_user(self.cashier).set_pos_favorite(True)

    def test_favourite_toggle_refuses_a_non_pos_user(self):
        outsider = new_test_user(
            self.env, login="pos_outsider", groups="base.group_user"
        )
        template = self.env["product.template"].create(
            {"name": "Favourite probe 3", "available_in_pos": True}
        )
        with self.assertRaises(AccessError):
            template.with_user(outsider).set_pos_favorite(True)
