from os import getenv

from odoo.tests import tagged

from . import test_static

WEB_SERVER_URL = getenv("WEB_SERVER_URL", "http://localhost:80")


@tagged("webserver", "-standard", "-at_install", "post_install")
class TestHttpStaticWebServer(
    test_static.TestHttpStatic, test_static.TestHttpStaticCache
):
    allow_inherited_tests_method = True

    @classmethod
    def base_url(cls):
        return WEB_SERVER_URL

    def assertDownloadGizeh(self, url, x_sendfile=None, assert_filename="gizeh.png"):
        return super().assertDownloadGizeh(
            url, x_sendfile=False, assert_filename=assert_filename
        )

    def assertDownload(
        self,
        url,
        headers,
        assert_status_code,
        assert_headers,
        assert_content=None,
    ):
        assert_headers.pop("Content-Length", None)
        if assert_headers.pop("X-Sendfile", None):
            assert_headers.pop("X-Accel-Redirect", None)
            assert_content = None
        return super().assertDownload(
            url, headers, assert_status_code, assert_headers, assert_content
        )

    def test_static_cache3_private(self):
        super().test_static_cache3_private()

        self.authenticate(None, None)
        self.assertDownloadPlaceholder("/web/image/test_http.gizeh_png")
