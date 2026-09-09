from lxml import etree

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged

# The menus `views/sale_menus.xml` opens to the tier, and the core group each one
# already carried. Granting must add the role, never displace who had it.
CORE_GROUP_PER_GRANTED_MENU = {
    "sale.menu_sale_quotations": "sales_team.group_sale_salesman",
    "sale.menu_sale_order": "sales_team.group_sale_salesman",
    "sale.res_partner_menu": "sales_team.group_sale_salesman",
    "sale.product_menu_catalog": "sales_team.group_sale_salesman",
    "sale.menu_sale_report": "sales_team.group_sale_manager",
}

# Menus core gates on a Settings feature flag rather than on a role. The tier
# used to be granted these too, which showed them with the flag off.
FEATURE_FLAG_MENUS = {
    "sale.menu_products": "product.group_product_variant",
    "sale.menu_product_pricelist_main": "product.group_product_pricelist",
}

# The role is meant to sit *below* a salesperson, so anything it sees that a
# salesperson cannot is drift. These three are the known, deliberate exceptions.
# Shrink this list, never grow it without a decision behind the entry.
MENUS_THE_ROLE_MAY_SEE_ALONE = {
    # Reporting is the one entry that genuinely belongs to a read-only role.
    "sale.menu_sale_report",
    # Consequences of the account.move / account.payment grants. Both disappear
    # once the accounting surface of the role is decided (audit finding F03).
    "account.menu_action_account_payments_receivable",
    "account.menu_action_account_payments_payable",
}


@tagged("post_install", "-at_install")
class TestSaleGroupReadonly(TransactionCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

        cls.group_readonly = cls.env.ref("sales_team.group_sale_readonly")

        # Built from the group alone on purpose: passing `base.group_user`
        # explicitly would satisfy `test_readonly_user_is_an_internal_user` even
        # if the group stopped implying it.
        cls.user_readonly = cls.env["res.users"].create(
            {
                "name": "Test Sale Readonly User",
                "login": "test_sale_readonly",
                "email": "test_sale_readonly@test.com",
                "group_ids": [Command.set([cls.group_readonly.id])],
            }
        )

        cls.user_salesman = cls.env["res.users"].create(
            {
                "name": "Test Sale Salesman",
                "login": "test_sale_salesman",
                "email": "test_sale_salesman@test.com",
                "group_ids": [
                    Command.set(
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("sales_team.group_sale_salesman").id,
                        ]
                    )
                ],
            }
        )

        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test Customer",
            }
        )

        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "list_price": 100.0,
            }
        )

        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "user_id": cls.user_salesman.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": 1.0,
                            "price_unit": 100.0,
                        }
                    )
                ],
            }
        )

    def test_group_is_a_role_under_the_sales_privilege(self) -> None:
        """Pin what the group *is*, not what it is called.

        `setUpClass` already fails the whole class if the xmlid is missing, and
        the label is translatable, so neither carried information.
        """
        self.assertEqual(
            self.group_readonly.privilege_id,
            self.env.ref("sales_team.res_groups_privilege_sales"),
            "the role must sit under the Sales privilege",
        )
        self.assertIn(
            self.env.ref("base.group_user"),
            self.group_readonly.all_implied_ids,
            "the group must imply base.group_user (sales_team/security/sales_team_security.xml)",
        )

    def test_readonly_user_is_an_internal_user(self) -> None:
        """The group alone has to be enough to make an internal user."""
        self.assertIn(
            self.env.ref("base.group_user"),
            self.user_readonly.all_group_ids,
            "holding only the role must still grant base.group_user",
        )

    def test_readonly_user_can_read_sale_order(self) -> None:
        order = self.sale_order.with_user(self.user_readonly)
        order.read(["partner_id", "amount_total"])

    def test_readonly_user_cannot_create_sale_order(self) -> None:
        sale_order_env = self.env["sale.order"].with_user(self.user_readonly)
        with self.assertRaises(AccessError):
            sale_order_env.create(
                {
                    "partner_id": self.partner.id,
                }
            )

    def test_readonly_user_cannot_write_sale_order(self) -> None:
        order = self.sale_order.with_user(self.user_readonly)
        with self.assertRaises(AccessError):
            order.write({"client_order_ref": "Test ref"})

    def test_readonly_user_cannot_unlink_sale_order(self) -> None:
        order = self.sale_order.with_user(self.user_readonly)
        with self.assertRaises(AccessError):
            order.unlink()

    def test_readonly_user_can_read_order_lines(self) -> None:
        lines = self.sale_order.line_ids.with_user(self.user_readonly)
        lines.read(["product_id", "product_uom_qty", "price_unit"])

    def test_the_all_documents_rung_implies_readonly(self) -> None:
        """The lowest rung that already sees every document implies the tier.

        Not the salesperson: the tier's read rules OR with the personal rule,
        so a narrower rung implying it would read every order through it.
        """
        all_documents = self.env.ref("sales_team.group_sale_salesman_all_leads")
        salesman = self.env.ref("sales_team.group_sale_salesman")
        manager = self.env.ref("sales_team.group_sale_manager")
        self.assertIn(self.group_readonly, all_documents.implied_ids)
        self.assertIn(self.group_readonly, manager.all_implied_ids)
        self.assertNotIn(self.group_readonly, salesman.all_implied_ids)

    def test_readonly_reads_every_order_whatever_else_it_holds(self) -> None:
        """The tier is a decision to see everything, stated as a read rule.

        Without it a salesperson given the tier would stay narrowed to their own
        orders by the personal rule, and a reader holding the tier alone would
        see everything only because no rule applied to them.
        """
        other_order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "user_id": self.env.ref("base.user_admin").id,
            }
        )
        with self.assertRaises(AccessError):
            other_order.with_user(self.user_salesman).read(["id"])
        self.user_salesman.write({"group_ids": [Command.link(self.group_readonly.id)]})
        other_order.with_user(self.user_salesman).read(["id"])
        with self.assertRaises(AccessError):
            other_order.with_user(self.user_salesman).write({"client_order_ref": "x"})
        other_order.with_user(self.user_readonly).read(["id"])

    def test_salesman_can_read_sale_order(self) -> None:
        order = self.sale_order.with_user(self.user_salesman)
        order.read(["partner_id", "amount_total"])

    def test_salesman_can_write_sale_order(self) -> None:
        order = self.sale_order.with_user(self.user_salesman)
        order.write({"client_order_ref": "Regression test ref"})

    # --- the menu grants, which no test covered before ---

    def test_granted_menus_are_visible_to_the_role(self) -> None:
        """Every menu opened to the role must be reachable by it."""
        visible = (
            self.env["ir.ui.menu"].with_user(self.user_readonly)._get_visible_menu_ids()
        )
        for xmlid in CORE_GROUP_PER_GRANTED_MENU:
            menu = self.env.ref(xmlid)
            # A downstream module may retire a menu; an inactive one is visible
            # to nobody, and that says nothing about the grant.
            if not menu.active:
                continue
            self.assertIn(
                menu.id,
                visible,
                f"{xmlid} is granted but the role cannot see it",
            )

    def test_menu_grants_do_not_displace_the_core_group(self) -> None:
        """A grant must add the role, never replace who already had the menu.

        A previous round shipped records that dropped the core group and blocked
        18 salespeople in production; `Command.link` is what prevents a repeat.
        """
        for xmlid, core_group_xmlid in CORE_GROUP_PER_GRANTED_MENU.items():
            group_ids = self.env.ref(xmlid).group_ids
            self.assertIn(
                self.env.ref(core_group_xmlid),
                group_ids,
                f"{xmlid} lost its core group {core_group_xmlid}",
            )
            self.assertIn(self.group_readonly, group_ids, f"{xmlid} lost the role")

    def test_feature_flag_menus_stay_behind_their_flag(self) -> None:
        """The role must not reach menus gated on a Settings checkbox.

        Those groups are feature flags, not roles: OR-ing the role onto them
        showed the menus with the flag off, and showed them to the role when a
        salesperson could not see them. Switching a flag on hands it to every
        internal user through base.group_user, so the contract is that the role
        holds a flag exactly when base.group_user does, and sees the menu
        exactly when it holds the flag.
        """
        visible = (
            self.env["ir.ui.menu"].with_user(self.user_readonly)._get_visible_menu_ids()
        )
        group_user = self.env.ref("base.group_user")
        for xmlid, flag_xmlid in FEATURE_FLAG_MENUS.items():
            flag = self.env.ref(flag_xmlid)
            flag_is_on = flag in group_user.all_implied_ids
            self.assertEqual(
                flag in self.user_readonly.all_group_ids,
                flag_is_on,
                f"the role must hold the feature flag {flag_xmlid} only through "
                "base.group_user",
            )
            menu = self.env.ref(xmlid)
            self.assertEqual(
                menu.id in visible,
                flag_is_on and menu.active,
                f"{xmlid} must follow the flag {flag_xmlid}, not the role",
            )

    def test_role_outranks_a_salesperson_only_where_intended(self) -> None:
        """The role sits below a salesperson, so extra menus are drift.

        Pinned as an explicit allowance rather than a free pass: a new entry
        appearing here fails the suite and has to be argued for.
        """
        menu_model = self.env["ir.ui.menu"]
        visible_readonly = menu_model.with_user(
            self.user_readonly
        )._get_visible_menu_ids()
        visible_salesman = menu_model.with_user(
            self.user_salesman
        )._get_visible_menu_ids()
        allowed_roots = [
            menu.id
            for menu in (
                self.env.ref(xmlid, raise_if_not_found=False)
                for xmlid in MENUS_THE_ROLE_MAY_SEE_ALONE
            )
            if menu
        ]
        # Allowing a menu allows what hangs under it: a child with no groups of
        # its own is visible to whoever sees the parent, and that was decided
        # once, at the parent.
        allowed = set(menu_model.search([("id", "child_of", allowed_roots)]).ids)
        unexpected = sorted(
            menu_model.browse(menu_id).complete_name
            for menu_id in set(visible_readonly) - set(visible_salesman) - allowed
        )
        self.assertFalse(
            unexpected,
            f"the role sees menus a salesperson cannot, and nobody decided to: "
            f"{unexpected}",
        )

    # --- the ACL surface, which no test covered before ---

    def test_every_acl_row_grants_something(self) -> None:
        """No row may duplicate access `base.group_user` already has.

        Asserted as a property rather than a pinned list so the file cannot
        silently drift back: 24 of the original 60 rows were dead this way.

        A duplicate is judged against the modules the row's own module can
        see. website_event opens events to every employee, which makes
        event_sale's rows redundant in an install carrying it and necessary in
        one that does not; a row is dead only when a module in its own
        dependency closure already grants the read.
        """
        group_user = self.env.ref("base.group_user")
        access = self.env["ir.model.access"]
        module_model = self.env["ir.module.module"]
        closures = {}
        dead = []
        for row in self._tier_acl_rows():
            row_module = row.get_external_id()[row.id].split(".")[0]
            if row_module not in closures:
                module = module_model.search([("name", "=", row_module)])
                closures[row_module] = {row_module} | set(
                    module.upstream_dependencies(
                        exclude_states=("uninstalled", "uninstallable", "to remove")
                    ).mapped("name")
                )
            granting = access.search(
                [
                    ("model_id", "=", row.model_id.id),
                    ("group_id", "=", group_user.id),
                    ("perm_read", "=", True),
                ]
            )
            granting_modules = {
                xmlid.split(".")[0] for xmlid in granting.get_external_id().values()
            }
            if granting_modules & closures[row_module]:
                dead.append(row.model_id.model)
        self.assertFalse(
            dead, f"these rows grant nothing over base.group_user: {sorted(dead)}"
        )

    def test_no_acl_row_targets_a_transient_model(self) -> None:
        """A wizard is entered by creating a record, and the role cannot create.

        So a read row on a TransientModel can never take effect.
        """
        transient = [
            row.model_id.model
            for row in self._tier_acl_rows()
            if self.env[row.model_id.model]._transient
        ]
        self.assertFalse(
            transient,
            f"read rows on transient models never apply: {sorted(transient)}",
        )

    def test_acl_rows_grant_read_only(self) -> None:
        """The role is read-only; no row may hand it a write bit."""
        writable = [
            row.model_id.model
            for row in self._tier_acl_rows()
            if row.perm_write or row.perm_create or row.perm_unlink
        ]
        self.assertFalse(writable, f"these rows are not read-only: {sorted(writable)}")

    def _tier_acl_rows(self):
        rows = self.env["ir.model.access"].search(
            [("group_id", "=", self.group_readonly.id)]
        )
        self.assertTrue(rows, "the tier must grant something")
        return rows

    def _assert_write_buttons_gated(
        self, view_xmlid, model, rung, buttons, user, feature_flags=()
    ):
        """The gate is asserted where it is declared, and the tier where it lands.

        Each write button is gated POSITIVELY on the transacting rung, which the
        tier does not carry, and the rendered form for the tier drops it.
        """
        view = self.env.ref(view_xmlid)
        arch = etree.fromstring(view.arch)
        for button in buttons:
            nodes = arch.xpath(f"//header/button[@name='{button}']")
            self.assertTrue(nodes, f"{button} is not in {view_xmlid}")
            for node in nodes:
                # A feature-flag gate stays as it is: `groups` is an OR, so
                # adding the rung would show the button to every salesperson
                # with the flag off.
                if node.get("groups") in feature_flags:
                    continue
                self.assertEqual(node.get("groups"), rung, button)
        views = self.env[model].with_user(user).get_views([(view.id, "form")])
        rendered = views["views"]["form"]["arch"]
        for button in buttons:
            self.assertNotIn(f'name="{button}"', rendered, button)

    def test_order_write_buttons_are_hidden_from_readonly(self) -> None:
        self._assert_write_buttons_gated(
            "sale.view_sale_order_form",
            "sale.order",
            "sales_team.group_sale_salesman",
            (
                "action_send_quotation",
                "action_confirm",
                "payment_action_capture",
                "payment_action_void",
                "action_cancel",
                "action_draft",
            ),
            self.user_readonly,
            feature_flags=("sale.group_proforma_sales",),
        )
