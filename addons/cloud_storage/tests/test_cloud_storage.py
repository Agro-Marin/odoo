# Part of Odoo. See LICENSE file for full copyright and licensing details.

import uuid

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCloudStorage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.attachment = cls.env["ir.attachment"].create(
            {"name": "cloud.txt", "raw": b"payload"}
        )

    def test_generate_url_is_abstract(self):
        """The provider-agnostic base leaves blob URL generation unimplemented."""
        with self.assertRaises(NotImplementedError):
            self.attachment._generate_cloud_storage_url()

    def test_generate_download_info_is_abstract(self):
        """The base module has no download-info implementation."""
        with self.assertRaises(NotImplementedError):
            self.attachment._generate_cloud_storage_download_info()

    def test_generate_upload_info_is_abstract(self):
        """The base module has no upload-info implementation."""
        with self.assertRaises(NotImplementedError):
            self.attachment._generate_cloud_storage_upload_info()

    def test_post_add_create_without_provider_raises(self):
        """Flagging an attachment as cloud storage needs an enabled provider."""
        self.env["ir.config_parameter"].sudo().set_param("cloud_storage_provider", "")
        with self.assertRaises(UserError):
            self.attachment._post_add_create(cloud_storage=True)

    def test_blob_name_is_scoped_to_attachment(self):
        """The blob name embeds the attachment id, a uuid4, and the file name."""
        blob_name = self.attachment._generate_cloud_storage_blob_name()
        prefix, token, name = blob_name.split("/")
        self.assertEqual(prefix, str(self.attachment.id))
        self.assertEqual(name, self.attachment.name)
        # a malformed token would raise ValueError and fail the test
        self.assertEqual(str(uuid.UUID(token)), token)

    def test_get_values_reports_min_file_size_in_mb(self):
        """Settings expose the byte threshold converted to megabytes."""
        self.env["ir.config_parameter"].sudo().set_param(
            "cloud_storage_min_file_size", "30000000"
        )
        values = self.env["res.config.settings"].get_values()
        self.assertEqual(values["cloud_storage_min_file_size_mb"], 30)
