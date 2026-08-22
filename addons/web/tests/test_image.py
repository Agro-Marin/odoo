import base64
import io
from datetime import datetime, timedelta
from urllib.parse import unquote_plus

from freezegun import freeze_time
from PIL import Image

from odoo.tests.common import HttpCase, new_test_user, tagged
from odoo.tools.misc import limited_field_access_token


@tagged("-at_install", "post_install", "web_http", "web_image")
class TestImage(HttpCase):
    def test_01_content_image_resize_placeholder(self):
        response = self.url_open("/web/image/0/200x150")
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.size, (150, 150))

        response = self.url_open("/web/image/fake/0/image_128")
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.size, (128, 128))

        response = self.url_open("/web/image/fake/0/image_256")
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.size, (256, 256))

        response = self.url_open("/web/image/fake/0/image_1024")
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.size, (256, 256))

        response = self.url_open("/web/image/fake/0/image_no_size")
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.size, (256, 256))

    def test_01b_broken_image_download_false_serves_placeholder(self):
        resp = self.url_open("/web/image/fake/0/image_128?download=false")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("image/"))
        resp = self.url_open("/web/image/fake/0/image_128?download=true")
        self.assertEqual(resp.status_code, 404)

    def test_01c_malformed_id_is_not_a_server_error(self):
        for bad_id in ("abc", "1e9", " ", "1.5", "0x10", "-", "%00"):
            with self.subTest(id=bad_id):
                resp = self.url_open(f"/web/image?id={bad_id}")
                self.assertEqual(
                    resp.status_code,
                    200,
                    f"/web/image?id={bad_id} should serve the placeholder",
                )
                self.assertTrue(resp.headers["Content-Type"].startswith("image/"))

                resp = self.url_open(f"/web/content?id={bad_id}")
                self.assertEqual(
                    resp.status_code,
                    404,
                    f"/web/content?id={bad_id} should 404",
                )

        self.assertEqual(self.url_open("/web/image?id=999999999").status_code, 200)
        self.assertEqual(self.url_open("/web/content?id=999999999").status_code, 404)

    def test_01d_asset_nocache_is_coerced(self):
        url = "/web/assets/any/web.assets_web.min.css"
        cached = self.url_open(url).headers.get("Cache-Control", "")
        self.assertIn("max-age", cached)
        self.assertIn("immutable", cached)

        for falsy in ("false", "0", "False"):
            with self.subTest(nocache=falsy):
                headers = self.url_open(f"{url}?nocache={falsy}").headers
                self.assertEqual(
                    headers.get("Cache-Control", ""),
                    cached,
                    "a falsy nocache must not disable caching",
                )

        opted_out = self.url_open(f"{url}?nocache=true").headers.get(
            "Cache-Control", ""
        )
        self.assertNotIn("max-age=", opted_out)
        self.assertNotIn("immutable", opted_out)

    def test_02_content_image_Etag_304(self):
        attachment = self.env["ir.attachment"].create(
            {
                "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "testEtag.gif",
                "public": True,
                "mimetype": "image/gif",
            }
        )
        response = self.url_open("/web/image/%s" % attachment.id, timeout=None)
        response.raise_for_status()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(base64.b64encode(response.content), attachment.datas)

        etag = response.headers.get("ETag")

        response2 = self.url_open(
            "/web/image/%s" % attachment.id, headers={"If-None-Match": etag}
        )
        response2.raise_for_status()
        self.assertEqual(response2.status_code, 304)
        self.assertEqual(len(response2.content), 0)

    def test_03_web_content_filename(self):
        att = self.env["ir.attachment"].create(
            {
                "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "testFilename.gif",
                "public": True,
                "mimetype": "image/gif",
            }
        )

        res = self.url_open("/web/image/%s/0x0/?download=true" % att.id)
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"],
            "attachment; filename=testFilename.gif",
        )

        res = self.url_open("/web/image/%s/0x0/custom?download=true" % att.id)
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"],
            "attachment; filename=custom.gif",
        )

        res = self.url_open("/web/image/%s/0x0/custom.png?download=true" % att.id)
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"],
            "attachment; filename=custom.png",
        )

    def test_04_web_content_filename_secure(self):
        att = self.env["ir.attachment"].create(
            {
                "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": """fô☺o-l'éb \n a"!r".gif""",
                "public": True,
                "mimetype": "image/gif",
            }
        )

        def assert_filenames(
            url,
            expected_filename,
            expected_filename_star="",
            message=r"File that will be saved on disc should have the original filename without \n and \r",
        ):
            res = self.url_open(url)
            res.raise_for_status()
            if expected_filename_star:
                inline, filename, filename_star = res.headers[
                    "Content-Disposition"
                ].split("; ")
            else:
                inline, filename = res.headers["Content-Disposition"].split("; ")
                filename_star = ""

            filename = filename.removeprefix("filename=").strip('"')
            filename_star = unquote_plus(
                filename_star.removeprefix("filename*=UTF-8''").strip('"')
            )

            self.assertEqual(inline, "inline")
            self.assertEqual(filename, expected_filename, message)
            self.assertEqual(filename_star, expected_filename_star, message)

        assert_filenames(
            f"/web/image/{att.id}",
            r"""foo-l'eb _ a\"!r\".gif""",
            r"""fô☺o-l'éb _ a"!r".gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/custom_invalid_name\nis-ok.gif",
            r"""custom_invalid_name_is-ok.gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/\r\n",
            r"""__.gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/你好",
            r""".gif""",
            r"""你好.gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/%E9%9D%A2%E5%9B%BE.gif",
            r""".gif""",
            r"""面图.gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/hindi_नमस्ते.gif",
            r"""hindi_.gif""",
            r"""hindi_नमस्ते.gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/arabic_مرحبا",
            r"""arabic_.gif""",
            r"""arabic_مرحبا.gif""",
        )
        assert_filenames(
            f"/web/image/{att.id}/4wzb_!!63148-0-t1.jpg_360x1Q75.jpg_.webp",
            r"""4wzb_!!63148-0-t1.jpg_360x1Q75.jpg_.webp""",
        )

    def test_05_web_image_access_token(self):
        def get_datetime_from_token(token):
            return datetime.fromtimestamp(int(token.rsplit("o", 1)[1], 16))

        attachment = self.env["ir.attachment"].create(
            {
                "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                "name": "test.gif",
                "mimetype": "image/gif",
            }
        )
        res = self.url_open(f"/web/image/{attachment.id}")
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"],
            "inline; filename=placeholder.png",
        )
        res = self.url_open(f"/web/image/{attachment.id}?access_token=invalid_token")
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"],
            "inline; filename=placeholder.png",
        )
        token = limited_field_access_token(attachment, "raw", scope="other_scope")
        res = self.url_open(f"/web/image/{attachment.id}?access_token={token}")
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"],
            "inline; filename=placeholder.png",
        )
        token = attachment._get_raw_access_token()
        res = self.url_open(f"/web/image/{attachment.id}?access_token={token}")
        res.raise_for_status()
        self.assertEqual(
            res.headers["Content-Disposition"], "inline; filename=test.gif"
        )
        with freeze_time(get_datetime_from_token(token) - timedelta(seconds=1)):
            res = self.url_open(f"/web/image/{attachment.id}?access_token={token}")
            res.raise_for_status()
            self.assertEqual(
                res.headers["Content-Disposition"], "inline; filename=test.gif"
            )
        with freeze_time(get_datetime_from_token(token)):
            res = self.url_open(f"/web/image/{attachment.id}?access_token={token}")
            res.raise_for_status()
            self.assertEqual(
                res.headers["Content-Disposition"],
                "inline; filename=placeholder.png",
            )
        start_of_period = datetime(2021, 2, 18, 0, 0, 0)
        base_result = datetime(2021, 3, 24, 15, 25, 40)
        for i in range(14):
            with freeze_time(
                start_of_period + timedelta(days=i, hours=i % 24, minutes=i % 60)
            ):
                self.assertEqual(
                    get_datetime_from_token(
                        self.env["ir.attachment"].browse(2)._get_raw_access_token()
                    ),
                    base_result,
                )
        for i in range(50):
            with freeze_time(
                start_of_period
                + timedelta(days=14 * i + i % 14, hours=i % 24, minutes=i % 60)
            ):
                self.assertEqual(
                    get_datetime_from_token(
                        self.env["ir.attachment"].browse(2)._get_raw_access_token()
                    ),
                    base_result + timedelta(days=14 * i),
                )
        with freeze_time(datetime(2021, 3, 1, 1, 2, 3)):
            self.assertEqual(
                get_datetime_from_token(
                    self.env["ir.attachment"].browse(2)._get_raw_access_token()
                ),
                base_result,
            )
            record_res = self.env["ir.attachment"].browse(3)._get_raw_access_token()
            self.assertNotIn(record_res, [base_result])
            field_res = get_datetime_from_token(
                limited_field_access_token(
                    self.env["ir.attachment"].browse(3), "datas", scope="binary"
                )
            )
            self.assertNotIn(field_res, [base_result, record_res])
            model_res = get_datetime_from_token(
                limited_field_access_token(
                    self.env["res.partner"].browse(3), "raw", scope="binary"
                )
            )
            self.assertNotIn(model_res, [base_result, record_res, field_res])

    def test_06_web_image_attachment_access(self):
        new_test_user(self.env, "portal_user", groups="base.group_portal")
        new_test_user(self.env, "internal_user")
        restricted_record = self.env["res.users.settings"].create(
            {"user_id": self.env.user.id}
        )
        accessible_record = self.env["res.partner"].create({"name": "test partner"})
        attachments = self.env["ir.attachment"].create(
            [
                {
                    "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "description": "restricted attachment",
                    "name": "test.gif",
                    "res_id": restricted_record.id,
                    "res_model": restricted_record._name,
                },
                {
                    "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "description": "restricted attachment",
                    "name": "test.gif",
                    "res_id": accessible_record.id,
                    "res_model": accessible_record._name,
                },
                {
                    "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "description": "standalone attachment",
                    "name": "test.gif",
                },
                {
                    "datas": b"R0lGODdhAQABAIAAAP///////ywAAAAAAQABAAACAkQBADs=",
                    "description": "public attachment",
                    "name": "test.gif",
                    "public": True,
                },
            ]
        )
        attachments.generate_access_token()
        internal_restricted, internal_accessible, standalone, public = attachments
        tests = [
            (internal_restricted, "public_user", None, False),
            (internal_restricted, "public_user", "token", True),
            (internal_restricted, "public_user", "limited token", True),
            (internal_restricted, "portal_user", None, False),
            (internal_restricted, "portal_user", "token", True),
            (internal_restricted, "portal_user", "limited token", True),
            (internal_restricted, "internal_user", None, False),
            (internal_restricted, "internal_user", "token", True),
            (internal_restricted, "internal_user", "limited token", True),
            (internal_accessible, "public_user", None, False),
            (internal_accessible, "public_user", "token", True),
            (internal_accessible, "public_user", "limited token", True),
            (internal_accessible, "portal_user", None, False),
            (internal_accessible, "portal_user", "token", True),
            (internal_accessible, "portal_user", "limited token", True),
            (internal_accessible, "internal_user", None, True),
            (internal_accessible, "internal_user", "token", True),
            (internal_accessible, "internal_user", "limited token", True),
            (standalone, "public_user", None, False),
            (standalone, "public_user", "token", True),
            (standalone, "public_user", "limited token", True),
            (standalone, "portal_user", None, False),
            (standalone, "portal_user", "token", True),
            (standalone, "portal_user", "limited token", True),
            (standalone, "internal_user", None, False),
            (standalone, "internal_user", "token", True),
            (standalone, "internal_user", "limited token", True),
            (public, "public_user", None, True),
            (public, "public_user", "token", True),
            (public, "public_user", "limited token", True),
            (public, "portal_user", None, True),
            (public, "portal_user", "token", True),
            (public, "portal_user", "limited token", True),
            (public, "internal_user", None, True),
            (public, "internal_user", "token", True),
            (public, "internal_user", "limited token", True),
        ]
        for attachment, user, token, result in tests:
            login = None if user == "public_user" else user
            self.authenticate(login, login)
            access_token_param = ""
            if token:
                access_token = (
                    attachment.access_token
                    if token == "token"
                    else attachment._get_raw_access_token()
                )
                access_token_param = f"?access_token={access_token}"
            res = self.url_open(f"/web/image/{attachment.id}{access_token_param}")
            if result:
                self.assertEqual(
                    res.headers["Content-Disposition"],
                    "inline; filename=test.gif",
                    f"{user} should have access to {attachment.description} with {token or 'no token'}",
                )
            else:
                self.assertEqual(
                    res.headers["Content-Disposition"],
                    "inline; filename=placeholder.png",
                    f"{user} should not have access to {attachment.description} with {token or 'no token'}",
                )
