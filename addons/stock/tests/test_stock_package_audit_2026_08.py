from odoo import fields
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


class PackageAuditCommon(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Package = cls.env["stock.package"]

    def assert_search_matches_compute(self, records, field_name, value_records):
        expected = records.filtered(lambda r: r[field_name] & value_records)
        got = records.search(
            [("id", "in", records.ids), (field_name, "in", value_records.ids)]
        )
        self.assertEqual(
            got, expected, f"{field_name} 'in' disagrees with its compute"
        )
        got_neg = records.search(
            [("id", "in", records.ids), (field_name, "not in", value_records.ids)]
        )
        self.assertEqual(
            got_neg,
            records - expected,
            f"{field_name} 'not in' is not the complement of 'in'",
        )


@tagged("post_install", "-at_install")
class TestPackageSearchComputeAgreement(PackageAuditCommon):
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
class TestPackageMoveLineDerivedFields(PackageAuditCommon):
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
class TestPackageWriteAndDefaults(PackageAuditCommon):
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
