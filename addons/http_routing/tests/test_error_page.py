import werkzeug.exceptions
from markupsafe import Markup

import odoo.http
from odoo import exceptions
from odoo.exceptions import MissingError
from odoo.http import request
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools.translate import xml_translate


@tagged("-at_install", "post_install")
class TestExceptionCodeValues(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]

    def test_maps_odoo_exceptions_to_their_http_status(self):
        cases = [
            (exceptions.UserError("boom"), 422),
            (exceptions.ValidationError("nope"), 422),
            (exceptions.AccessError("denied"), 403),
            (exceptions.MissingError("gone"), 404),
        ]
        for exception, expected in cases:
            with self.subTest(exception=type(exception).__name__):
                code, values = self.IrHttp._get_exception_code_values(exception)
                self.assertEqual(code, expected)
                self.assertEqual(values["status_code"], expected)

    def test_maps_werkzeug_exceptions_to_their_code(self):
        for exception, expected in [
            (werkzeug.exceptions.NotFound(), 404),
            (
                werkzeug.exceptions.Forbidden("website_visibility_password_required"),
                403,
            ),
            (werkzeug.exceptions.ServiceUnavailable(), 503),
            (werkzeug.exceptions.Gone(), 410),
        ]:
            with self.subTest(exception=type(exception).__name__):
                self.assertEqual(
                    self.IrHttp._get_exception_code_values(exception)[0], expected
                )

    def test_unknown_exception_is_a_500(self):
        code, _values = self.IrHttp._get_exception_code_values(RuntimeError("x"))
        self.assertEqual(code, 500)

    def test_codeless_http_exception_is_named_500(self):
        code, values = self.IrHttp._get_exception_code_values(
            werkzeug.exceptions.HTTPException()
        )
        self.assertEqual(code, 500)
        self.assertEqual(values["status_code"], 500)
        self.assertTrue(values["status_message"])


@tagged("-at_install", "post_install")
class TestErrorHtml(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]

    def setUp(self):
        super().setUp()
        self.rendered = []

        def _render_template(view, template, values=None, **kwargs):
            if not view.env.ref(template, raise_if_not_found=False):
                raise MissingError("No template %s" % template)
            self.rendered.append(template)
            return Markup("<html>%s</html>") % template

        self.patch(self.registry["ir.ui.view"], "_render_template", _render_template)

    def _values(self, code):
        return {
            "status_code": code,
            "status_message": "",
            "error_message": "e",
            "exception": RuntimeError("x"),
            "traceback": "tb",
            "editable": False,
            "debug": False,
        }

    def _render(self, code):
        self.rendered.clear()
        served, html = self.IrHttp._get_error_html(self.env, code, self._values(code))
        self.assertTrue(html)
        return served, self.rendered[-1]

    def test_status_with_a_template_uses_it(self):
        for code in (400, 403, 404, 415, 422, 500):
            with self.subTest(code=code):
                served, template = self._render(code)
                self.assertEqual(served, code)
                self.assertEqual(template, "http_routing.%s" % code)

    def test_4xx_without_a_template_falls_back_to_4xx(self):
        for code in (401, 405, 409, 429):
            with self.subTest(code=code):
                served, template = self._render(code)
                self.assertEqual(served, code)
                self.assertEqual(template, "http_routing.4xx")

    def test_5xx_without_a_template_keeps_its_code(self):
        for code in (501, 502, 503, 504):
            with self.subTest(code=code):
                served, template = self._render(code)
                self.assertEqual(served, code)
                self.assertEqual(template, "http_routing.http_error")


@tagged("-at_install", "post_install")
class TestErrorStatusEndToEnd(HttpCase):
    EP = "/website/translations"

    def _raise(self, exception):
        def _dispatch(endpoint):
            raise exception

        self.patch(self.registry["ir.http"], "_dispatch", _dispatch)

    def test_5xx_without_a_template_reaches_the_client_intact(self):
        self._raise(werkzeug.exceptions.ServiceUnavailable())
        response = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(response.status_code, 503)

    def test_5xx_with_a_template_still_works(self):
        self._raise(werkzeug.exceptions.InternalServerError())
        response = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(response.status_code, 500)

    def test_4xx_without_a_template_reaches_the_client_intact(self):
        self._raise(werkzeug.exceptions.TooManyRequests())
        response = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(response.status_code, 429)

    def test_every_shipped_status_page_renders(self):
        cases = [
            (werkzeug.exceptions.BadRequest(), 400, "Bad Request"),
            (werkzeug.exceptions.Forbidden(), 403, "Forbidden"),
            (werkzeug.exceptions.UnsupportedMediaType(), 415, "Unsupported Media Type"),
            (exceptions.ValidationError("nope"), 422, "Oops! Something went wrong."),
            (werkzeug.exceptions.TooManyRequests(), 429, "Oops! Something went wrong."),
        ]
        for exception, code, heading in cases:
            with self.subTest(code=code):
                self._raise(exception)
                response = self.url_open(self.EP, allow_redirects=False)
                self.assertEqual(response.status_code, code)
                self.assertIn(heading, response.text)

    def test_odoo_exception_keeps_its_http_status(self):
        self._raise(exceptions.ValidationError("nope"))
        response = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(response.status_code, 422)

    def test_error_page_is_never_a_success(self):
        for exception in (
            werkzeug.exceptions.ServiceUnavailable(),
            werkzeug.exceptions.BadGateway(),
            werkzeug.exceptions.HTTPException(),
            RuntimeError("boom"),
        ):
            with self.subTest(exception=type(exception).__name__):
                self._raise(exception)
                response = self.url_open(self.EP, allow_redirects=False)
                self.assertGreaterEqual(response.status_code, 400)

    def test_no_entrypoint_branch_can_answer_a_status_less_exception_with_200(self):
        # The three branches Application.__call__ chooses between -- static,
        # nodb, db -- do not share an error path: only the last two funnel a
        # code-less HTTPException through _serve_aborted. Measured on the tree
        # before the guard moved into HTTPException.get_response, a status-less
        # exception raised from get_static_file, from Request._post_init or
        # from _serve_static each answered *200 OK*; one raised from a handler
        # answered 500. _serve_static is not a corner: it is how every asset on
        # the server is delivered.
        blank = werkzeug.exceptions.HTTPException("no status on this one")

        def _boom(*args, **kwargs):
            raise blank

        for target, attr in (
            (odoo.http.root, "get_static_file"),
            (odoo.http.Request, "_post_init"),
            (odoo.http.Request, "_serve_static"),
        ):
            with self.subTest(raised_in=attr):
                self.patch(target, attr, _boom)
                response = self.url_open(
                    "/web/static/img/favicon.ico", allow_redirects=False
                )
                self.assertGreaterEqual(
                    response.status_code,
                    400,
                    f"a status-less HTTPException from {attr} answered "
                    f"{response.status_code}",
                )

    def test_abort_with_a_response_is_still_delivered_verbatim(self):
        def _dispatch(endpoint):
            werkzeug.exceptions.abort(
                request.redirect("/somewhere-else", code=301, local=True)
            )

        self.patch(self.registry["ir.http"], "_dispatch", _dispatch)
        response = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(response.status_code, 301)
        self.assertURLEqual(response.headers.get("Location"), "/somewhere-else")


@tagged("-at_install", "post_install")
class TestErrorPageTranslatability(TransactionCase):
    PAGES = {
        "400": ["400: Bad Request"],
        "403": ["403: Forbidden"],
        "415": ["415: Unsupported Media Type"],
        "422": ["Oops! Something went wrong."],
        "4xx": ["Oops! Something went wrong."],
    }

    def _terms(self, xmlid):
        view = self.env.ref("http_routing.%s" % xmlid)
        terms = []
        xml_translate(terms.append, view.with_context(lang=None).arch_db)
        return [xml_translate.get_text_content(term) for term in terms]

    def test_headings_are_extracted_as_translatable_terms(self):
        for xmlid, expected in self.PAGES.items():
            with self.subTest(page=xmlid):
                terms = self._terms(xmlid)
                for text in expected:
                    self.assertIn(text, terms)

    def test_the_shared_body_carries_no_stale_copy(self):
        terms = self._terms("error_page")
        for texts in self.PAGES.values():
            for text in texts:
                self.assertNotIn(text, terms)


@tagged("-at_install", "post_install")
class TestErrorTemplateSelection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]

    def test_default_template_follows_the_status(self):
        for code in (403, 404, 500):
            with self.subTest(code=code):
                self.assertEqual(
                    self.IrHttp._get_error_template(code, {}),
                    "http_routing.%s" % code,
                )

    def test_overriding_the_template_leaves_the_status_alone(self):
        rendered = []

        def _render_template(view, template, values=None, **kwargs):
            rendered.append(template)
            return Markup("<html/>")

        self.patch(self.registry["ir.ui.view"], "_render_template", _render_template)
        self.patch(
            self.registry["ir.http"],
            "_get_error_template",
            classmethod(lambda cls, code, values: "some_module.a_custom_404"),
        )
        code, values = self.IrHttp._get_exception_code_values(
            werkzeug.exceptions.NotFound()
        )
        self.assertEqual(code, 404, "the status must survive a template override")
        served, _html = self.IrHttp._get_error_html(self.env, code, values)
        self.assertEqual(served, 404)
        self.assertEqual(rendered, ["some_module.a_custom_404"])
