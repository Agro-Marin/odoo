# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta
from freezegun import freeze_time
from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.addons.bus.models.bus import DEFAULT_GC_RETENTION_SECONDS


@tagged("-at_install", "post_install")
class TestBusGC(HttpCase):
    def _create_one_bus_message(self):
        """Helper: clear all bus messages, create one, and return the model."""
        self.env["bus.bus"].search([]).unlink()
        self.env["bus.bus"].create({"channel": "foo", "message": "bar"})
        self.assertEqual(self.env["bus.bus"].search_count([]), 1)

    def test_default_gc_retention_window(self):
        self.env["ir.config_parameter"].search([("key", "=", "bus.gc_retention_seconds")]).unlink()
        self.env["bus.bus"].search([]).unlink()
        self.env["bus.bus"].create({"channel": "foo", "message": "bar"})
        self.assertEqual(self.env["bus.bus"].search_count([]), 1)

        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS / 2)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)
        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_custom_gc_retention_window(self):
        self.env["bus.bus"].search([]).unlink()
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", 25000)
        self.env["bus.bus"].create({"channel": "foo", "message": "bar"})
        self.assertEqual(self.env["bus.bus"].search_count([]), 1)

        with freeze_time(datetime.now() + timedelta(seconds=15000)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)
        with freeze_time(datetime.now() + timedelta(seconds=30000)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_zero_gc_retention_falls_back_to_default(self):
        """Zero retention is invalid; GC must fall back to DEFAULT_GC_RETENTION_SECONDS."""
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", 0)
        self._create_one_bus_message()

        # Just past DEFAULT — message should be gone (default was used, not 0)
        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)):
            with patch("odoo.addons.bus.models.bus._logger") as mock_logger:
                self.env["bus.bus"]._gc_messages()
                mock_logger.warning.assert_called_once()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_negative_gc_retention_falls_back_to_default(self):
        """Negative retention is invalid; GC must fall back to DEFAULT_GC_RETENTION_SECONDS."""
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", -3600)
        self._create_one_bus_message()

        # Message is still fresh — well within default window
        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS / 2)):
            with patch("odoo.addons.bus.models.bus._logger") as mock_logger:
                self.env["bus.bus"]._gc_messages()
                mock_logger.warning.assert_called_once()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)

        # Past the default window — message should now be deleted
        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)

    def test_non_numeric_gc_retention_falls_back_to_default(self):
        """Non-numeric retention is invalid; GC must fall back to DEFAULT_GC_RETENTION_SECONDS."""
        self.env["ir.config_parameter"].set_param("bus.gc_retention_seconds", "not_a_number")
        self._create_one_bus_message()

        # Message is still fresh — well within default window
        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS / 2)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 1)

        # Past the default window — message should now be deleted
        with freeze_time(datetime.now() + timedelta(seconds=DEFAULT_GC_RETENTION_SECONDS + 1)):
            self.env["bus.bus"]._gc_messages()
            self.assertEqual(self.env["bus.bus"].search_count([]), 0)
