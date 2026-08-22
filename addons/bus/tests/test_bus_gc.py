from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo.tests import TransactionCase, tagged

from odoo.addons.bus.models.bus import DEFAULT_GC_RETENTION_SECONDS


def _utcnow():
    return datetime.now(UTC)


@tagged("-at_install", "post_install")
class TestBusGC(TransactionCase):
    def _create_one_bus_message(self):
        self.env["bus.bus"].search([]).unlink()
        self.env["bus.bus"].create({"channel": "foo", "message": "bar"})
        self.assertEqual(self.env["bus.bus"].search_count([]), 1)

    def test_default_gc_retention_window(self):
        self.env["ir.config_parameter"].search(
            [("key", "=", "bus.gc_retention_seconds")]
        ).unlink()
        self._create_one_bus_message()

        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS / 2)
        ):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)
        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)
        ):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_custom_gc_retention_window(self):
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", 25000)
        self._create_one_bus_message()

        with freeze_time(_utcnow() + timedelta(seconds=15000)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)
        with freeze_time(_utcnow() + timedelta(seconds=30000)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_zero_gc_retention_falls_back_to_default(self):
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", 0)
        self._create_one_bus_message()

        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)
        ):
            with patch("odoo.addons.bus.models.bus._logger") as mock_logger:
                self.env["bus.bus"]._gc_messages()
                mock_logger.warning.assert_called_once()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_negative_gc_retention_falls_back_to_default(self):
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", -3600)
        self._create_one_bus_message()

        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS / 2)
        ):
            with patch("odoo.addons.bus.models.bus._logger") as mock_logger:
                self.env["bus.bus"]._gc_messages()
                mock_logger.warning.assert_called_once()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)

        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)
        ):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_non_numeric_gc_retention_falls_back_to_default(self):
        self.env["ir.config_parameter"].set_param(
            "bus.gc_retention_seconds", "not_a_number"
        )
        self._create_one_bus_message()

        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS / 2)
        ):
            with patch("odoo.addons.bus.models.bus._logger") as mock_logger:
                self.env["bus.bus"]._gc_messages()
                mock_logger.warning.assert_called_once()
                warned_value = mock_logger.warning.call_args[0][1]
                self.assertEqual(warned_value, "not_a_number")
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)

        with freeze_time(
            _utcnow() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)
        ):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)
