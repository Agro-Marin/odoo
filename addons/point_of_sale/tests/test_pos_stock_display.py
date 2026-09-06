import importlib.util
from pathlib import Path

from odoo.tests import Form, HttpCase, TransactionCase, tagged

UPGRADE_SCRIPT = (
    Path(__file__).parents[1]
    / "upgrades"
    / "1.0.3"
    / "pre-dissolve-pos-stock-and-grouped-lines.py"
)


def load_upgrade_script():
    spec = importlib.util.spec_from_file_location(
        "pos_dissolve_upgrade", UPGRADE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestPosStockQuantities(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Warehouse = cls.env["stock.warehouse"]
        cls.warehouse = Warehouse.search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.other_warehouse = Warehouse.create({"name": "Other", "code": "OTH"})
        cls.stock = cls.warehouse.lot_stock_id
        cls.shelf = cls.env["stock.location"].create(
            {"name": "Shelf", "usage": "internal", "location_id": cls.stock.id}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Counted", "type": "consu", "is_storable": True}
        )
        cls.service = cls.env["product.product"].create(
            {"name": "Service", "type": "service"}
        )
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.product, cls.stock, 5)
        Quant._update_available_quantity(cls.product, cls.shelf, 7)
        Quant._update_available_quantity(
            cls.product, cls.other_warehouse.lot_stock_id, 3
        )
        cls.config = cls.env["pos.config"].create({"name": "Stock POS"})
        cls.cashier = cls.env["res.users"].create(
            {
                "name": "Cashier",
                "login": "pos_stock_display_cashier",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("point_of_sale.group_pos_user").id,
                        ],
                    )
                ],
            }
        )

    def quantities(self, product_ids=None, user=None):
        Product = self.env["product.product"].with_user(user or self.env.user)
        if product_ids is None:
            product_ids = [self.product.id]
        return Product.get_pos_stock_quantities(product_ids, self.config.id)

    def stock_user(self, login):
        user = self.cashier.copy({"login": login})
        user.group_ids = [(4, self.env.ref("stock.group_stock_user").id)]
        return user

    def test_no_scope_counts_every_warehouse(self):
        self.assertEqual(self.quantities(), {self.product.id: 15.0})

    def test_warehouse_scope_includes_its_child_locations(self):
        self.config.stock_warehouse_id = self.warehouse
        self.assertEqual(self.quantities(), {self.product.id: 12.0})

    def test_location_scope_includes_children_of_a_selected_parent(self):
        self.config.stock_warehouse_id = self.warehouse
        self.config.stock_location_ids = self.stock
        self.assertEqual(self.quantities(), {self.product.id: 12.0})

    def test_location_scope_is_exact_for_a_leaf(self):
        self.config.stock_warehouse_id = self.warehouse
        self.config.stock_location_ids = self.shelf
        self.assertEqual(self.quantities(), {self.product.id: 7.0})

    def test_locations_win_over_the_warehouse(self):
        self.config.stock_warehouse_id = self.other_warehouse
        self.config.stock_location_ids = self.shelf
        self.assertEqual(self.quantities(), {self.product.id: 7.0})

    def test_services_missing_ids_and_empty_input_read_zero(self):
        missing = self.product.id + 100_000
        self.assertEqual(
            self.quantities([self.service.id, missing]),
            {self.service.id: 0.0, missing: 0.0},
        )
        self.assertEqual(self.quantities([]), {})

    def test_a_cashier_without_stock_rights_can_read_quantities(self):
        self.assertFalse(self.cashier.has_group("stock.group_stock_user"))
        self.assertEqual(self.quantities(user=self.cashier), {self.product.id: 15.0})

    def test_changing_the_warehouse_clears_the_locations(self):
        self.config.write(
            {
                "stock_warehouse_id": self.warehouse.id,
                "stock_location_ids": [(6, 0, self.shelf.ids)],
            }
        )
        with Form(self.config) as form:
            form.stock_warehouse_id = self.other_warehouse
        self.assertFalse(self.config.stock_location_ids)
        self.assertEqual(
            self.config.stock_warehouse_view_location_id,
            self.other_warehouse.view_location_id,
        )

    def test_pos_data_carries_the_display_settings(self):
        self.config.write(
            {
                "stock_warehouse_id": self.warehouse.id,
                "stock_location_ids": [(6, 0, self.shelf.ids)],
                "stock_display_location": "bottom_right",
                "low_stock_threshold": 3.5,
            }
        )
        data = self.env["pos.config"]._load_pos_data_read(self.config, self.config)[0]
        self.assertTrue(data["show_stock_in_pos"])
        self.assertEqual(data["stock_display_location"], "bottom_right")
        self.assertEqual(data["low_stock_threshold"], 3.5)
        self.assertEqual(data["stock_warehouse_id"], self.warehouse.id)
        self.assertEqual(data["stock_location_ids"], self.shelf.ids)

    def test_an_outgoing_block_hides_the_location_from_a_cashier_only(self):
        self.shelf.block_type = "soft_out"
        self.config.stock_warehouse_id = self.warehouse
        self.assertEqual(self.quantities(user=self.cashier), {self.product.id: 5.0})
        stock_user = self.stock_user("pos_stock_display_stock_user")
        self.assertEqual(self.quantities(user=stock_user), {self.product.id: 12.0})

    def test_stock_locations_follow_the_same_scope_as_the_quantities(self):
        Location = self.env["stock.location"]
        company_roots = (
            self.env["stock.warehouse"]
            .search([("company_id", "in", self.env.companies.ids)])
            .view_location_id
        )
        every_internal = Location.search(
            [("location_id", "child_of", company_roots.ids), ("usage", "=", "internal")]
        )
        self.assertEqual(self.config._get_stock_locations(), every_internal)
        self.assertIn(self.shelf, every_internal)

        self.config.stock_warehouse_id = self.warehouse
        in_warehouse = self.config._get_stock_locations()
        self.assertIn(self.stock, in_warehouse)
        self.assertIn(self.shelf, in_warehouse)
        self.assertNotIn(self.other_warehouse.lot_stock_id, in_warehouse)

        self.config.stock_location_ids = self.stock
        self.assertEqual(self.config._get_stock_locations(), self.stock | self.shelf)

        self.config.stock_location_ids = self.shelf
        self.assertEqual(self.config._get_stock_locations(), self.shelf)

    def test_a_blocked_location_leaves_a_cashier_scope_and_stays_in_a_stock_users(self):
        self.shelf.block_type = "soft_out"
        self.config.stock_warehouse_id = self.warehouse
        as_cashier = self.config.with_user(self.cashier)._get_stock_locations()
        self.assertNotIn(self.shelf, as_cashier)
        self.assertIn(self.stock, as_cashier)
        stock_user = self.stock_user("pos_stock_display_stock_user_2")
        self.assertIn(
            self.shelf, self.config.with_user(stock_user)._get_stock_locations()
        )


@tagged("post_install", "-at_install")
class TestDissolvedModulesUpgrade(TransactionCase):
    DISSOLVED = ("pos_product_stock", "pos_orderline_grouped_product")

    def setUp(self):
        super().setUp()
        self.upgrade = load_upgrade_script()
        self.config = self.env["pos.config"].create({"name": "Dissolved POS"})
        for name in self.DISSOLVED:
            self.env.cr.execute(
                """
                INSERT INTO ir_module_module (name, state)
                     VALUES (%s, 'installed')
                ON CONFLICT (name) DO UPDATE SET state = 'installed'
                """,
                [name],
            )

    def module_state(self, name):
        self.env.cr.execute(
            "SELECT state FROM ir_module_module WHERE name = %s", [name]
        )
        return self.env.cr.fetchone()[0]

    def xmlid_owner(self, model, name):
        self.env.cr.execute(
            "SELECT module FROM ir_model_data WHERE model = %s AND name = %s",
            [model, name],
        )
        return sorted(row[0] for row in self.env.cr.fetchall())

    def test_both_modules_are_retired_and_the_fields_change_owner(self):
        self.env.cr.execute(
            """
            UPDATE ir_model_data SET module = 'pos_product_stock'
             WHERE module = 'point_of_sale' AND model = 'ir.model.fields'
               AND name = 'field_pos_config__show_stock_in_pos'
            """
        )
        self.env.cr.execute(
            """
            INSERT INTO ir_model_data (module, model, name, res_id, noupdate)
                 SELECT 'pos_product_stock', model, name, res_id, noupdate
                   FROM ir_model_data
                  WHERE module = 'point_of_sale' AND model = 'ir.model.fields'
                    AND name = 'field_pos_config__low_stock_threshold'
            """
        )
        self.upgrade.migrate(self.env.cr, "1.0.2")

        for name in self.DISSOLVED:
            self.assertEqual(self.module_state(name), "uninstalled")
        self.assertEqual(
            self.xmlid_owner("ir.model.fields", "field_pos_config__show_stock_in_pos"),
            ["point_of_sale"],
        )
        self.assertEqual(
            self.xmlid_owner(
                "ir.model.fields", "field_pos_config__low_stock_threshold"
            ),
            ["point_of_sale"],
        )
        self.env.cr.execute(
            "SELECT count(*) FROM ir_model_data WHERE module = 'pos_product_stock'"
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_the_inheriting_view_is_deleted_rather_than_adopted(self):
        view = self.env["ir.ui.view"].create(
            {
                "name": "dissolved stock display",
                "model": "pos.config",
                "inherit_id": self.env.ref("point_of_sale.pos_config_view_form").id,
                "arch": "<data/>",
            }
        )
        self.env["ir.model.data"].create(
            {
                "module": "pos_product_stock",
                "name": "view_pos_config_form_stock_display",
                "model": "ir.ui.view",
                "res_id": view.id,
            }
        )
        self.upgrade.migrate(self.env.cr, "1.0.2")
        self.assertFalse(view.exists())

    def test_a_warehouse_of_another_company_is_cleared(self):
        other_company = self.env["res.company"].create({"name": "Elsewhere"})
        foreign_warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", other_company.id)], limit=1
        )
        self.env.cr.execute(
            "UPDATE pos_config SET stock_warehouse_id = %s WHERE id = %s",
            [foreign_warehouse.id, self.config.id],
        )
        self.env.cr.execute(
            "INSERT INTO pos_config_stock_location_rel (config_id, location_id) VALUES (%s, %s)",
            [self.config.id, foreign_warehouse.lot_stock_id.id],
        )
        self.config.invalidate_recordset()

        self.upgrade.migrate(self.env.cr, "1.0.2")

        self.config.invalidate_recordset()
        self.assertFalse(self.config.stock_warehouse_id)
        self.assertFalse(self.config.stock_location_ids)

    def test_a_database_that_never_had_the_modules_is_left_alone(self):
        self.env.cr.execute(
            "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = ANY(%s)",
            [list(self.DISSOLVED)],
        )
        self.config.stock_warehouse_id = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        self.upgrade.migrate(self.env.cr, "1.0.2")
        self.config.invalidate_recordset()
        self.assertTrue(self.config.stock_warehouse_id)


@tagged("post_install", "-at_install")
class TestPosStockBadges(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env["product.product"]
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        shelf = cls.env["stock.location"].create(
            {
                "name": "Badge Shelf",
                "usage": "internal",
                "location_id": warehouse.lot_stock_id.id,
            }
        )
        category = cls.env["pos.category"].create({"name": "Badges"})

        def product(name, stock=0.0, shelf_qty=0.0):
            record = Product.create(
                {
                    "name": name,
                    "type": "consu",
                    "is_storable": True,
                    "available_in_pos": True,
                    "list_price": 1.0,
                    "pos_categ_ids": [(6, 0, category.ids)],
                }
            )
            if stock:
                cls.env["stock.quant"]._update_available_quantity(
                    record, warehouse.lot_stock_id, stock
                )
            if shelf_qty:
                cls.env["stock.quant"]._update_available_quantity(
                    record, shelf, shelf_qty
                )
            return record

        cls.plenty = product("Badge Plenty", stock=50, shelf_qty=25)
        cls.low = product("Badge Low", stock=3)
        cls.empty = product("Badge Empty")
        cls.config = cls.env["pos.config"].create(
            {
                "name": "Badge POS",
                "stock_warehouse_id": warehouse.id,
                "stock_display_location": "bottom_right",
            }
        )

    def test_badges_render_from_the_real_bundle(self):
        self.config.open_ui()
        self.config.current_session_id.set_opening_control(0, "")
        self.authenticate("admin", "admin")
        self.browser_js(
            f"/pos/ui?config_id={self.config.id}",
            """
            const fail = (message) => { throw new Error(message); };
            const byName = (name) => [...document.querySelectorAll("article.product")]
                .find((card) => card.querySelector(".product-name").textContent.trim() === name);
            const badge = (name) => byName(name)?.querySelector(".o_pos_stock_badge");
            const check = () => {
                const plenty = badge("Badge Plenty");
                if (!plenty) fail("no badge on the template card");
                if (plenty.textContent.trim() !== "75") fail(`expected 75, got ${plenty.textContent}`);
                if (!plenty.classList.contains("o_pos_stock_available")) fail(`plenty class ${plenty.className}`);
                if (!plenty.classList.contains("bottom-0") || !plenty.classList.contains("end-0")) fail(`position ${plenty.className}`);
                const low = badge("Badge Low");
                if (low.textContent.trim() !== "3" || !low.classList.contains("o_pos_stock_low")) fail(`low ${low.outerHTML}`);
                const empty = badge("Badge Empty");
                if (empty.textContent.trim() !== "0" || !empty.classList.contains("o_pos_stock_empty")) fail(`empty ${empty.outerHTML}`);
                console.log("test successful");
            };
            const started = Date.now();
            const poll = () => {
                document.querySelector(".open-register-btn")?.click();
                const ready = document.querySelector(".o_pos_stock_available") && document.querySelector(".o_pos_stock_empty");
                if (ready) return check();
                if (Date.now() - started > 60000) fail("badges never rendered; body: " + document.body.innerText.replace(/\\s+/g, " ").slice(0, 300));
                setTimeout(poll, 250);
            };
            poll();
            """,
            ready="document.readyState === 'complete'",
            login="admin",
            timeout=120,
        )
