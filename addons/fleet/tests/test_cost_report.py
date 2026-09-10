from datetime import date

from psycopg.errors import CheckViolation

from odoo.exceptions import ValidationError
from odoo.tests import common
from odoo.tools import mute_logger

APRIL = date(2025, 4, 1)
APRIL_DAYS = 30


class FleetCase(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Probe"})
        model = cls.env["fleet.vehicle.model"].create(
            {"brand_id": brand.id, "name": "Probe One"}
        )
        cls.vehicle = cls.env["fleet.vehicle"].create(
            {"model_id": model.id, "acquisition_date": date(2025, 1, 1)}
        )


class TestFleetCostReport(FleetCase):
    def _contract(self, unit, interval, cost):
        return self.env["fleet.vehicle.log.contract"].create(
            {
                "vehicle_id": self.vehicle.id,
                "amount": 0.0,
                "cost_generated": cost,
                "cost_frequency_unit": unit,
                "cost_frequency_interval": interval,
                "start_date": date(2025, 1, 1),
                "expiration_date": date(2025, 12, 31),
                "date": date(2025, 1, 15),
                "state": "open",
            }
        )

    def _april_contract_cost(self):
        self.env.flush_all()
        rows = self.env["fleet.vehicle.cost.report"].search_read(
            [
                ("vehicle_id", "=", self.vehicle.id),
                ("cost_type", "=", "contract"),
                ("date_start", "=", APRIL),
            ],
            ["cost"],
        )
        return sum(row["cost"] for row in rows)

    def test_each_contract_counts_once(self):
        self._contract("month", 1, 100.0)
        self._contract("month", 1, 100.0)
        self._contract("month", 1, 100.0)
        self.assertAlmostEqual(self._april_contract_cost(), 300.0)

    def test_contracts_of_different_units_do_not_multiply_each_other(self):
        self._contract("month", 1, 100.0)
        self._contract("day", 1, 100.0)
        self.assertAlmostEqual(self._april_contract_cost(), 100.0 + 100.0 * APRIL_DAYS)

    def test_a_weekly_contract_contributes(self):
        self._contract("week", 1, 70.0)
        self.assertAlmostEqual(self._april_contract_cost(), 70.0 * APRIL_DAYS / 7)

    def test_the_interval_divides_the_cost(self):
        self._contract("month", 3, 300.0)
        self._contract("week", 2, 140.0)
        self.assertAlmostEqual(
            self._april_contract_cost(), 100.0 + 140.0 * APRIL_DAYS / 14
        )

    def test_a_yearly_contract_accrues_by_day(self):
        self._contract("year", 1, 36525.0)
        self.assertAlmostEqual(
            self._april_contract_cost(), 36525.0 * APRIL_DAYS / 365.25
        )

    def test_a_contract_without_a_unit_has_no_recurring_cost(self):
        self._contract(False, 1, 100.0)
        self.assertAlmostEqual(self._april_contract_cost(), 0.0)

    def test_the_interval_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._contract("month", 0, 100.0)

    def test_cost_per_month_normalises_every_unit(self):
        cases = (
            ("month", 3, 300.0, 100.0),
            ("day", 1, 10.0, 10.0 * 30.4375),
            ("week", 1, 70.0, 70.0 * 30.4375 / 7),
            ("year", 1, 365.25, 30.4375),
            (False, 1, 100.0, 0.0),
        )
        for unit, interval, cost, expected in cases:
            with self.subTest(unit=unit, interval=interval):
                contract = self._contract(unit, interval, cost)
                self.assertAlmostEqual(contract._cost_per_month(), expected)


class TestFleetOdometer(FleetCase):
    def _reading(self, value, day):
        return self.env["fleet.vehicle.odometer"].create(
            {"vehicle_id": self.vehicle.id, "value": value, "date": day}
        )

    def test_a_later_reading_below_an_earlier_one_is_refused(self):
        self._reading(1000.0, date(2025, 4, 1))
        with self.assertRaises(ValidationError):
            self._reading(500.0, date(2025, 4, 2))

    def test_an_earlier_reading_above_a_later_one_is_refused(self):
        self._reading(1000.0, date(2025, 4, 10))
        with self.assertRaises(ValidationError):
            self._reading(5000.0, date(2025, 4, 1))

    def test_a_reading_created_in_the_same_batch_is_a_neighbour(self):
        with self.assertRaises(ValidationError):
            self.env["fleet.vehicle.odometer"].create(
                [
                    {
                        "vehicle_id": self.vehicle.id,
                        "value": 1000.0,
                        "date": date(2025, 4, 1),
                    },
                    {
                        "vehicle_id": self.vehicle.id,
                        "value": 500.0,
                        "date": date(2025, 4, 2),
                    },
                ]
            )

    def test_an_earlier_lower_reading_is_accepted(self):
        self._reading(1000.0, date(2025, 4, 10))
        self._reading(10.0, date(2025, 3, 1))
        self._reading(2000.0, date(2025, 4, 20))
        self.env.flush_all()
        self.assertEqual(self.vehicle.odometer, 2000.0)

    def test_a_negative_reading_is_refused(self):
        with self.assertRaises(CheckViolation), mute_logger("odoo.db"):
            self._reading(-5.0, date(2025, 4, 1))
            self.env.flush_all()

    def test_the_vehicle_reports_its_latest_reading_not_its_highest(self):
        # Readings that run backwards can no longer be created, but a database
        # upgraded from before the constraint may still hold them.
        self._reading(10000.0, date(2025, 4, 1))
        self.env.flush_all()
        self.env.cr.execute(
            "INSERT INTO fleet_vehicle_odometer (vehicle_id, value, date)"
            " VALUES (%s, %s, %s), (%s, %s, %s)",
            (
                self.vehicle.id,
                999999.0,
                date(2025, 4, 2),
                self.vehicle.id,
                10500.0,
                date(2025, 4, 3),
            ),
        )
        self.env.invalidate_all()
        self.assertEqual(self.vehicle.odometer, 10500.0)
