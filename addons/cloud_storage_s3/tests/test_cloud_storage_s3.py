from unittest.mock import MagicMock, patch
from urllib.parse import quote

from botocore.exceptions import ClientError

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from .. import uninstall_hook
from ..models.ir_attachment import _get_s3_client, _S3ClientCache


class TestCloudStorageS3Common(TransactionCase):
    def setUp(self):
        super().setUp()
        self.bucket_name = "test-odoo-bucket"
        self.region = "us-east-2"
        self.access_key_id = "AKIAIOSFODNN7EXAMPLE"
        self.secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

        icp = self.env["ir.config_parameter"]
        icp.set_param("cloud_storage_s3_enabled", "True")
        icp.set_param("cloud_storage_provider", "s3")
        icp.set_param("cloud_storage_s3_bucket_name", self.bucket_name)
        icp.set_param("cloud_storage_s3_region", self.region)
        icp.set_param("cloud_storage_s3_access_key_id", self.access_key_id)
        icp.set_param("cloud_storage_s3_secret_access_key", self.secret_access_key)

        _S3ClientCache.clear()

        self.mock_s3_client = MagicMock()
        self.mock_s3_client.generate_presigned_url.return_value = (
            "https://presigned.example.com/test"
        )
        self.mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        self._boto3_patcher = patch(
            "odoo.addons.cloud_storage_s3.models.ir_attachment.boto3.client",
            return_value=self.mock_s3_client,
        )
        self._boto3_patcher.start()

    def tearDown(self):
        self._boto3_patcher.stop()
        _S3ClientCache.clear()
        super().tearDown()


class TestCloudStorageS3(TestCloudStorageS3Common):
    def test_generate_cloud_storage_url(self):
        attachment = self.env["ir.attachment"].create(
            [{"name": "test.txt", "mimetype": "text/plain", "datas": b""}]
        )
        attachment._post_add_create(cloud_storage=True)
        self.assertTrue(
            attachment.url.startswith(
                f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/"
            ),
            "URL should use the S3 virtual-hosted style",
        )

    def test_generate_url_with_special_characters(self):
        file_name = "reporte año 2026 (final).pdf"
        attachment = self.env["ir.attachment"].create(
            [{"name": file_name, "mimetype": "application/pdf", "datas": b""}]
        )
        attachment._post_add_create(cloud_storage=True)
        self.assertIn(
            quote(file_name),
            attachment.url,
            "Special characters in filename should be URL-encoded",
        )

    def test_generate_presigned_download_info(self):
        attachment = self.env["ir.attachment"].create(
            [{"name": "test.txt", "mimetype": "text/plain", "datas": b""}]
        )
        attachment._post_add_create(cloud_storage=True)
        info = attachment._generate_cloud_storage_download_info()
        self.assertIn("url", info)
        self.assertIn("time_to_expiry", info)
        self.mock_s3_client.generate_presigned_url.assert_called()

    def test_generate_presigned_upload_info(self):
        attachment = self.env["ir.attachment"].create(
            [{"name": "test.txt", "mimetype": "text/plain", "datas": b""}]
        )
        attachment._post_add_create(cloud_storage=True)
        info = attachment._generate_cloud_storage_upload_info()
        self.assertEqual(info["method"], "PUT")
        self.assertEqual(info["response_status"], 200)

    def test_blob_name_structure(self):
        attachment = self.env["ir.attachment"].create(
            [
                {
                    "name": "document.pdf",
                    "mimetype": "application/pdf",
                    "datas": b"",
                    "res_model": "res.partner",
                    "res_id": 1,
                }
            ]
        )
        attachment._post_add_create(cloud_storage=True)
        self.assertIn("res_partner/1/", attachment.url)

    def test_s3_url_validation(self):
        attachment = self.env["ir.attachment"].create(
            [
                {
                    "name": "test.txt",
                    "mimetype": "text/plain",
                    "type": "cloud_storage",
                    "url": f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/res_partner/1/42_abc12345_test.txt",
                }
            ]
        )
        info = attachment._get_s3_info()
        self.assertEqual(info["bucket_name"], self.bucket_name)
        self.assertEqual(info["region"], self.region)
        self.assertEqual(info["blob_name"], "res_partner/1/42_abc12345_test.txt")

    def test_s3_url_validation_invalid(self):
        attachment = self.env["ir.attachment"].create(
            [
                {
                    "name": "test.txt",
                    "mimetype": "text/plain",
                    "type": "cloud_storage",
                    "url": "https://storage.googleapis.com/bucket/blob",
                }
            ]
        )
        with self.assertRaises(ValidationError):
            attachment._get_s3_info()

    def test_unlink_deletes_s3_blobs_batch(self):
        attachments = self.env["ir.attachment"]
        for i in range(3):
            attachments |= self.env["ir.attachment"].create(
                [
                    {
                        "name": f"file_{i}.txt",
                        "mimetype": "text/plain",
                        "type": "cloud_storage",
                        "url": f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/test/{i}_abc_file_{i}.txt",
                    }
                ]
            )
        attachments.unlink()
        self.mock_s3_client.delete_objects.assert_called_once()
        call_args = self.mock_s3_client.delete_objects.call_args
        self.assertEqual(call_args.kwargs["Bucket"], self.bucket_name)
        self.assertEqual(len(call_args.kwargs["Delete"]["Objects"]), 3)

    def test_unlink_non_s3_attachments_ignored(self):
        attachment = self.env["ir.attachment"].create(
            [
                {
                    "name": "local.txt",
                    "mimetype": "text/plain",
                    "datas": b"",
                }
            ]
        )
        attachment.unlink()
        self.mock_s3_client.delete_objects.assert_not_called()

    def test_client_cache_invalidation(self):
        with patch(
            "odoo.addons.cloud_storage_s3.models.ir_attachment.boto3.client",
            side_effect=lambda *a, **kw: MagicMock(),
        ):
            _S3ClientCache.clear()
            client1 = _get_s3_client(self.env)
            client2 = _get_s3_client(self.env)
            self.assertIs(client1, client2)

            self.env["ir.config_parameter"].set_param(
                "cloud_storage_s3_access_key_id", "NEWKEY"
            )
            client3 = _get_s3_client(self.env)
            self.assertIsNot(client1, client3)

    def test_is_s3_provider(self):
        attachment = self.env["ir.attachment"].new()
        self.assertTrue(attachment._is_s3_provider())

        self.env["ir.config_parameter"].set_param("cloud_storage_provider", "google")
        self.assertFalse(attachment._is_s3_provider())

    def test_uninstall_fail(self):
        with self.assertRaises(UserError):
            attachment = self.env["ir.attachment"].create(
                [{"name": "test.txt", "mimetype": "text/plain", "datas": b""}]
            )
            attachment._post_add_create(cloud_storage=True)
            attachment.flush_recordset()
            uninstall_hook(self.env)

    def test_uninstall_success(self):
        uninstall_hook(self.env)
        icp = self.env["ir.config_parameter"]
        self.assertFalse(icp.get_param("cloud_storage_provider"))
        self.assertFalse(icp.get_param("cloud_storage_s3_bucket_name"))
        self.assertFalse(icp.get_param("cloud_storage_s3_region"))
        self.assertFalse(icp.get_param("cloud_storage_s3_access_key_id"))
        self.assertFalse(icp.get_param("cloud_storage_s3_secret_access_key"))


class TestCloudStorageS3Hybrid(TestCloudStorageS3Common):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].set_param(
            "cloud_storage_s3_storage_mode", "hybrid"
        )

    def _make_attachment(self, **vals):
        defaults = {
            "name": "doc.txt",
            "raw": b"hello world",
            "res_model": "res.partner",
            "res_id": 1,
        }
        defaults.update(vals)
        return self.env["ir.attachment"].create([defaults])

    def test_create_flags_business_attachment_pending(self):
        attachment = self._make_attachment()
        self.assertEqual(attachment.type, "binary")
        self.assertTrue(attachment.s3_mirror_pending)

    def test_create_skips_system_assets(self):
        attachment = self.env["ir.attachment"].create(
            [{"name": "bundle.js", "raw": b"console.log(1)"}]
        )
        self.assertFalse(attachment.s3_mirror_pending)

    def test_post_add_create_keeps_local_in_hybrid(self):
        attachment = self._make_attachment()
        attachment._post_add_create(cloud_storage=True)
        self.assertEqual(attachment.type, "binary")
        self.assertFalse(attachment.url)

    def test_mirror_uploads_and_clears_pending(self):
        attachment = self._make_attachment()
        attachment._s3_mirror_to_cloud()
        self.mock_s3_client.put_object.assert_called_once()
        call = self.mock_s3_client.put_object.call_args
        self.assertEqual(call.kwargs["Bucket"], self.bucket_name)
        self.assertEqual(call.kwargs["Body"], b"hello world")
        self.assertFalse(attachment.s3_mirror_pending)
        self.assertTrue(attachment.s3_blob_name)

    def test_mirror_failure_keeps_pending(self):
        self.mock_s3_client.put_object.side_effect = Exception("network down")
        attachment = self._make_attachment()
        attachment._s3_mirror_to_cloud()
        self.assertTrue(attachment.s3_mirror_pending)
        self.assertFalse(attachment.s3_blob_name)

    def test_cron_mirrors_pending(self):
        attachment = self._make_attachment()
        self.env["ir.attachment"]._cron_mirror_pending_to_s3()
        self.mock_s3_client.put_object.assert_called()
        self.assertFalse(attachment.s3_mirror_pending)

    def test_unlink_deletes_hybrid_mirror(self):
        attachment = self._make_attachment()
        attachment._s3_mirror_to_cloud()
        blob_name = attachment.s3_blob_name
        attachment.unlink()
        self.mock_s3_client.delete_objects.assert_called_once()
        call = self.mock_s3_client.delete_objects.call_args
        self.assertEqual(call.kwargs["Bucket"], self.bucket_name)
        self.assertEqual(call.kwargs["Delete"]["Objects"], [{"Key": blob_name}])

    def test_write_flags_late_res_model(self):
        attachment = self.env["ir.attachment"].create(
            [{"name": "late.pdf", "raw": b"pdf-bytes"}]
        )
        self.assertFalse(attachment.s3_mirror_pending)
        attachment.write({"res_model": "documents.document", "res_id": 99})
        self.assertTrue(attachment.s3_mirror_pending)

    def test_blob_name_mirrors_filestore(self):
        attachment = self._make_attachment()
        attachment._s3_mirror_to_cloud()
        self.assertEqual(attachment.s3_blob_name, attachment.store_fname)

    def test_unlink_keeps_shared_blob(self):
        a1 = self._make_attachment(name="a.txt")
        a2 = self._make_attachment(name="b.txt")
        a1._s3_mirror_to_cloud()
        a2._s3_mirror_to_cloud()
        self.assertEqual(a1.s3_blob_name, a2.s3_blob_name)
        a1.unlink()
        self.mock_s3_client.delete_objects.assert_not_called()
        a2.unlink()
        self.mock_s3_client.delete_objects.assert_called_once()

    def test_mirror_skips_existing_object(self):
        self.mock_s3_client.head_object.side_effect = None
        self.mock_s3_client.head_object.return_value = {"ContentLength": 11}
        attachment = self._make_attachment()
        attachment._s3_mirror_to_cloud()
        self.mock_s3_client.put_object.assert_not_called()
        self.assertFalse(attachment.s3_mirror_pending)
        self.assertTrue(attachment.s3_blob_name)

    def test_backfill_mirrors_existing(self):
        attachment = self._make_attachment()
        attachment.s3_mirror_pending = False
        self.assertFalse(attachment.s3_blob_name)
        self.env["ir.attachment"]._s3_backfill_to_s3(
            batch_size=1000, commit_each_batch=False
        )
        self.assertTrue(attachment.s3_blob_name)
        self.assertFalse(attachment.s3_mirror_pending)

    def test_backfill_includes_binary_field_attachments(self):
        attachment = self._make_attachment(res_field="image_128")
        attachment.s3_mirror_pending = False
        self.assertFalse(attachment.s3_blob_name)
        self.env["ir.attachment"]._s3_backfill_to_s3(
            batch_size=1000, commit_each_batch=False
        )
        self.assertEqual(attachment.s3_blob_name, attachment.store_fname)
        self.assertFalse(attachment.s3_mirror_pending)

    def test_cron_retries_binary_field_attachments(self):
        attachment = self._make_attachment(res_field="image_128")
        self.assertTrue(attachment.s3_mirror_pending)
        self.env["ir.attachment"]._cron_mirror_pending_to_s3()
        self.assertFalse(attachment.s3_mirror_pending)
        self.assertEqual(attachment.s3_blob_name, attachment.store_fname)

    def test_unlink_keeps_blob_shared_with_binary_field_attachment(self):
        doc = self._make_attachment(name="doc.txt")
        field_att = self._make_attachment(name="field.bin", res_field="image_128")
        doc._s3_mirror_to_cloud()
        field_att._s3_mirror_to_cloud()
        self.assertEqual(doc.s3_blob_name, field_att.s3_blob_name)
        doc.unlink()
        self.mock_s3_client.delete_objects.assert_not_called()

    def test_disabled_environment_skips_s3(self):
        self.env["ir.config_parameter"].set_param("cloud_storage_s3_enabled", "False")
        attachment = self._make_attachment()
        self.assertFalse(attachment.s3_mirror_pending)
        self.env["ir.attachment"]._cron_mirror_pending_to_s3()
        self.env["ir.attachment"]._s3_backfill_to_s3()
        self.mock_s3_client.put_object.assert_not_called()

    def test_unlink_disabled_skips_s3_delete(self):
        attachment = self._make_attachment()
        attachment._s3_mirror_to_cloud()
        self.assertTrue(attachment.s3_blob_name)
        self.env["ir.config_parameter"].set_param("cloud_storage_s3_enabled", "False")
        attachment.unlink()
        self.mock_s3_client.delete_objects.assert_not_called()

    def test_config_available_when_disabled(self):
        self.env["ir.config_parameter"].set_param("cloud_storage_s3_enabled", "False")
        settings = self.env["res.config.settings"].new({})
        self.assertTrue(settings._get_cloud_storage_configuration())

    def test_documents_not_in_unsupported_models(self):
        unsupported = self.env["ir.attachment"]._get_cloud_storage_unsupported_models()
        self.assertNotIn("documents.document", unsupported)
