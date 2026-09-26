import os
from unittest.mock import patch

from odoo.tests import tagged

from .common import DeviceTransactionCase


@tagged("post_install", "-at_install")
class TestInboundCredentialWithoutKey(DeviceTransactionCase):
    def _create_without_key(self, identifier):
        environ = {
            key: value
            for key, value in os.environ.items()
            if key != "ODOO_API_ENCRYPTION_KEY"
        }
        with (
            patch.dict(os.environ, environ, clear=True),
            self.assertLogs("odoo.addons.device.models.device_device", "WARNING"),
        ):
            return self._create_device_device(
                identifier=identifier, auth_type="bearer", rate_limit_enabled=False
            )

    def test_a_device_created_without_a_key_holds_an_unprovisioned_credential(self):
        device = self._create_without_key("NO-KEY-1")

        credential = device.sudo().credential_id
        self.assertTrue(credential)
        self.assertFalse(credential.credential_value_encrypted)
        self.assertFalse(device.sudo().credential_fingerprint)

    def test_an_unprovisioned_device_refuses_every_bearer(self):
        device = self._create_without_key("NO-KEY-2")

        for header in ("Bearer ", "Bearer anything"):
            allowed, _reason = device.check_inbound_auth(
                {"Authorization": header}, "10.0.0.1"
            )
            self.assertFalse(allowed, header)

    def test_a_device_created_with_a_key_still_gets_its_token(self):
        device = self._create_device_device(identifier="WITH-KEY")

        self.assertTrue(self._device_token(device))
        self.assertTrue(device.sudo().credential_fingerprint)
