from datetime import datetime
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.cloud_drive_s3.tools import s3_drive

_HEAD_404 = ClientError({"Error": {"Code": "404"}}, "HeadObject")


@tagged("post_install", "-at_install")
class TestS3DriveKeyHelpers(TransactionCase):
    def test_clean_rel_normalizes(self):
        self.assertEqual(s3_drive._clean_rel(self.env, "/a//b/./c/"), "a/b/c")
        self.assertEqual(s3_drive._clean_rel(self.env, ""), "")

    def test_clean_rel_rejects_traversal(self):
        for bad in ("a/../b", "../etc", "a\\b", "a/b\x00c"):
            with self.assertRaises(UserError):
                s3_drive._clean_rel(self.env, bad)

    def test_full_key_prefixes_and_requires_path(self):
        self.assertEqual(s3_drive._full_key(self.env, "Conta/x.pdf"), "Conta/x.pdf")
        with self.assertRaises(UserError):
            s3_drive._full_key(self.env, "")

    def test_full_prefix(self):
        self.assertEqual(s3_drive._full_prefix(self.env, ""), "")
        self.assertEqual(s3_drive._full_prefix(self.env, "Conta"), "Conta/")


@tagged("post_install", "-at_install")
class TestS3DriveOperations(TransactionCase):
    def _client(self):
        return MagicMock()

    def test_list_path_parses_folders_and_hides_markers(self):
        client = self._client()
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        now = datetime(2026, 7, 18, 12, 0, 0)
        paginator.paginate.return_value = [
            {
                "CommonPrefixes": [{"Prefix": "Conta/"}],
                "Contents": [
                    {"Key": "factura.pdf", "Size": 12, "LastModified": now},
                    {"Key": "Conta/", "Size": 0, "LastModified": now},
                ],
            }
        ]
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            res = s3_drive.list_path(self.env, "")
        self.assertEqual([f["name"] for f in res["folders"]], ["Conta"])
        self.assertEqual([f["path"] for f in res["folders"]], ["Conta"])
        self.assertEqual([f["name"] for f in res["files"]], ["factura.pdf"])
        self.assertEqual(res["files"][0]["key"], "factura.pdf")

    def test_presign_upload_uses_post_policy_with_size_cap(self):
        client = self._client()
        client.generate_presigned_post.return_value = {
            "url": "https://signed",
            "fields": {"key": "x.pdf", "Content-Type": "application/pdf"},
        }
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            res = s3_drive.presign_upload(
                self.env, "x.pdf", content_type="application/pdf"
            )
        self.assertEqual(res["url"], "https://signed")
        _, kwargs = client.generate_presigned_post.call_args
        self.assertEqual(kwargs["Key"], "x.pdf")
        self.assertEqual(kwargs["Fields"]["Content-Type"], "application/pdf")
        self.assertIn(
            ["content-length-range", 0, s3_drive.MAX_UPLOAD_BYTES],
            kwargs["Conditions"],
        )
        self.assertIn({"Content-Type": "application/pdf"}, kwargs["Conditions"])

    def test_make_folder_writes_zero_byte_marker(self):
        client = self._client()
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.make_folder(self.env, "Conta", "2026")
        _, kwargs = client.put_object.call_args
        self.assertEqual(kwargs["Key"], "Conta/2026/")
        self.assertEqual(kwargs["Body"], b"")

    def test_delete_folder_refuses_non_empty(self):
        client = self._client()
        client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "Conta/"},
                {"Key": "Conta/x.pdf"},
            ]
        }
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.delete_folder(self.env, "Conta")
        client.delete_object.assert_not_called()

    def test_copy_file(self):
        client = self._client()
        client.head_object.side_effect = _HEAD_404
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.copy_file(self.env, "a.txt", "b.txt")
        _, kwargs = client.copy_object.call_args
        self.assertEqual(kwargs["Key"], "b.txt")
        self.assertEqual(kwargs["CopySource"], {"Bucket": "bucket", "Key": "a.txt"})

    def test_copy_refuses_to_overwrite_existing_destination(self):
        client = self._client()
        client.head_object.return_value = {"ContentLength": 1}
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.copy_file(self.env, "a.txt", "b.txt")
        client.copy_object.assert_not_called()

    def test_move_file_copies_then_deletes(self):
        client = self._client()
        client.head_object.side_effect = _HEAD_404
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.move_file(self.env, "a.txt", "sub/c.txt")
        client.copy_object.assert_called_once()
        client.delete_object.assert_called_once_with(Bucket="bucket", Key="a.txt")

    def test_move_refuses_to_overwrite_existing_destination(self):
        client = self._client()
        client.head_object.return_value = {"ContentLength": 1}
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.move_file(self.env, "a.txt", "b.txt")
        client.copy_object.assert_not_called()
        client.delete_object.assert_not_called()

    def test_object_info(self):
        client = self._client()
        client.head_object.return_value = {
            "ContentLength": 10,
            "LastModified": datetime(2026, 7, 18, 12, 0, 0),
            "ContentType": "image/png",
            "ETag": '"abc123"',
        }
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            info = s3_drive.object_info(self.env, "x.png")
        self.assertEqual(info["size"], 10)
        self.assertEqual(info["content_type"], "image/png")
        self.assertEqual(info["etag"], "abc123")

    def test_list_path_adds_preview_for_images(self):
        client = self._client()
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        client.generate_presigned_url.return_value = "https://thumb"
        now = datetime(2026, 7, 18, 12, 0, 0)
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "photo.png", "Size": 5, "LastModified": now},
                    {"Key": "notes.txt", "Size": 3, "LastModified": now},
                ]
            }
        ]
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            res = s3_drive.list_path(self.env, "")
        by_name = {f["name"]: f for f in res["files"]}
        self.assertTrue(by_name["photo.png"]["is_image"])
        self.assertEqual(by_name["photo.png"]["preview_url"], "https://thumb")
        self.assertFalse(by_name["notes.txt"]["is_image"])
        self.assertNotIn("preview_url", by_name["notes.txt"])

    def test_presign_download_signs_get_url(self):
        client = self._client()
        client.generate_presigned_url.return_value = "https://signed-get"
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            url = s3_drive.presign_download(self.env, "Conta/x.pdf")
        self.assertEqual(url, "https://signed-get")
        args, kwargs = client.generate_presigned_url.call_args
        self.assertEqual(args[0], "get_object")
        self.assertEqual(kwargs["Params"]["Key"], "Conta/x.pdf")

    def test_presign_download_forces_attachment_disposition(self):
        client = self._client()
        client.generate_presigned_url.return_value = "https://signed-get"
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.presign_download(self.env, "Conta/notes.html")

        _, kwargs = client.generate_presigned_url.call_args
        self.assertEqual(kwargs["Params"]["ResponseContentDisposition"], "attachment")

    def test_image_preview_stays_inline(self):
        client = self._client()
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        client.generate_presigned_url.return_value = "https://thumb"
        now = datetime(2026, 7, 18, 12, 0, 0)
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "photo.png", "Size": 5, "LastModified": now}]}
        ]
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.list_path(self.env, "")

        _, kwargs = client.generate_presigned_url.call_args
        self.assertNotIn("ResponseContentDisposition", kwargs["Params"])

    def test_delete_file(self):
        client = self._client()
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.delete_file(self.env, "Conta/x.pdf")
        client.delete_object.assert_called_once_with(Bucket="bucket", Key="Conta/x.pdf")

    def test_make_folder_rejects_invalid_name(self):
        for bad in ("", "a/b", ".", ".."):
            with self.assertRaises(UserError):
                s3_drive.make_folder(self.env, "Conta", bad)

    def test_copy_same_src_dst_raises(self):
        client = self._client()
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.copy_file(self.env, "a.txt", "a.txt")
        client.copy_object.assert_not_called()

    def test_move_same_src_dst_is_noop(self):
        client = self._client()
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.move_file(self.env, "a.txt", "a.txt")
        client.copy_object.assert_not_called()
        client.delete_object.assert_not_called()
        client.head_object.assert_not_called()

    def test_connection_ok_when_versioning_enabled(self):
        client = self._client()
        client.get_bucket_versioning.return_value = {"Status": "Enabled"}
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            self.assertEqual(s3_drive.test_connection(self.env), "bucket")
        client.head_bucket.assert_called_once_with(Bucket="bucket")
        client.get_bucket_versioning.assert_called_once_with(Bucket="bucket")

    def test_connection_fails_when_versioning_not_enabled(self):
        client = self._client()
        client.get_bucket_versioning.return_value = {"Status": "Suspended"}
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.test_connection(self.env)

    def _folder_client(self, keys):
        client = self._client()
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": [{"Key": k} for k in keys]}]
        client.list_objects_v2.return_value = {"Contents": []}
        return client

    def test_copy_folder_recurses_over_prefix(self):
        client = self._folder_client(["Conta/", "Conta/x.pdf", "Conta/sub/y.txt"])
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.copy_folder(self.env, "Conta", "Archivo/Conta")
        dst_keys = {c.kwargs["Key"] for c in client.copy_object.call_args_list}
        self.assertEqual(
            dst_keys,
            {"Archivo/Conta/", "Archivo/Conta/x.pdf", "Archivo/Conta/sub/y.txt"},
        )
        client.delete_objects.assert_not_called()

    def test_move_folder_copies_then_batch_deletes(self):
        client = self._folder_client(["Conta/", "Conta/x.pdf"])
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.move_folder(self.env, "Conta", "Archivo")
        self.assertEqual(client.copy_object.call_count, 2)
        _, kwargs = client.delete_objects.call_args
        deleted = {o["Key"] for o in kwargs["Delete"]["Objects"]}
        self.assertEqual(deleted, {"Conta/", "Conta/x.pdf"})

    def test_move_folder_refuses_nesting_into_itself(self):
        client = self._folder_client(["Conta/", "Conta/x.pdf"])
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.move_folder(self.env, "Conta", "Conta/Sub")
        client.copy_object.assert_not_called()

    def test_move_folder_refuses_existing_destination(self):
        client = self._folder_client(["Conta/", "Conta/x.pdf"])
        client.list_objects_v2.return_value = {"Contents": [{"Key": "Archivo/z"}]}
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            with self.assertRaises(UserError):
                s3_drive.move_folder(self.env, "Conta", "Archivo")
        client.copy_object.assert_not_called()

    def test_copy_folder_refuses_sibling_prefix_false_positive(self):
        client = self._folder_client(["Cont/", "Cont/a.txt"])
        with patch.object(
            s3_drive, "get_drive_client", return_value=(client, "bucket")
        ):
            s3_drive.copy_folder(self.env, "Cont", "Conta")
        self.assertEqual(client.copy_object.call_count, 2)
