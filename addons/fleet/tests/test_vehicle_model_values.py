from odoo.tests import TransactionCase


class TestVehicleModelValues(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Brand"})
        cls.model_in_miles = cls.env["fleet.vehicle.model"].create(
            {"name": "Miles model", "brand_id": brand.id, "range_unit": "mi"}
        )

    def test_a_new_vehicle_takes_its_range_unit_from_the_model(self):
        vehicle = self.env["fleet.vehicle"].create({"model_id": self.model_in_miles.id})

        self.assertEqual(vehicle.range_unit, "mi")

    def test_an_explicit_range_unit_wins_over_the_model(self):
        vehicle = self.env["fleet.vehicle"].create(
            {"model_id": self.model_in_miles.id, "range_unit": "km"}
        )

        self.assertEqual(vehicle.range_unit, "km")
