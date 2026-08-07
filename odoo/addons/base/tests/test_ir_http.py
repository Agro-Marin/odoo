import logging
import re
import time
from contextlib import contextmanager
from types import SimpleNamespace

from odoo.exceptions import AccessDenied
from odoo.http import SessionExpiredException
from odoo.http.core import _request_stack
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


@tagged("-at_install", "post_install")
class TestIrHttpPerformances(TransactionCase):
    def test_routing_map_performance(self):
        self.env.registry.clear_cache("routing")
        re._cache.clear()

        self.env.registry.clear_cache("routing")
        start = time.time()
        self.env["ir.http"].routing_map()
        duration = time.time() - start
        _logger.info("Routing map web generated in %.3fs", duration)

        start = time.time()
        self.env["ir.http"].routing_map(key=1)
        duration = time.time() - start
        _logger.info("Routing map website1 generated in %.3fs", duration)


class TestIrHttpAuth(TransactionCase):
    @contextmanager
    def _fake_request(self, env, path="/"):
        fake = SimpleNamespace(env=env, httprequest=SimpleNamespace(path=path))
        _request_stack.push(fake)
        try:
            yield fake
        finally:
            _request_stack.pop()

    def test_auth_method_user_rejects_public(self):
        public_uid = self.env.ref("base.public_user").id
        with self._fake_request(self.env(user=public_uid)):
            with self.assertRaises(SessionExpiredException):
                self.registry["ir.http"]._auth_method_user()

    def test_authenticate_explicit_unknown_method(self):
        with self._fake_request(self.env) as fake:
            fake.session = SimpleNamespace(uid=None)
            with self.assertRaises(AccessDenied):
                self.registry["ir.http"]._authenticate_explicit("does_not_exist")

    def test_serve_fallback_skips_non_public(self):
        path = "/non_public_fallback_probe"
        self.env["ir.attachment"].sudo().create(
            {
                "name": "probe.bin",
                "type": "binary",
                "url": path,
                "raw": b"secret",
                "public": False,
            }
        )
        with self._fake_request(self.env, path=path):
            self.assertIsNone(
                self.registry["ir.http"]._serve_fallback(),
                "non-public binary attachment must not be served by the fallback",
            )

    def test_serve_attachment_public_filter(self):
        path = "/serve_attachment_public_filter_probe"
        Attachment = self.env["ir.attachment"].sudo()
        non_public = Attachment.create(
            {
                "name": "private.bin",
                "type": "binary",
                "url": path,
                "raw": b"secret",
                "public": False,
            }
        )
        public = Attachment.create(
            {
                "name": "public.bin",
                "type": "binary",
                "url": path,
                "raw": b"hello",
                "public": True,
            }
        )
        served = Attachment._get_serve_attachment(
            path, extra_domain=[("public", "=", True)]
        )
        self.assertEqual(
            served,
            public,
            "only the public attachment should match the fallback domain",
        )
        self.assertNotEqual(served, non_public)
