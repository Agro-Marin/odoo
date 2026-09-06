from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

# Server actions that carry stock.group_stock_user but which the readonly tier
# must NOT be able to run. Kept here so the assertion below is a whitelist with
# a stated reason rather than a count that drifts.
EXCLUDED_SERVER_ACTIONS = {
    # Open product.replenish, which creates procurements.
    "stock.action_product_template_replenishment",
    "stock.action_product_replenishment",
}

# Models whose explicit ACL rows were dropped as redundant because
# base.group_user already grants read and the readonly group implies it. The
# grants now live upstream, on a different lifecycle, so this list is asserted:
# if upstream ever narrows one, this test fails instead of access disappearing.
READ_VIA_BASE_GROUP_USER = [
    "barcode.nomenclature",
    "barcode.rule",
    "product.attribute",
    "product.attribute.value",
    "product.category",
    "product.pricelist",
    "product.pricelist.item",
    "product.product",
    "product.supplierinfo",
    "product.tag",
    "product.template",
    "product.template.attribute.exclusion",
    "product.template.attribute.line",
    "product.template.attribute.value",
    "report.stock.quantity",
    "res.partner",
    "stock.location",
    "stock.move.line",
    "stock.package",
    "stock.picking.type",
    "stock.putaway.rule",
    "stock.quant",
    "stock.route",
    "stock.rule",
    "stock.storage.category",
    "stock.storage.category.capacity",
    "stock.warehouse",
    "uom.uom",
]

# Wizards the readonly tier may instantiate: they only read.
READ_ONLY_WIZARDS = [
    "stock.quantity.history",
    "stock.rules.report",
    "stock.traceability.report",
]

# Wizards that front a write. A readonly row on these buys nothing, so they
# carry none and the readonly tier cannot even read them.
WRITE_WIZARDS = [
    "product.replenish",
    "stock.quant.relocate",
    "stock.replenishment.info",
    "stock.replenishment.option",
    "stock.request.count",
    "stock.return.picking",
]


@tagged("post_install", "-at_install")
class TestStockGroupReadonly(TransactionCase):
    """The readonly tier's contract.

    post_install because every assertion here reads the ACL union and the
    group graph, both of which are only settled once every module has loaded.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_readonly = cls.env.ref("stock.group_stock_readonly")
        cls.group_user = cls.env.ref("stock.group_stock_user")
        cls.group_manager = cls.env.ref("stock.group_stock_manager")

        cls.user_readonly = cls._create_user("test_sgr_readonly", cls.group_readonly)
        cls.user_stock = cls._create_user("test_sgr_user", cls.group_user)
        cls.user_manager = cls._create_user("test_sgr_manager", cls.group_manager)

        # A readonly account must not carry the User tier, or every assertion
        # below passes for the wrong reason.
        assert cls.group_user not in cls.user_readonly.all_group_ids, (
            "the readonly test user carries stock.group_stock_user"
        )

        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.product = cls.env["product.product"].create(
            {"name": "Test SGR Product", "is_storable": True, "type": "consu"}
        )

    @classmethod
    def _create_user(cls, login, group):
        """Create a real user in exactly one stock group.

        The uid assertion is not ceremony. `with_user` on an empty recordset
        runs as superuser, so a lookup that silently returns nothing turns this
        whole suite green while checking nothing.
        """
        user = cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "email": "%s@test.com" % login,
                "group_ids": [Command.set([group.id])],
            }
        )
        assert user and isinstance(user.id, int) and user.id != 1, (
            "test user %s is not a real non-superuser account" % login
        )
        return user

    # --- the privilege ladder -------------------------------------------

    def test_readonly_is_implied_by_the_user_tier(self):
        self.assertIn(
            self.group_readonly,
            self.group_user.all_implied_ids,
            "the User tier must imply Read-only, or the readonly group cannot "
            "be used as a positive gate",
        )
        self.assertIn(self.group_readonly, self.group_manager.all_implied_ids)
        self.assertIn(self.group_readonly, self.user_stock.all_group_ids)
        self.assertIn(self.group_readonly, self.user_manager.all_group_ids)

    def test_readonly_readable_is_a_subset_of_user_readable(self):
        access = self.env["ir.model.access"]
        ours = access.search([("group_id", "=", self.group_readonly.id)])
        as_user = access.with_user(self.user_stock)
        offenders = [
            row.model_id.model
            for row in ours
            if not as_user.check(row.model_id.model, "read", False)
        ]
        self.assertFalse(
            offenders,
            "these models are readable by Read-only but not by a stock User, "
            "which inverts the tier order: %s" % offenders,
        )

    # --- server actions --------------------------------------------------

    def test_every_user_gated_server_action_reaches_readonly(self):
        """The regression test for the hook's old "stock.%" model filter.

        The hook searched ir.model for stock.% and so never saw the actions
        declared on product models.
        """
        actions = self.env["ir.actions.server"].search(
            [("group_ids", "in", self.group_user.ids)]
        )
        self.assertTrue(actions, "no group_stock_user server actions found")

        missing = []
        for action in actions:
            if self.group_readonly in action.group_ids:
                continue
            if action.get_external_id().get(action.id) in EXCLUDED_SERVER_ACTIONS:
                continue
            missing.append(action.get_external_id().get(action.id))

        self.assertFalse(
            missing,
            "server actions gated on the User tier that neither reach Read-only "
            "nor appear on the documented exclusion list: %s" % missing,
        )

    def test_excluded_server_actions_stay_denied(self):
        for xml_id in sorted(EXCLUDED_SERVER_ACTIONS):
            action = self.env.ref(xml_id)
            self.assertNotIn(
                self.group_readonly,
                action.group_ids,
                "%s must not reach the readonly tier" % xml_id,
            )

    def test_routes_diagram_action_is_runnable_by_readonly(self):
        action = self.env.ref("stock.action_open_routes")
        self.assertIn(self.group_readonly, action.group_ids)
        result = (
            action.with_user(self.user_readonly)
            .with_context(default_product_tmpl_id=self.product.product_tmpl_id.id)
            .run()
        )
        self.assertTrue(result, "the routes diagram action returned nothing")

    # --- ACL surface -----------------------------------------------------

    def test_readonly_can_read_but_not_write_stock_data(self):
        for model in ("stock.picking", "stock.move", "stock.quant"):
            as_readonly = self.env[model].with_user(self.user_readonly)
            self.assertIsInstance(as_readonly.search_count([]), int)
            access = self.env["ir.model.access"].with_user(self.user_readonly)
            self.assertTrue(access.check(model, "read", False), model)
            self.assertFalse(access.check(model, "write", False), model)
            self.assertFalse(access.check(model, "create", False), model)
            self.assertFalse(access.check(model, "unlink", False), model)

    def test_readonly_cannot_write_a_picking(self):
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "internal")], limit=1
        )
        if not picking_type:
            self.skipTest("no internal picking type in this database")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": picking_type.default_location_src_id.id
                or self.warehouse.lot_stock_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id
                or self.warehouse.lot_stock_id.id,
            }
        )
        with self.assertRaises(AccessError):
            picking.with_user(self.user_readonly).write({"note": "nope"})

    def test_models_read_through_base_group_user_stay_readable(self):
        """Guards the redundant-row deletion.

        Those rows were dropped because base.group_user already grants read.
        That grant is upstream's to change, so assert it rather than trust it.
        """
        access = self.env["ir.model.access"].with_user(self.user_readonly)
        lost = [
            model
            for model in READ_VIA_BASE_GROUP_USER
            if model in self.env and not access.check(model, "read", False)
        ]
        self.assertFalse(
            lost,
            "the readonly tier lost read on models whose explicit ACL rows were "
            "removed as redundant: %s" % lost,
        )

    # --- wizards ---------------------------------------------------------

    def test_readonly_can_run_the_read_only_report_wizards(self):
        access = self.env["ir.model.access"].with_user(self.user_readonly)
        for model in READ_ONLY_WIZARDS:
            self.assertTrue(access.check(model, "create", False), model)

        history = self.env["stock.quantity.history"].with_user(self.user_readonly)
        action = history.create({}).action_view_products_at_date()
        self.assertEqual(action["res_model"], "product.product")

        report = self.env["stock.traceability.report"].with_user(self.user_readonly)
        self.assertIsInstance(report.get_main_lines(), list)

        if self.warehouse:
            rules = self.env["stock.rules.report"].with_user(self.user_readonly)
            self.assertTrue(
                rules.create(
                    {
                        "product_id": self.product.id,
                        "product_tmpl_id": self.product.product_tmpl_id.id,
                        "warehouse_ids": [Command.set(self.warehouse.ids)],
                    }
                )
            )

    def test_readonly_cannot_reach_the_write_wizards(self):
        access = self.env["ir.model.access"].with_user(self.user_readonly)
        for model in WRITE_WIZARDS:
            self.assertFalse(access.check(model, "read", False), model)
            self.assertFalse(access.check(model, "create", False), model)

    # --- menus -----------------------------------------------------------

    def test_readonly_sees_the_patched_menus(self):
        menus = self.env["ir.ui.menu"].with_user(self.user_readonly).load_menus(False)
        visible = {
            entry.get("xmlid") for entry in menus.values() if isinstance(entry, dict)
        }
        for xml_id in (
            "stock.menu_stock_root",
            "stock.menu_stock_picking_incoming",
            "stock.menu_stock_picking_outgoing",
            "stock.menu_warehouse_report",
        ):
            self.assertIn(xml_id, visible, "%s is not visible to Read-only" % xml_id)

    # --- view affordances -------------------------------------------------

    def _form_arch(self, model, user, view_id=False, view_type="form"):
        views = self.env[model].with_user(user).get_views([(view_id, view_type)])
        return views["views"][view_type]["arch"]

    def _assert_write_buttons_gated(self, view_xmlid, model, view_type, buttons):
        """The gate is asserted where it is declared, and the tier where it lands.

        A stock User seeing the button is not asserted: a downstream module may
        narrow a write button further, and that is its decision. What stock
        owns is that each button is gated POSITIVELY on the User tier, which
        the readonly group does not carry, and that the rendered view for the
        tier drops it.
        """
        view = self.env.ref(view_xmlid)
        arch = etree.fromstring(view.arch)
        for button in buttons:
            nodes = arch.xpath(f"//button[@name='{button}']")
            self.assertTrue(nodes, f"{button} is not in {view_xmlid}")
            for node in nodes:
                self.assertEqual(
                    node.get("groups"),
                    "stock.group_stock_user",
                    f"{button} must be gated positively on the User tier",
                )
        readonly_arch = self._form_arch(model, self.user_readonly, view.id, view_type)
        for button in buttons:
            self.assertNotIn(button, readonly_arch, button)
        return readonly_arch

    def test_picking_write_buttons_are_hidden_from_readonly(self):
        self._assert_write_buttons_gated(
            "stock.view_stock_picking_form",
            "stock.picking",
            "form",
            ("action_confirm", "action_assign", "action_cancel"),
        )

    def test_inventory_write_buttons_are_hidden_from_readonly(self):
        readonly_arch = self._assert_write_buttons_gated(
            "stock.view_stock_quant_list_inventory_editable",
            "stock.quant",
            "list",
            (
                "action_apply_all",
                "action_apply_inventory",
                "action_clear_inventory_quantity",
                "stock.action_stock_inventory_adjustement_name",
            ),
        )
        # The history button only reads, so it stays for everyone.
        self.assertIn("action_inventory_history", readonly_arch)
