from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

SECRET = "wJalrXUtnFEMI/K7MDENG/TESTONLYSECRETKEY"
ACCESS_KEY = "AKIAIOSFODNN7TESTONLY"


@tagged("post_install", "-at_install", "cloud_drive_s3")
class TestConfigSecretLifetime(TransactionCase):
    def _wizard(self):
        return self.env["cloud.drive.config"].create(
            {
                "bucket_name": "a-bucket",
                "region": "us-east-2",
                "access_key_id": ACCESS_KEY,
                "secret_access_key": SECRET,
            }
        )

    def _column(self, wizard, column):
        self.env.flush_all()
        self.env.cr.execute(
            f"SELECT {column} FROM cloud_drive_config WHERE id = %s",
            (wizard.id,),
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def test_secret_is_cleared_from_the_transient_table(self):
        wizard = self._wizard()
        self.assertEqual(self._column(wizard, "secret_access_key"), SECRET)

        with patch.object(type(wizard), "_store_keys") as store:
            wizard._persist()
        store.assert_called_once()

        self.assertFalse(self._column(wizard, "secret_access_key"))
        self.assertFalse(self._column(wizard, "access_key_id"))

    def test_whole_row_is_free_of_the_secret(self):
        wizard = self._wizard()
        with patch.object(type(wizard), "_store_keys"):
            wizard._persist()

        self.env.flush_all()
        self.env.cr.execute(
            "SELECT row_to_json(cloud_drive_config) FROM cloud_drive_config "
            "WHERE id = %s",
            (wizard.id,),
        )
        self.assertNotIn(SECRET, str(self.env.cr.fetchone()[0]))

    def test_keys_set_is_reported_after_saving(self):
        wizard = self._wizard()
        with patch.object(type(wizard), "_store_keys"):
            wizard._persist()
        self.assertTrue(wizard.keys_set)

    def test_partial_credentials_are_still_rejected(self):
        from odoo.exceptions import UserError

        wizard = self.env["cloud.drive.config"].create(
            {"bucket_name": "b", "region": "us-east-2", "access_key_id": ACCESS_KEY}
        )
        with self.assertRaises(UserError):
            wizard._persist()

    def test_empty_credentials_keep_the_stored_ones(self):
        wizard = self.env["cloud.drive.config"].create(
            {"bucket_name": "b", "region": "us-east-2"}
        )
        with patch.object(type(wizard), "_store_keys") as store:
            wizard._persist()
        store.assert_not_called()
