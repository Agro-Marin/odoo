from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

CATEGORY_XMLID = "cloud_drive_s3.credential_category_drive_s3"


@tagged("post_install", "-at_install")
class TestCloudDriveConfig(TransactionCase):
    def _category(self):
        return self.env.ref(CATEGORY_XMLID)

    def _credentials(self):
        return (
            self.env["credential.credential"]
            .sudo()
            .search([("category_id", "=", self._category().id)])
        )

    def test_save_stores_bucket_region_in_params(self):
        self.env["cloud.drive.config"].create(
            {
                "bucket_name": "my-bucket",
                "region": "us-east-2",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "supersecret",
            }
        )._persist()
        icp = self.env["ir.config_parameter"].sudo()
        self.assertEqual(icp.get_param("cloud_drive_s3.bucket_name"), "my-bucket")
        self.assertEqual(icp.get_param("cloud_drive_s3.region"), "us-east-2")

    def test_secrets_never_in_config_params(self):
        self.env["cloud.drive.config"].create(
            {
                "bucket_name": "b",
                "region": "r",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "supersecret",
            }
        )._persist()
        icp = self.env["ir.config_parameter"].sudo()
        self.assertFalse(icp.get_param("cloud_drive_s3.access_key_id"))
        self.assertFalse(icp.get_param("cloud_drive_s3.secret_access_key"))

    def test_keys_stored_as_readable_json(self):
        self.env["cloud.drive.config"].create(
            {
                "bucket_name": "b",
                "region": "r",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "supersecret",
            }
        )._persist()
        cred = self._credentials()
        self.assertEqual(len(cred), 1)
        self.assertEqual(cred.storage_method, "json")
        data = cred.get_credential_dict()
        self.assertEqual(data.get("access_key_id"), "AKIAEXAMPLE")
        self.assertEqual(data.get("secret_access_key"), "supersecret")

    def test_partial_keys_raise(self):
        wizard = self.env["cloud.drive.config"].create(
            {"bucket_name": "b", "region": "r", "access_key_id": "only-id"}
        )
        with self.assertRaises(UserError):
            wizard._persist()

    def test_saving_without_keys_does_not_duplicate_or_wipe(self):
        self.env["cloud.drive.config"].create(
            {
                "bucket_name": "b",
                "region": "r",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "supersecret",
            }
        )._persist()
        self.assertEqual(len(self._credentials()), 1)
        self.env["cloud.drive.config"].create(
            {"bucket_name": "b", "region": "us-west-2"}
        )._persist()
        creds = self._credentials()
        self.assertEqual(len(creds), 1)
        self.assertEqual(
            creds.get_credential_dict().get("access_key_id"), "AKIAEXAMPLE"
        )

    def test_default_get_reports_keys_set(self):
        self.env["cloud.drive.config"].create(
            {
                "bucket_name": "b",
                "region": "r",
                "access_key_id": "AKIAEXAMPLE",
                "secret_access_key": "supersecret",
            }
        )._persist()
        defaults = self.env["cloud.drive.config"].default_get(
            ["bucket_name", "region", "keys_set"]
        )
        self.assertEqual(defaults["bucket_name"], "b")
        self.assertTrue(defaults["keys_set"])
