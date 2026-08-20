"""Claims made by the 2026-08-16 `mixin.mail.render` audit, written as assertions.

Each test states the behaviour the audit argues *should* hold. A test that fails
is the audit's evidence; a test that passes is a claim the audit got wrong. The
docstrings name which is which at the time of writing so the file doubles as the
audit's own falsification record.
"""

import base64
import io

from markupsafe import Markup
from PIL import Image

from odoo.exceptions import AccessError, MissingError, UserError
from odoo.tests import tagged, users

from odoo.addons.mail.tests import common


@tagged("mail_render", "post_install", "-at_install")
class TestRendererEquivalence(common.MailCommon):
    """Where the two `t-out` renderers agree, and where they differ on purpose.

    `_render_template_qweb` picks between an evaluation-free renderer and QWeb
    on whether the template needs an evaluator. It used to decide that on
    whether *any* `t-out` element carried an extra attribute -- a property of
    the template's presentation, not of its expressions -- so this class forced
    the QWeb path by adding `style="color:red"`. Presentational attributes no
    longer force anything (see `TestPresentationalAttributes`), and the
    discriminator is now the expression: an allow-listed path renders without
    an evaluator, anything else with one.

    `TestRegexRendering.test_qweb_regex_rendering` in `mail` specifies the
    evaluation-free renderer's semantics case by case, including two that differ
    from QWeb by design (a valueless `t-out` keeps its empty element; a default
    body is stripped). Those are the contract, not drift.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["mail.test.track"].create(
            {
                "name": "Rec",
                "email_from": "rec@test.example.com",
                "user_id": cls.env.uid,
            }
        )
        cls.record_empty = cls.env["mail.test.track"].create(
            {"name": "", "email_from": "empty@test.example.com"}
        )
        cls.model = "mail.test.track"

    def _both(self, expression, default="", record=None):
        """Render the same value twice, once per renderer.

        The evaluating path is reached by wrapping the expression in something
        no allow-list holds -- `x or None` is the value of `x` -- rather than by
        decorating the element, which no longer decides anything.
        """
        record = record or self.record
        mixin = self.env["mixin.mail.render"]
        bare = f'<p t-out="{expression}">{default}</p>'
        evaluated = f'<p t-out="{expression} or None">{default}</p>'
        self.assertFalse(
            mixin._has_unsafe_expression_template_qweb(bare, self.model),
            "precondition: the bare form must take the evaluation-free path",
        )
        self.assertTrue(
            mixin._has_unsafe_expression_template_qweb(evaluated, self.model),
            "precondition: the wrapped form must take the QWeb path",
        )

        def render(src):
            try:
                return str(
                    mixin._render_template_qweb(src, self.model, [record.id])[record.id]
                )
            except Exception as err:
                return f"{type(err).__name__}"

        return render(bare), render(evaluated)

    def test_recordset_renders_as_display_name_on_both_paths(self):
        """AUDIT F1 — expected to FAIL: QWeb renders the recordset repr.

        `object.partner_id` and `object.user_id` are in the default
        `mail_allowed_qweb_expressions()`, and the inline engine already maps a
        recordset to its display name through `_format_template_value`.
        """
        static, dynamic = self._both("object.user_id")
        self.assertNotIn(
            "res.users(", dynamic, "a recordset repr reached the email body"
        )
        self.assertEqual(static, dynamic)

    def test_inline_and_qweb_agree_on_a_recordset(self):
        """AUDIT F1 — expected to FAIL: the two engines format recordsets differently."""
        mixin = self.env["mixin.mail.render"]
        inline = mixin._render_template_inline_template(
            "{{ object.user_id }}", self.model, [self.record.id]
        )[self.record.id]
        qweb = str(
            mixin._render_template_qweb(
                '<t t-out="object.user_id or None"/>',
                self.model,
                [self.record.id],
            )[self.record.id]
        )
        self.assertEqual(str(inline), qweb)

    def test_the_specified_divergences_are_the_specified_ones(self):
        """AUDIT F2/F3/F4 — NOT defects. The audit's first draft called them that.

        `mail`'s own `TestRegexRendering.test_qweb_regex_rendering` pins each of
        these against a literal expected string, so they are the evaluation-free
        renderer's specified behaviour:

        * a `t-out` whose value is missing or falsy keeps its empty element,
          where QWeb emits nothing at all;
        * a default body is emitted stripped, where QWeb emits it verbatim;
        * an allow-listed path the model does not have renders empty, where
          QWeb raises.

        This test exists so that a future reader who spots the divergence finds
        out it was considered, rather than re-deriving it and "fixing" it into a
        red suite -- which is what happened here.
        """
        mixin = self.env["mixin.mail.render"]

        def static(src, record):
            return str(
                mixin._render_template_qweb(src, self.model, [record.id])[record.id]
            )

        self.assertEqual(
            static('<p t-out="object.user_id.name"/>', self.record_empty),
            "<p></p>",
            "valueless t-out must keep its element; QWeb would emit nothing",
        )
        self.assertEqual(
            static(
                '<p t-out="object.user_id.name">  fallback  </p>', self.record_empty
            ),
            "<p>fallback</p>",
            "the default body is stripped; QWeb would keep the whitespace",
        )
        self.assertEqual(
            static('<p t-out="object.contact_name"/>', self.record),
            "<p></p>",
            "an allow-listed path the model lacks renders empty; QWeb would raise",
        )

    def test_directive_attributes_do_not_crash_the_static_renderer(self):
        """AUDIT D1 — expected to FAIL: `SyntaxError`, not a `UserError`.

        The restricted QWeb compile accepts `t-tag-open`/`t-tag-close` on a
        `t-out` element; the static renderer accepts `{t-out}` and nothing else,
        so it is handed a template it cannot render and raises a bare
        `SyntaxError` that no caller catches.
        """
        mixin = self.env["mixin.mail.render"]
        src = '<p t-out="object.name" t-tag-open="1"/>'
        try:
            mixin._render_template_qweb(src, self.model, [self.record.id])
        except SyntaxError:
            self.fail(
                "the two safety checks disagree and the disagreement is a SyntaxError"
            )
        except UserError:
            pass  # an acceptable outcome: refused, but as a domain error


@tagged("mail_render", "post_install", "-at_install")
class TestRenderErrorPolicy(common.MailCommon):
    """One error policy, not one per code path.

    `_check_render_error` classifies `AccessError` carefully. It is reachable
    from one of the five render paths.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env["mail.test.track"].create(
            {"name": "Rec", "email_from": "rec@test.example.com"}
        )
        cls.editor = cls.env["res.users"].create(
            {
                "name": "Template Editor",
                "login": "render_audit_editor",
                "email": "editor@test.example.com",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("mail.group_mail_template_editor").id,
                        ],
                    )
                ],
            }
        )
        # an expression that trips a real ORM access check, not a synthetic raise
        cls.denied = "env['ir.config_parameter'].search([], limit=1).key"

    @users("render_audit_editor")
    def test_access_error_survives_the_inline_engine(self):
        """AUDIT D4 — expected to FAIL: reported as `UserError`."""
        mixin = self.env["mixin.mail.render"]
        with self.assertRaises(AccessError):
            mixin._render_template(
                "{{ %s }}" % self.denied,
                self.model,
                [self.record.id],
                engine="inline_template",
            )

    @users("render_audit_editor")
    def test_access_error_survives_the_qweb_engine(self):
        """AUDIT D4 — expected to PASS: this is the path that gets it right."""
        mixin = self.env["mixin.mail.render"]
        with self.assertRaises(AccessError):
            mixin._render_template(
                '<p t-out="%s"/>' % self.denied.replace('"', "'"),
                self.model,
                [self.record.id],
                engine="qweb",
            )

    @users("render_audit_editor")
    def test_access_error_survives_the_qweb_view_engine(self):
        """AUDIT D4 — expected to FAIL: reported as `UserError`."""
        view = (
            self.env["ir.ui.view"]
            .sudo()
            .create(
                {
                    "name": "render_audit_view",
                    "type": "qweb",
                    "arch_db": "<t t-name='x'><p t-out=\"%s\"/></t>"
                    % self.denied.replace('"', "'"),
                }
            )
        )
        with self.assertRaises(AccessError):
            self.env["mixin.mail.render"]._render_template(
                view.id, self.model, [self.record.id], engine="qweb_view"
            )

    def test_missing_error_survives_every_engine(self):
        """AUDIT D4 (second direction) — expected to FAIL for the dynamic paths.

        `mail.template._render_dynamic_fields` re-raises `MissingError` on
        purpose rather than reporting a broken template; the dynamic paths turn
        it into `UserError` first, so that guard cannot fire.
        """
        gone = self.env["mail.test.track"].create(
            {"name": "Gone", "email_from": "gone@test.example.com"}
        )
        gone_id = gone.id
        gone.unlink()
        mixin = self.env["mixin.mail.render"]
        cases = [
            ("inline_template", "{{ object.name }}"),  # static
            ("inline_template", "{{ object.name or 'x' }}"),  # dynamic
            ("qweb", '<p t-out="object.name"/>'),  # static
            ("qweb", '<p t-out="object.name or None"/>'),  # dynamic
        ]
        for engine, src in cases:
            with self.subTest(engine=engine, src=src), self.assertRaises(MissingError):
                mixin._render_template(src, self.model, [gone_id], engine=engine)


@tagged("mail_render", "post_install", "-at_install")
class TestDynamicTemplateWriteScope(common.MailCommon):
    """Writing one placeholder field must not re-validate the others."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_user = cls.env["res.users"].create(
            {
                "name": "Plain",
                "login": "render_audit_plain",
                "email": "plain@test.example.com",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def _template(self):
        return self.env["mail.template"].create(
            {
                "name": "audit tpl",
                "model_id": self.env["ir.model"]._get("mail.test.track").id,
                "email_from": "from@test.example.com",
                # one character off `object.user_id.name`, which IS allow-listed
                "subject": "Hi {{ object.user_id.email }}",
                "body_html": Markup("<p>plain</p>"),
            }
        )

    def test_write_narrows_the_check_to_the_written_fields(self):
        """AUDIT D5 — expected to FAIL: `_check_access_right_dynamic_template(None)`.

        Asserted on the argument rather than on the outcome: the outcome depends
        on the acting user's groups, and a test env that happens to be a
        template editor short-circuits the check entirely, which would make this
        pass while proving nothing.
        """
        template = self._template()
        self.env.flush_all()
        received = []
        model_cls = type(template)
        original = model_cls._check_access_right_dynamic_template

        def spy(self, fnames=None):
            received.append(fnames)
            return original(self, fnames=fnames)

        self.patch(model_cls, "_check_access_right_dynamic_template", spy)
        template.write({"email_to": "to@test.example.com"})
        self.env.flush_all()
        self.assertTrue(
            received, "precondition: the write must reach the placeholder check"
        )
        self.assertEqual(
            received,
            [{"email_to"}],
            "the write re-validated every dynamic field instead of the one written",
        )

    def test_write_scan_is_proportional_to_the_write(self):
        """AUDIT D5, the cost half — expected to FAIL.

        Writing one placeholder field re-parses every other placeholder field on
        the record.
        """
        template = self._template()
        self.env.flush_all()
        scanned = []
        model_cls = type(template)
        original = model_cls._has_unsafe_expression_template_inline_template

        def spy(self, template_txt, model, fname=None):
            scanned.append(template_txt)
            return original(self, template_txt, model, fname=fname)

        self.patch(model_cls, "_has_unsafe_expression_template_inline_template", spy)
        # bypass the group short-circuit so the scan actually runs
        self.patch(
            model_cls,
            "_check_access_right_dynamic_template",
            lambda self, fnames=None: self._has_unsafe_expression(fnames=fnames),
        )
        template.write({"email_to": "to@test.example.com"})
        self.env.flush_all()
        self.assertEqual(
            len(scanned), 1, "one field was written, %d were parsed" % len(scanned)
        )

    def test_changing_the_model_revalidates_the_placeholders(self):
        """AUDIT D7 — expected to FAIL: no rescan at all.

        The model decides which expressions are allowed, so changing it can turn
        a validated placeholder into a forbidden one. `write()`'s guard only
        fires on char/text/html fields, and `model_id` is neither.
        """
        template = self._template()
        self.env.flush_all()
        received = []
        model_cls = type(template)
        original = model_cls._check_access_right_dynamic_template

        def spy(self, fnames=None):
            received.append(fnames)
            return original(self, fnames=fnames)

        # Asserted on the call, not on `_has_unsafe_expression`: the check
        # short-circuits for a template editor, and the test env is one, so
        # spying deeper would pass vacuously.
        self.patch(model_cls, "_check_access_right_dynamic_template", spy)
        template.write({"model_id": self.env["ir.model"]._get("mail.test.simple").id})
        self.env.flush_all()
        self.assertEqual(
            received,
            [None],
            "moving the render model must re-check every placeholder, not none of them",
        )


@tagged("mail_render", "post_install", "-at_install")
class TestLocalLinkReplacement(common.MailCommon):
    """`/[^/][^"]+` is a hand-rolled 'not //', and it is wrong at the edges."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://ex.test"
        )

    def test_root_link_does_not_swallow_the_next_link(self):
        """AUDIT D3 — expected to FAIL.

        For `href="/"` the `[^/]` matches the closing quote and `[^"]+` runs on
        to the next quote in the document, consuming the following `href="`.
        """
        body = '<p><a href="/">Home</a> | <a href="/shop">Shop</a></p>'
        out = str(self.env["mixin.mail.render"]._replace_local_links(body))
        self.assertNotIn(
            'href="/shop"', out, "the link after a root link stayed relative"
        )

    def test_protocol_relative_urls_are_left_alone(self):
        """Expected to PASS — the case the pattern was written for."""
        body = '<a href="//cdn.test/x">x</a>'
        self.assertEqual(
            str(self.env["mixin.mail.render"]._replace_local_links(body)), body
        )

    def test_short_local_paths_are_made_absolute(self):
        """AUDIT D3 (second edge) — expected to FAIL: needs three characters."""
        body = '<a href="/a">a</a>'
        out = str(self.env["mixin.mail.render"]._replace_local_links(body))
        self.assertIn("https://ex.test/a", out)


@tagged("mail_render", "post_install", "-at_install")
class TestEncapsulateContract(common.MailCommon):
    """`_render_encapsulate` and the notify pipeline build the same context."""

    def test_missing_layout_does_not_produce_an_empty_body(self):
        """AUDIT D6 — expected to FAIL: returns `Markup('')`.

        `_notify_by_email_render_layout` falls back to the message body when the
        layout is missing; `_render_encapsulate` returns empty, and its callers
        assign the result straight to `body_html`.
        """
        body = Markup("<p>the actual content</p>")
        out = self.env["mixin.mail.render"]._render_encapsulate(
            "mail.this_layout_does_not_exist", body
        )
        self.assertTrue(out, "a missing layout silently emptied the mail body")


@tagged("mail_render", "post_install", "-at_install")
class TestPlaceholderValueTypes(common.MailCommon):
    """Every engine answers the same thing for a value with no text form.

    The three renderers reach the question by different routes -- the inline
    engine through `renders_as_no_value`, the evaluation-free one through
    `_get_static_value`, the evaluated QWeb one through
    `ir_qweb._mail_normalize_out` -- so the property is asserted on all three
    rather than on whichever happens to run.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "res.partner"
        cls.record = cls.env["res.partner"].create({"name": "P"})
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "red").save(buffer, "PNG")
        cls.record.image_1920 = base64.b64encode(buffer.getvalue())

    def _render(self, src, engine):
        return str(
            self.env["mixin.mail.render"]._render_template(
                src, self.model, [self.record.id], engine=engine
            )[self.record.id]
        )

    def test_binary_never_reaches_the_wire_as_a_bytes_repr(self):
        """A binary placeholder used to emit `b'iVBORw0KGgo...'` -- payload and
        Python repr -- into a subject line."""
        cases = [
            ("inline_template", "{{object.image_1920}}"),
            ("qweb", '<t t-out="object.image_1920"/>'),
            ("qweb", '<t style="x" t-out="object.image_1920"/>'),
        ]
        for engine, src in cases:
            with self.subTest(engine=engine, src=src):
                rendered = self._render(src, engine)
                self.assertNotIn("payload", rendered)
                self.assertNotIn("b'", rendered)

    def test_binary_falls_back_to_the_author_s_default_on_every_engine(self):
        cases = [
            ("inline_template", "{{object.image_1920 ||| (none)}}"),
            ("qweb", '<t t-out="object.image_1920">(none)</t>'),
            ("qweb", '<t style="x" t-out="object.image_1920">(none)</t>'),
        ]
        for engine, src in cases:
            with self.subTest(engine=engine, src=src):
                self.assertEqual(self._render(src, engine), "(none)")

    def test_an_escaped_terminator_survives_a_round_trip(self):
        """`}}` in a default used to truncate the placeholder and spill the
        rest of itself into the rendered text."""
        rendered = self._render(
            r"{{object.parent_id.name ||| see \}\} here}}", "inline_template"
        )
        self.assertEqual(rendered, "see }} here")

    def test_the_separator_is_not_scrubbed_out_of_a_default(self):
        rendered = self._render(
            "{{object.parent_id.name ||| a ||| b}}", "inline_template"
        )
        self.assertEqual(rendered, "a ||| b")


@tagged("mail_render", "post_install", "-at_install")
class TestPresentationalAttributes(common.MailCommon):
    """Formatting a placeholder is not writing code.

    Restricted rendering refused every attribute on a `t-out` element, so
    `<p style="color:red" t-out="object.name"/>` -- what the editor produces the
    moment anyone colours a placeholder -- revoked a non-editor's save and sent
    the template down the evaluating renderer. The rule protected nothing: the
    same user may write `<p style="color:red">` with no `t-out` on it in the
    same field, and the dangerous attributes are removed by the html field's
    sanitizer.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env[cls.model].create(
            {"name": "Rec", "email_from": "rec@test.example.com"}
        )
        cls.plain_user = cls.env["res.users"].create(
            {
                "name": "Plain",
                "login": "render_attrs_plain",
                "email": "plain@test.example.com",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def test_a_styled_placeholder_is_not_code(self):
        mixin = self.env["mixin.mail.render"]
        self.assertFalse(
            mixin._has_unsafe_expression_template_qweb(
                '<p style="color:red" t-out="object.name"/>', self.model
            )
        )

    def test_a_qweb_directive_still_is(self):
        mixin = self.env["mixin.mail.render"]
        for src in (
            '<p t-if="1" t-out="object.name"/>',
            '<p t-att-class="object.name" t-out="object.name"/>',
            '<p t-esc="object.name"/>',
        ):
            with self.subTest(src=src):
                self.assertTrue(
                    mixin._has_unsafe_expression_template_qweb(src, self.model)
                )

    def test_the_evaluation_free_renderer_keeps_the_attribute(self):
        rendered = str(
            self.env["mixin.mail.render"]._render_template_qweb(
                '<p style="color:red" t-out="object.name"/>',
                self.model,
                [self.record.id],
            )[self.record.id]
        )
        self.assertEqual(rendered, '<p style="color:red">Rec</p>')

    @users("render_attrs_plain")
    def test_a_non_editor_may_save_one(self):
        self.env["mail.template"].create(
            {
                "name": "styled",
                "model_id": self.env["ir.model"]._get(self.model).id,
                "body_html": Markup('<p style="color:red" t-out="object.name"/>'),
            }
        )
