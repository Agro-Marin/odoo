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
        # Measure the cold state: drop any compiled-regex cache a prior routing
        # map may have left behind.
        re._cache.clear()

        self.env.registry.clear_cache("routing")
        start = time.time()
        self.env["ir.http"].routing_map()
        duration = time.time() - start
        _logger.info("Routing map web generated in %.3fs", duration)

        # second website: check we reuse anything the first routing map computed
        start = time.time()
        self.env["ir.http"].routing_map(key=1)
        duration = time.time() - start
        _logger.info("Routing map website1 generated in %.3fs", duration)


class TestIrHttpAuth(TransactionCase):
    """Base-level coverage for the auth methods and the URL fallback (IHTTP-T1, security-critical)."""

    @contextmanager
    def _fake_request(self, env, path="/"):
        """Push a minimal fake ``request`` exposing ``env`` onto the stack, so
        classmethods reading only ``request.env``/``request.httprequest`` run
        without a live WSGI request.
        """
        fake = SimpleNamespace(env=env, httprequest=SimpleNamespace(path=path))
        _request_stack.push(fake)
        try:
            yield fake
        finally:
            _request_stack.pop()

    def test_auth_method_user_rejects_public(self):
        """``_auth_method_user`` rejects a not-logged-in (public) user.

        Covers the ``uid in [None] + _get_public_users()`` branch: the public
        user (and an anonymous uid=None env) counts as not logged in.
        """
        public_uid = self.env.ref("base.public_user").id
        with self._fake_request(self.env(user=public_uid)):
            with self.assertRaises(SessionExpiredException):
                self.registry["ir.http"]._auth_method_user()

    def test_authenticate_explicit_unknown_method(self):
        """An unknown ``auth=`` value fails closed with AccessDenied (IHTTP-M3)."""
        with self._fake_request(self.env) as fake:
            # no stored session, so _authenticate_explicit goes straight to
            # the auth-method dispatch
            fake.session = SimpleNamespace(uid=None)
            with self.assertRaises(AccessDenied):
                self.registry["ir.http"]._authenticate_explicit("does_not_exist")

    def test_serve_fallback_skips_non_public(self):
        """The URL fallback must NOT serve a non-public binary attachment.

        Regression pin for IHTTP-L3: ``_serve_fallback`` searches under
        ``sudo()``; without the ``public=True`` filter a non-public attachment
        on an unmatched path would be served to anonymous callers.
        """
        path = "/non_public_fallback_probe"
        # sudo() create bypasses the write-time serving guard, mirroring the
        # residual risk the fix hardens against.
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
        """The fallback domain (``public=True``) selects only public rows (IHTTP-L3).

        Asserts the ``extra_domain=[('public', '=', True)]`` filter that
        ``_serve_fallback`` passes to ``_get_serve_attachment`` directly.
        """
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
