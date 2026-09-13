from odoo.tests import TransactionCase, tagged

from odoo.addons.mixin_encryption.tests.common import EncryptionKeyCase


@tagged("post_install", "-at_install")
class TestSystemSecret(EncryptionKeyCase, TransactionCase):
    def test_a_system_secret_round_trips_encrypted_and_leaves_no_parameter(self):
        Credential = self.env["credential.credential"]

        Credential._set_system_secret("probe_client_secret", "s3cr3t")

        self.assertEqual(Credential._get_system_secret("probe_client_secret"), "s3cr3t")
        credential = Credential._get_system_secret_credential("probe_client_secret")
        self.assertFalse(credential.company_id)
        self.assertTrue(credential.credential_value_encrypted)
        self.assertFalse(
            self.env["ir.config_parameter"].sudo().get_param("probe_client_secret")
        )

    def test_writing_it_again_replaces_it_and_clearing_it_removes_it(self):
        Credential = self.env["credential.credential"]
        Credential._set_system_secret("probe_client_secret", "first")

        Credential._set_system_secret("probe_client_secret", "second")
        self.assertEqual(Credential._get_system_secret("probe_client_secret"), "second")

        Credential._set_system_secret("probe_client_secret", False)
        self.assertFalse(Credential._get_system_secret("probe_client_secret"))
        self.assertFalse(
            Credential._get_system_secret_credential("probe_client_secret")
        )
