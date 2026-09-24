import re

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.product.tests.common import ProductVariantsCommon

RECEPTION_ROUTE_BOUGHT = "purchase_stock replaces the reception pull rule by a buy rule"


def is_module_installed(env, name):
    return env["ir.module.module"]._get(name).state == "installed"


GENERATED_LINE_FIELDS = (
    "picking_id",
    "product_id",
    "product_uom_id",
    "location_id",
    "location_dest_id",
    "lot_id",
    "lot_name",
    "quantity",
    "expiration_date",
)


def generate_lot_lines(
    move,
    mode="generate",
    first_lot="",
    count=0,
    lot_text="",
    keep_lines=False,
    quantity=None,
    context=None,
):
    MoveLine = move.env["stock.move.line"]
    replaced = MoveLine if keep_lines else move.move_line_ids
    is_lot = move.has_tracking == "lot"
    context_data = {
        **(context or {}),
        "default_product_id": move.product_id.id,
        "default_location_id": move.location_id.id,
        "default_location_dest_id": move.location_dest_id.id,
        "default_tracking": move.has_tracking,
        "default_quantity": quantity if quantity is not None else move.quantity,
        "default_picking_id": move.picking_id.id,
        "default_picking_type_id": move.picking_type_id.id,
        "default_company_id": move.company_id.id,
        "exclude_sml_ids": replaced.ids,
    }
    if is_lot:
        context_data["default_uom_id"] = move.product_uom_id.id
    vals_list = move.env["stock.move"].action_generate_lot_line_vals(
        context_data, mode, first_lot, count, lot_text
    )
    commands = [Command.delete(line.id) for line in replaced]
    for vals in vals_list:
        line_vals = {
            name: value["id"] if isinstance(value, dict) else value
            for name, value in vals.items()
            if name in GENERATED_LINE_FIELDS and name in MoveLine._fields
        }
        commands.append(Command.create(line_vals))
    move.write({"move_line_ids": commands})
    return move.move_line_ids


class TestStockCommon(ProductVariantsCommon):
    def _create_move(self, product, src_location, dst_location, **values):
        Move = self.env["stock.move"].with_user(self.user_stock_manager)
        move = Move.new(
            {
                "product_id": product.id,
                "location_id": src_location.id,
                "location_dest_id": dst_location.id,
            }
        )
        move_values = move._convert_to_write(move._cache)
        move_values.update(**values)
        return Move.create(move_values)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.uom_dunit = cls.env["uom.uom"].create(
            {
                "name": "DeciUnit",
                "relative_factor": 10.0,
                "relative_uom_id": cls.uom_unit.id,
            }
        )

        cls.product_1, cls.product_2, cls.product_3 = cls.env["product.product"].create(
            [
                {
                    "name": "Courage",
                    "type": "consu",
                    "default_code": "PROD-1",
                    "uom_id": cls.uom_dunit.id,
                },
                {
                    "name": "Wood",
                },
                {
                    "name": "Stone",
                    "uom_id": cls.uom_dozen.id,
                },
            ]
        )

        cls.ProductObj = cls.env["product.product"]
        cls.UomObj = cls.env["uom.uom"]
        cls.PartnerObj = cls.env["res.partner"]
        cls.ModelDataObj = cls.env["ir.model.data"]
        cls.StockPackObj = cls.env["stock.move.line"]
        cls.StockQuantObj = cls.env["stock.quant"]
        cls.PickingObj = cls.env["stock.picking"]
        cls.MoveObj = cls.env["stock.move"]
        cls.LotObj = cls.env["stock.lot"]
        cls.StockLocationObj = cls.env["stock.location"]

        cls.warehouse_1 = cls.env["stock.warehouse"].create(
            {
                "name": "Base Warehouse",
                "reception_steps": "one_step",
                "delivery_steps": "ship_only",
                "code": "BWH",
                "sequence": 5,
            }
        )
        cls.route_mto = cls.warehouse_1.mto_pull_id.route_id
        cls.route_mto.rule_ids.procure_method = "make_to_order"

        cls.picking_type_in = cls.warehouse_1.in_type_id
        cls.picking_type_int = cls.warehouse_1.int_type_id
        cls.picking_type_out = cls.warehouse_1.out_type_id
        cls.picking_type_out.reservation_method = "manual"

        cls.stock_location = cls.warehouse_1.lot_stock_id
        cls.scrap_location = cls.StockLocationObj.search(
            [
                ("company_id", "=", cls.warehouse_1.company_id.id),
                ("usage", "=", "inventory"),
            ],
            limit=1,
        )
        cls.shelf_1, cls.shelf_2 = cls.StockLocationObj.create(
            [
                {
                    "name": "Shelf 1",
                    "location_id": cls.stock_location.id,
                },
                {
                    "name": "Shelf 2",
                    "location_id": cls.stock_location.id,
                },
            ]
        )

        pack_location = cls.warehouse_1.wh_pack_stock_loc_id
        pack_location.active = True
        cls.pack_location = pack_location
        output_location = cls.warehouse_1.wh_output_stock_loc_id
        output_location.active = True
        cls.output_location = output_location

        cls.supplier_location = cls.quick_ref("stock.stock_location_suppliers")
        cls.customer_location = cls.quick_ref("stock.stock_location_customers")
        cls.inter_company_location = cls.quick_ref("stock.stock_location_inter_company")

        (
            cls.productA,
            cls.productB,
            cls.productC,
            cls.productD,
            cls.productE,
        ) = cls.ProductObj.create(
            [
                {"name": "Product A", "is_storable": True},
                {"name": "Product B", "is_storable": True},
                {"name": "Product C", "is_storable": True},
                {"name": "Product D", "is_storable": True},
                {"name": "Product E", "is_storable": True},
            ]
        )

        cls.uom_kg = cls.uom_kgm
        cls.uom_gm = cls.uom_gram

        cls.kgB, cls.gB = cls.ProductObj.create(
            [
                {"name": "kg-B", "is_storable": True, "uom_id": cls.uom_kg.id},
                {"name": "g-B", "is_storable": True, "uom_id": cls.uom_gm.id},
            ]
        )

        cls.group_user.write(
            {
                "implied_ids": [
                    (4, cls.quick_ref("base.group_multi_company").id),
                    (4, cls.quick_ref("stock.group_production_lot").id),
                ]
            }
        )

        cls.user_stock_user = mail_new_test_user(
            cls.env,
            name="Pauline Poivraisselle",
            login="pauline",
            email="p.p@example.com",
            notification_type="inbox",
            groups="stock.group_stock_user",
        )
        cls.user_stock_manager = mail_new_test_user(
            cls.env,
            name="Julie Tablier",
            login="julie",
            email="j.j@example.com",
            notification_type="inbox",
            groups="stock.group_stock_manager",
        )

        cls.partner_1 = cls.env["res.partner"].create(
            {
                "name": "Julia Agrolait",
                "email": "julia@agrolait.example.com",
            }
        )

        cls.existing_inventories = cls.StockQuantObj.search(
            [("inventory_quantity", "!=", 0.0)]
        )
        cls.existing_quants = cls.StockQuantObj.search([])

    def url_extract_rec_id_and_model(self, url):
        action_match = re.findall(r"action-([^/]+)", url)
        model_name = self.env.ref(action_match[0]).res_model
        rec_id = re.findall(r"/(\d+)$", url)[0]
        return rec_id, model_name


class DoneMoveCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.Location = cls.env["stock.location"]
        cls.Product = cls.env["product.product"]
        cls.Lot = cls.env["stock.lot"]

    def _done_move(self, product, quantity, source, dest, line_vals=None):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "location_id": source.id,
                "location_dest_id": dest.id,
            },
        )
        move._action_confirm()
        if line_vals is None:
            move._action_assign()
        else:
            move.move_line_ids.unlink()
            move.move_line_ids = [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "quantity": quantity,
                        "location_id": source.id,
                        "location_dest_id": dest.id,
                        **line_vals,
                    },
                )
            ]
        move.picked = True
        move._action_done()
        return move

    def _backdate(self, moves, days):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE stock_move SET date = now() - make_interval(days => %s)"
            " WHERE id = ANY(%s)",
            [days, moves.ids],
        )
        self.env.invalidate_all()


class LocationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Location = cls.env["stock.location"]
        cls.Quant = cls.env["stock.quant"]
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.group_hard_override = cls.env.ref("stock.group_override_hard_block")

    @classmethod
    def _create_product(cls, name, weight=1.0, **vals):
        return cls.env["product.product"].create(
            {"name": name, "is_storable": True, "weight": weight, **vals},
        )

    @classmethod
    def _create_location(cls, name, parent=None, **vals):
        return cls.Location.create(
            {
                "name": name,
                "location_id": (parent or cls.stock_location).id,
                "usage": "internal",
                **vals,
            },
        )

    def _create_user(self, login, *groups):
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("stock.group_stock_manager").id,
                            *[group.id for group in groups],
                        ],
                    ),
                ],
            },
        )


@tagged("post_install", "-at_install")
class TestMoveLineCommon(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MoveLine = cls.env["stock.move.line"]
        cls.Quant = cls.env["stock.quant"]
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.uom_kg = cls.env.ref("uom.product_uom_kgm")

    def _product(self, name, tracking="none", uom=None, uoms=None):
        vals = {"name": name, "is_storable": True, "tracking": tracking}
        if uom:
            vals["uom_id"] = uom.id
        if uoms:
            vals["uom_ids"] = [Command.set([u.id for u in uoms])]
        return self.env["product.product"].create(vals)

    def _stock(self, product, qty, lot=None, location=None):
        self.Quant._update_available_quantity(
            product, location or self.stock_location, qty, lot_id=lot
        )
        self.env.flush_all()

    def _delivery(self, product, qty, confirm=True, assign=False):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        if confirm:
            picking.action_confirm()
        if assign:
            picking.action_assign()
        return picking

    def _lines(self, picking, count, qty, lots=None):
        picking.move_ids.move_line_ids.unlink()
        self.env.flush_all()
        move = picking.move_ids
        vals = []
        for index in range(count):
            line = {
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": move.product_id.id,
                "quantity": qty,
                "location_id": move.location_id.id,
                "location_dest_id": move.location_dest_id.id,
            }
            if lots:
                line["lot_id"] = lots[index % len(lots)].id
            vals.append(line)
        lines = self.MoveLine.create(vals)
        self.env.flush_all()
        return lines


class PickingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.type_in = cls.env["stock.picking.type"].search(
            [("code", "=", "incoming"), ("warehouse_id", "=", cls.warehouse.id)],
            limit=1,
        )
        cls.type_out = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("warehouse_id", "=", cls.warehouse.id)],
            limit=1,
        )
        assert cls.type_in.sequence_id and cls.type_out.sequence_id
        cls.product = cls.env["product.product"].create(
            {"name": "Picking audit product", "is_storable": True},
        )

    def _picking(self, picking_type=None, quantity=3.0):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": (picking_type or self.type_in).id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": quantity,
                        },
                    ),
                ],
            },
        )


class WarehousePickingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].create(
            {"name": "Audit September", "code": "AUS"}
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.type_in = cls.warehouse.in_type_id
        cls.type_out = cls.warehouse.out_type_id
        cls.type_int = cls.warehouse.int_type_id
        cls.product = cls.env["product.product"].create(
            {"name": "September audit product", "is_storable": True, "weight": 1.0}
        )
        cls.env["stock.quant"]._update_available_quantity(cls.product, cls.stock, 1000)

    def _picking(self, picking_type, quantity=3.0, **values):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": quantity}
                    )
                ],
                **values,
            }
        )

    def _assigned(self, picking_type, **values):
        picking = self._picking(picking_type, **values)
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _statements(self, function):
        counts = []
        for _attempt in range(2):
            self.env.flush_all()
            self.env.invalidate_all()
            before = self.env.cr.sql_statement_count
            function()
            counts.append(self.env.cr.sql_statement_count - before)
        return counts[-1]
