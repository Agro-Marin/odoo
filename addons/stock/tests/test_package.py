import importlib.util
import pathlib
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon, WarehousePickingCase


class PackageCase(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Package = cls.env["stock.package"]

    def assert_search_matches_compute(self, records, field_name, value_records):
        expected = records.filtered(lambda r: r[field_name] & value_records)
        got = records.search(
            [("id", "in", records.ids), (field_name, "in", value_records.ids)]
        )
        self.assertEqual(got, expected, f"{field_name} 'in' disagrees with its compute")
        got_neg = records.search(
            [("id", "in", records.ids), (field_name, "not in", value_records.ids)]
        )
        self.assertEqual(
            got_neg,
            records - expected,
            f"{field_name} 'not in' is not the complement of 'in'",
        )


@tagged("post_install", "-at_install")
class TestPackageSearchComputeAgreement(PackageCase):
    def test_all_children_search_excludes_the_package_itself(self):
        outer = self.Package.create({"name": "AUD-OUT"})
        mid = self.Package.create({"name": "AUD-MID", "parent_package_id": outer.id})
        inner = self.Package.create({"name": "AUD-IN", "parent_package_id": mid.id})
        packs = outer | mid | inner

        self.assertNotIn(inner, inner.all_children_package_ids)
        found = self.Package.search(
            [("id", "in", packs.ids), ("all_children_package_ids", "in", inner.ids)]
        )
        self.assertEqual(
            found,
            outer | mid,
            "a package must not match a children-search for itself",
        )

    def test_outermost_search_includes_the_root_and_negates(self):
        root = self.Package.create({"name": "AUD-ROOT"})
        mid = self.Package.create({"name": "AUD-M", "package_dest_id": root.id})
        leaf = self.Package.create({"name": "AUD-L", "package_dest_id": mid.id})
        packs = root | mid | leaf

        self.assertEqual(root.outermost_package_id, root)
        self.assert_search_matches_compute(packs, "outermost_package_id", root)

    def test_owner_search_sees_quants_of_nested_packages(self):
        owner = self.env["res.partner"].create({"name": "AUD-Owner"})
        box = self.Package.create({"name": "AUD-BOX"})
        sub = self.Package.create({"name": "AUD-SUB", "parent_package_id": box.id})
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": self.stock_location.id,
                "quantity": 5.0,
                "package_id": sub.id,
                "owner_id": owner.id,
            }
        )
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(box.owner_id, owner, "owner propagates up the physical tree")
        found = self.Package.search(
            [("id", "in", (box | sub).ids), ("owner_id", "in", owner.ids)]
        )
        self.assertEqual(found, box | sub, "owner search must follow the same tree")


@tagged("post_install", "-at_install")
class TestPackageMoveLineDerivedFields(PackageCase):
    def _picking_into(self, package, location_dest):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.productA.id,
                            "product_uom_qty": 5.0,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.write(
            {"result_package_id": package.id, "location_dest_id": location_dest.id}
        )
        return picking

    def setUp(self):
        super().setUp()
        self.env["stock.quant"]._update_available_quantity(
            self.productA, self.stock_location, 100.0
        )
        self.dest_1, self.dest_2 = self.env["stock.location"].create(
            [
                {"name": "AUD-D1", "location_id": self.customer_location.id},
                {"name": "AUD-D2", "location_id": self.customer_location.id},
            ]
        )

    def test_picking_ids_has_no_phantom_record_without_a_picking(self):
        package = self.Package.create({"name": "AUD-NOPICK"})
        move = self.env["stock.move"].create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": 3.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.write({"result_package_id": package.id})
        self.assertFalse(move.move_line_ids.picking_id, "the fixture needs a bare move")
        self.env.flush_all()
        self.env.invalidate_all()

        pickings = package.picking_ids
        self.assertEqual(
            len(pickings),
            len(pickings.ids),
            "picking_ids holds a record with a NULL id: len() and .ids disagree",
        )
        self.assertFalse(pickings, "a move line with no picking contributes no picking")

    def test_picking_ids_equals_the_pickings_of_its_move_lines(self):
        package = self.Package.create({"name": "AUD-EQ"})
        self._picking_into(package, self.dest_1)
        self._picking_into(package, self.dest_2)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(package.picking_ids, package.move_line_ids.picking_id)

    def test_move_line_ids_refreshes_when_a_line_leaves_the_package(self):
        package = self.Package.create({"name": "AUD-STALE"})
        self._picking_into(package, self.dest_1)
        picking_2 = self._picking_into(package, self.dest_2)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(len(package.move_line_ids), 2)

        picking_2.move_line_ids.result_package_id = False
        self.assertEqual(
            len(package.move_line_ids),
            1,
            "move_line_ids must be invalidated by result_package_id, not by location_id",
        )

    def test_json_popover_refreshes_when_the_destinations_align(self):
        package = self.Package.create({"name": "AUD-POPOVER"})
        self._picking_into(package, self.dest_1)
        picking_2 = self._picking_into(package, self.dest_2)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertTrue(package.json_popover, "two destinations must warn")

        picking_2.move_line_ids.location_dest_id = self.dest_1
        self.assertEqual(
            bool(package.json_popover),
            package._has_issues(),
            "json_popover contradicts the predicate it is built from",
        )

    def test_location_dest_is_false_when_the_lines_disagree(self):
        package = self.Package.create({"name": "AUD-DEST"})
        self._picking_into(package, self.dest_1)
        self._picking_into(package, self.dest_2)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertFalse(
            package.location_dest_id,
            "two destinations is not one of them chosen arbitrarily",
        )
        self.assertTrue(package._has_issues(), "and the popover already says so")
        for location in (self.dest_1, self.dest_2):
            self.assertFalse(
                self.Package.search(
                    [("id", "=", package.id), ("location_dest_id", "in", location.ids)]
                ),
                "a package must not match a destination its field does not hold",
            )

    def test_location_dest_search_matches_when_the_lines_agree(self):
        package = self.Package.create({"name": "AUD-DEST-OK"})
        self._picking_into(package, self.dest_1)
        self._picking_into(package, self.dest_1)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(package.location_dest_id, self.dest_1)
        self.assert_search_matches_compute(package, "location_dest_id", self.dest_1)

    def test_picking_ids_not_in_excludes_packages_holding_that_picking(self):
        package = self.Package.create({"name": "AUD-NOTIN"})
        picking_1 = self._picking_into(package, self.dest_1)
        self._picking_into(package, self.dest_2)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertIn(picking_1, package.picking_ids)

        found = self.Package.search(
            [("id", "=", package.id), ("picking_ids", "not in", picking_1.ids)]
        )
        self.assertFalse(
            found, "a package holding the picking must not match 'picking_ids not in'"
        )


@tagged("post_install", "-at_install")
class TestPackageWriteAndDefaults(PackageCase):
    def test_put_in_pack_keeps_the_container_it_just_assigned(self):
        package = self.Package.create({"name": "AUD-PIP"})
        container = self.Package.create({"name": "AUD-PIP-TARGET"})

        package.action_put_in_pack(package_id=container.id)

        self.assertEqual(
            package.package_dest_id,
            container,
            "put_in_pack cleared the destination it had just set",
        )

    def test_pack_date_default_follows_the_user_timezone(self):
        for tz in ("Pacific/Kiritimati", "Pacific/Midway"):
            with self.subTest(tz=tz):
                package = self.Package.with_context(tz=tz).create({"name": f"AUD-{tz}"})
                self.assertEqual(
                    package.pack_date,
                    fields.Date.context_today(package),
                    "pack_date must default to the user's today, not the server's",
                )

    def test_create_does_not_mutate_the_caller_vals(self):
        vals = {"name": "", "package_type_id": False}
        snapshot = dict(vals)

        self.Package.create([vals])

        self.assertEqual(vals, snapshot, "create mutated the vals dict it was given")

    def test_write_does_not_mutate_the_caller_vals(self):
        package = self.Package.create({"name": "AUD-VALS"})
        vals = {"name": ""}
        snapshot = dict(vals)

        package.write(vals)

        self.assertEqual(vals, snapshot, "write mutated the vals dict it was given")

    def test_content_description_respects_decimal_precision(self):
        package = self.Package.create({"name": "AUD-CONTENT"})
        for quantity in (0.1, 0.2):
            self.env["stock.quant"].create(
                {
                    "product_id": self.productA.id,
                    "location_id": self.stock_location.id,
                    "quantity": quantity,
                    "package_id": package.id,
                }
            )
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertNotIn(
            "0.30000000000000004",
            package.content_description,
            "content_description printed the raw float error",
        )


@tagged("post_install", "-at_install")
class TestPackageHistoryCompany(WarehousePickingCase):
    def test_the_history_belongs_to_the_company_of_its_transfer(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "History company B"})
        self.env.user.company_ids |= company_b
        env_b = self.env(
            context=dict(self.env.context, allowed_company_ids=[company_b.id])
        )
        warehouse_b = env_b["stock.warehouse"].create(
            {"name": "History B", "code": "HSB", "company_id": company_b.id}
        )
        env_b["stock.quant"]._update_available_quantity(
            self.product, warehouse_b.lot_stock_id, 10
        )
        picking = env_b["stock.picking"].create(
            {
                "picking_type_id": warehouse_b.out_type_id.id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": 2}
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.picked = True
        picking.action_put_in_pack()

        env_ab = self.env(
            context=dict(
                self.env.context, allowed_company_ids=[company_a.id, company_b.id]
            )
        )
        env_ab["stock.picking"].browse(picking.id).button_validate()
        history = self.env["stock.package.history"].search(
            [("picking_ids", "in", picking.ids)]
        )

        self.assertEqual(picking.state, "done")
        self.assertTrue(history)
        self.assertEqual(history.company_id, company_b)

        history.company_id = company_a
        self.env.flush_all()
        migration = importlib.util.spec_from_file_location(
            "stock_post_package_history_company",
            pathlib.Path(__file__).parents[1]
            / "migrations"
            / "1.20"
            / "post-package_history_company.py",
        )
        module = importlib.util.module_from_spec(migration)
        migration.loader.exec_module(module)
        module.migrate(self.env.cr, "1.19")
        history.invalidate_recordset(["company_id"])
        self.assertEqual(history.company_id, company_b)


@tagged("post_install", "-at_install")
class TestPackageReadsAreBatched(WarehousePickingCase):
    def _packed_pickings(self, count):
        pickings = self.env["stock.picking"]
        packages = self.env["stock.package"]
        for index in range(count):
            picking = self._assigned(self.type_out)
            package = self.env["stock.package"].create(
                {"name": f"Batched read {count}-{index}"}
            )
            picking.move_line_ids.result_package_id = package
            pickings |= picking
            packages |= package
        return pickings, packages

    def test_a_package_list_costs_the_same_for_three_or_twelve_rows(self):
        _few_pickings, few = self._packed_pickings(3)
        _many_pickings, many = self._packed_pickings(12)

        def read(packages):
            return self._statements(
                lambda: packages.read(["location_dest_id", "json_popover"])
            )

        self.assertEqual(read(few), read(many))

    def test_counting_packages_costs_the_same_for_three_or_twelve_pickings(self):
        few, _few_packages = self._packed_pickings(3)
        many, _many_packages = self._packed_pickings(12)

        def count(pickings):
            return self._statements(lambda: pickings.mapped("count_packages"))

        self.assertEqual(count(few), count(many))
        self.assertEqual(many.mapped("count_packages"), [1] * 12)

    def _chains(self, count):
        Package = self.env["stock.package"]
        outer = Package.create([{"name": f"Outer {count}-{i}"} for i in range(count)])
        middle = Package.create(
            [
                {"name": f"Middle {count}-{i}", "package_dest_id": package.id}
                for i, package in enumerate(outer)
            ]
        )
        inner = Package.create(
            [
                {"name": f"Inner {count}-{i}", "package_dest_id": package.id}
                for i, package in enumerate(middle)
            ]
        )
        return outer, middle, inner

    def test_walking_nested_destinations_costs_one_read_per_level(self):
        few, *_rest = self._chains(3)
        many, *_rest = self._chains(12)

        def walk(packages):
            return self._statements(packages._get_all_children_package_dest_ids)

        self.assertEqual(walk(few), walk(many))

    def test_the_walk_reports_every_descendant_of_every_root(self):
        outer, middle, inner = self._chains(2)
        roots = outer[0] | middle[0] | outer[1]

        children_by_root, all_ids = roots._get_all_children_package_dest_ids()

        self.assertEqual(set(children_by_root[outer[0]]), {middle[0].id, inner[0].id})
        self.assertEqual(set(children_by_root[middle[0]]), {inner[0].id})
        self.assertEqual(set(children_by_root[outer[1]]), {middle[1].id, inner[1].id})
        self.assertEqual(all_ids, set((outer | middle | inner).ids))

    def test_shipping_weight_weighs_only_the_packages_each_picking_holds(self):
        pickings, _packages = self._packed_pickings(6)
        Package = type(self.env["stock.package"])
        original = Package._get_weight_by_picking
        sizes = []

        def spy(records, *args, **kwargs):
            result = original(records, *args, **kwargs)
            sizes.append(len(result))
            return result

        self.env.invalidate_all()
        with patch.object(Package, "_get_weight_by_picking", spy):
            pickings._fields["shipping_weight"].compute_value(pickings)

        self.assertEqual(sizes, [6])
        self.assertEqual(pickings.mapped("shipping_weight"), [3.0] * 6)
