import logging
from http import HTTPStatus

import odoo.http
from odoo.tests import get_db_name, tagged
from odoo.tests.common import Like, new_test_user
from odoo.tools import mute_logger
from odoo.tools.misc import submap

from .test_common import TestHttpBase
from odoo.addons import test_http
from odoo.addons.test_http.utils import HtmlTokenizer


@tagged("post_install", "-at_install")
class TestHttpModels(TestHttpBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jackoneill = new_test_user(cls.env, "jackoneill", context={"lang": "en_US"})

    def setUp(self):
        super().setUp()
        self.authenticate("jackoneill", "jackoneill")

    def test_models0_galaxy_ok(self):
        milky_way = self.env.ref("test_http.milky_way")

        res = self.url_open(f"/test_http/{milky_way.id}")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            HtmlTokenizer.tokenize(res.text),
            HtmlTokenizer.tokenize("""\
                <p>Milky Way</p>
                <ul>
                    <li><a href="/test_http/1/1">Earth (P4X-126)</a></li>
                    <li><a href="/test_http/1/2">Abydos (P2X-125)</a></li>
                    <li><a href="/test_http/1/3">Dakara (P5C-113)</a></li>
                </ul>
                """),
        )

    @mute_logger("odoo.http")
    def test_models1_galaxy_ko(self):
        res = self.url_open("/test_http/404")
        self.assertEqual(res.status_code, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("The Ancients did not settle there.", res.text)

    def test_models2_stargate_ok(self):
        milky_way = self.env.ref("test_http.milky_way")
        earth = self.env.ref("test_http.earth")

        res = self.url_open(f"/test_http/{milky_way.id}/{earth.id}")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            HtmlTokenizer.tokenize(res.text),
            HtmlTokenizer.tokenize("""\
                <dl>
                    <dt>name</dt><dd>Earth</dd>
                    <dt>address</dt><dd>sq5Abt</dd>
                    <dt>sgc_designation</dt><dd>P4X-126</dd>
                </dl>
            """),
        )

    def test_models3_stargate_ko(self):
        milky_way = self.env.ref("test_http.milky_way")
        with self.assertLogs("odoo.http.application", level="WARNING") as logs:
            res = self.url_open(f"/test_http/{milky_way.id}/9999")
        self.assertEqual(res.status_code, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("The goauld destroyed the gate", res.text)
        self.assertEqual(
            logs.output,
            ["WARNING:odoo.http.application:The goauld destroyed the gate"],
        )

    def test_models4_stargate_setname(self):
        milky_way = self.env.ref("test_http.milky_way")

        milky_way.invalidate_recordset()
        res = self.url_open(
            f"/test_http/{milky_way.id}/setname?readonly=0",
            {
                "name": "Wilky May",
                "csrf_token": odoo.http.Request.csrf_token(self),
            },
        )
        res.raise_for_status()

        milky_way.invalidate_recordset()
        self.assertEqual(milky_way.name, "Wilky May")

    def test_models5_stargate_setname_readonly(self):
        milky_way = self.env.ref("test_http.milky_way")

        self.assertEqual(milky_way.name, "Milky Way")

        with self.assertLogs("odoo.http._serve", "WARNING") as capture_http:
            res = self.url_open(
                f"/test_http/{milky_way.id}/setname?readonly=1",
                {
                    "name": "Wilky May",
                    "csrf_token": odoo.http.Request.csrf_token(self),
                },
            )
            res.raise_for_status()

        milky_way.invalidate_recordset()
        self.assertEqual(milky_way.name, "Wilky May")
        self.assertEqual(
            capture_http.output,
            [
                Like(
                    "...cannot execute UPDATE in a read-only transaction, retrying with a read/write cursor..."
                ),
            ],
        )
        self.assertIn(f"/test_http/{milky_way.id}/setname", capture_http.output[0])

    def test_models5_max_upload_too_large(self):
        res = self.url_open("/test_http/1/setname", {"name": "too much data" * 1000})
        self.assertEqual(res.status_code, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    def test_models6_rpc_path_poisoning(self):
        with self.assertLogs("werkzeug", logging.INFO) as capture:
            with mute_logger("odoo.addons.rpc.controllers.xmlrpc"):
                self.xmlrpc_object.execute_kw(
                    get_db_name(),
                    self.jackoneill.id,
                    "jackoneill",
                    "res.users",
                    "read",
                    [self.jackoneill.id, ["login"]],
                )
            res = self.url_open("/test_http/wsgi_environ")
            res.raise_for_status()

        self.assertEqual(
            capture.output,
            [
                Like('..."POST /xmlrpc/2/object#res.users.read HTTP/...'),
                Like('..."GET /test_http/wsgi_environ HTTP/...'),
            ],
            "there must be two requests, the first with a fragment, the second without",
        )

        environ = {
            "PATH_INFO": "/test_http/wsgi_environ",
            "QUERY_STRING": "",
            "REQUEST_URI": "/test_http/wsgi_environ",
            "RAW_URI": "/test_http/wsgi_environ",
        }
        self.assertEqual(
            submap(res.json(), environ.keys()),
            environ,
            "the fragment must not leak in the next request",
        )
        self.assertNotIn(
            "#res.users/read",
            res.text,
            "the fragment must not leak in the next request",
        )


@tagged("post_install", "-at_install")
class TestHttpReadonlyPromotion(TestHttpBase):
    def setUp(self):
        super().setUp()
        test_http.controllers.su_on_entry.clear()
        self.addCleanup(test_http.controllers.su_on_entry.clear)

    @mute_logger("odoo.http._serve")
    def test_promotion_replay_does_not_inherit_the_aborted_env(self):
        self.authenticate("admin", "admin")
        milky_way = self.env.ref("test_http.milky_way")

        res = self.url_open(
            f"/test_http/{milky_way.id}/su_setname",
            {"name": "Wilky May"},
        )
        res.raise_for_status()

        entries = test_http.controllers.su_on_entry
        self.assertEqual(
            len(entries),
            2,
            "the handler must have run twice (read-only attempt, then read/write)",
        )
        self.assertEqual(
            entries,
            [False, False],
            "the replay inherited the aborted attempt's superuser escalation",
        )

        milky_way.invalidate_recordset()
        self.assertEqual(milky_way.name, "Wilky May")


@tagged("post_install", "-at_install")
class TestHttpPromotionUpload(TestHttpBase):
    def setUp(self):
        super().setUp()
        test_http.controllers.promotion_upload_reads.clear()
        self.addCleanup(test_http.controllers.promotion_upload_reads.clear)

    @mute_logger("odoo.http._serve")
    def test_promotion_rewinds_the_upload_before_the_replay(self):
        # The read-only -> read/write promotion replays the handler, so the
        # request body has to be rewound first or the replay reads b"" from a
        # stream the first attempt drained. ``upload_file_retry`` covers the
        # *retry* path (a serialization failure inside ``retrying()``); it is
        # not a readonly route, so nothing exercised the promotion branch of
        # ``_serve_db`` with a file attached until this.
        res = self.db_url_open(
            "/test_http/promotion_upload",
            files={"ufile": ("gate.txt", b"Chevron seven", "text/plain")},
        )
        res.raise_for_status()

        reads = test_http.controllers.promotion_upload_reads
        self.assertEqual(
            len(reads),
            2,
            "the handler must have run twice (read-only attempt, then read/write)",
        )
        self.assertEqual(
            reads,
            [b"Chevron seven", b"Chevron seven"],
            "the replay read a drained stream: the upload was not rewound",
        )
        self.assertEqual(res.text, "2")


@tagged("post_install", "-at_install")
class TestHttpRerouteUpload(TestHttpBase):
    def setUp(self):
        super().setUp()
        test_http.controllers.reroute_upload_files.clear()
        self.addCleanup(test_http.controllers.reroute_upload_files.clear)

    def test_reroute_after_body_parse_does_not_stall(self):
        res = self.db_url_open(
            "/test_http/reroute_upload",
            files={"ufile": ("gate.txt", b"Chevron seven", "text/plain")},
        )
        res.raise_for_status()
        self.assertEqual(res.text, "Chevron seven")

    def test_reroute_before_body_parse_closes_the_live_wrapper(self):
        res = self.db_url_open(
            "/test_http/reroute_upload",
            files={"ufile": ("gate.txt", b"Chevron seven", "text/plain")},
            headers={"X-Test-Reroute": "1"},
        )
        res.raise_for_status()
        self.assertEqual(res.text, "Chevron seven")

        (ufile,) = test_http.controllers.reroute_upload_files
        self.assertTrue(
            ufile.stream.closed,
            "the post-reroute wrapper's upload was left open at end of request",
        )


@tagged("post_install", "-at_install")
class TestHttpRetryReplay(TestHttpBase):
    def setUp(self):
        super().setUp()
        test_http.controllers.replay_observations.clear()
        self.addCleanup(test_http.controllers.replay_observations.clear)
        test_http.controllers.should_fail = None
        self.addCleanup(setattr, test_http.controllers, "should_fail", None)

    @mute_logger("odoo.service.model")
    def test_retry_replays_from_a_clean_request_state(self):
        self.authenticate("admin", "admin")
        test_http.controllers.should_fail = True

        res = self.db_url_open("/test_http/retry_replay")
        res.raise_for_status()
        self.assertEqual(res.text, "ok")

        observations = test_http.controllers.replay_observations
        self.assertEqual(len(observations), 2, "the handler must have run twice")
        self.assertEqual(
            [o["su"] for o in observations],
            [False, False],
            "the replay inherited the aborted attempt's superuser escalation",
        )
        self.assertEqual(
            [o["default_env_su"] for o in observations],
            [False, False],
            "the replay flushes through the aborted attempt's escalated default_env",
        )
        self.assertEqual(
            [o["staged_cookies"] for o in observations],
            [0, 0],
            "the replay inherited the aborted attempt's staged Set-Cookie headers",
        )

        probes = [
            v
            for k, v in res.raw.headers.items()
            if k.lower() == "set-cookie" and v.startswith("probe=")
        ]
        self.assertEqual(
            len(probes), 1, f"the probe cookie was emitted once per attempt: {probes}"
        )
