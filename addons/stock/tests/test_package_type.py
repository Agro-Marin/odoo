from odoo.tests import TransactionCase


class TestPackageTypeSequencePrefix(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PackageType = cls.env["stock.package.type"]
        cls.Package = cls.env["stock.package"]

    def test_clearing_the_prefix_clears_it(self):
        package_type = self.PackageType.create(
            {"name": "Tote", "sequence_code": "TOTE"}
        )
        self.env.flush_all()
        self.assertEqual(
            self.Package.create({"package_type_id": package_type.id}).name,
            "TOTE0000001",
        )
        package_type.write({"sequence_code": False})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertFalse(package_type.sequence_id.prefix)
        self.assertNotIn(
            "TOTE",
            self.Package.create({"package_type_id": package_type.id}).name,
            "packages went on carrying a prefix the field reads back as blank",
        )

    def test_setting_a_new_prefix_still_takes(self):
        package_type = self.PackageType.create(
            {"name": "Crate", "sequence_code": "CRATE"}
        )
        self.env.flush_all()
        self.Package.create({"package_type_id": package_type.id})
        package_type.write({"sequence_code": "BIN"})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertTrue(
            self.Package.create({"package_type_id": package_type.id}).name.startswith(
                "BIN"
            )
        )
        self.assertEqual(package_type.sequence_id.name, "Package Type Sequence BIN")

    def test_a_write_that_names_no_prefix_leaves_the_sequence_alone(self):
        package_type = self.PackageType.create(
            {"name": "Pallet", "sequence_code": "PAL"}
        )
        self.env.flush_all()
        package_type.write({"name": "Pallet renamed"})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(package_type.sequence_id.prefix, "PAL")


class TestPackageTypeNextName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PackageType = cls.env["stock.package.type"]

    def test_a_type_with_a_sequence_uses_its_own(self):
        package_type = self.PackageType.create({"name": "Own", "sequence_code": "OWN"})
        self.env.flush_all()
        self.assertTrue(
            package_type._get_next_name_by_sequence().startswith("OWN"),
        )

    def test_no_type_at_all_falls_through_to_the_global_sequence(self):
        self.assertTrue(self.PackageType.browse()._get_next_name_by_sequence())

    def test_more_than_one_type_is_a_caller_error(self):
        pair = self.PackageType.create(
            [
                {"name": "First", "sequence_code": "ONE"},
                {"name": "Second", "sequence_code": "TWO"},
            ]
        )
        self.env.flush_all()
        with self.assertRaises(ValueError):
            pair._get_next_name_by_sequence()
