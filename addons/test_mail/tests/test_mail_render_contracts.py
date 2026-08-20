"""What `mixin.mail.render` promises its callers, asserted rather than assumed.

Each class here pins one contract the 2026-08-18 audit found the module was not
keeping. They are grouped by the promise, not by the method, because the point
of each is what a caller may rely on.
"""

from markupsafe import Markup

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.mail.tests import common


@tagged("mail_render", "post_install", "-at_install")
class TestEncapsulateContext(common.MailCommon):
    """`_render_encapsulate_context` is the notification layouts' contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["mail.test.track"].create(
            {"name": "Rec", "email_from": "rec@test.example.com"}
        )
        cls.body = Markup("<p>the body</p>")
        cls.layouts = ["mail.mail_notification_layout", "mail.mail_notification_light"]

    def test_a_supplied_subtype_does_not_raise(self):
        """It used to read `subtype.is_internal`; the field is `internal`.

        No call site supplies a subtype, which is why an `AttributeError` on
        every layout went unnoticed. The value is not passed from Python at all
        now — both layouts open by computing `subtype_internal` themselves — so
        this asserts the render survives, not what it produced.
        """
        subtype = self.env.ref("mail.mt_note")
        for layout in self.layouts:
            with self.subTest(layout=layout):
                rendered = self.env["mixin.mail.render"]._render_encapsulate(
                    layout,
                    self.body,
                    add_context={"subtype": subtype},
                    context_record=self.record,
                )
                self.assertIn("the body", rendered)

    def test_an_explicit_none_record_name_does_not_desync_the_subtitle(self):
        """`.get` cannot tell absent from None, and the spread then won.

        The caller got `record_name=None` alongside `subtitles=['Rec']`: two
        keys describing one record, disagreeing.
        """
        ctx = self.env["mixin.mail.render"]._render_encapsulate_context(
            self.body, {"record_name": None}, self.record
        )
        self.assertEqual(ctx["record_name"], "Rec")
        self.assertEqual(ctx["subtitles"], ["Rec"])

        absent = self.env["mixin.mail.render"]._render_encapsulate_context(
            self.body, {}, self.record
        )
        self.assertEqual(absent["record_name"], ctx["record_name"])
        self.assertEqual(absent["subtitles"], ctx["subtitles"])

    def test_a_caller_supplied_record_name_still_wins(self):
        ctx = self.env["mixin.mail.render"]._render_encapsulate_context(
            self.body, {"record_name": "Chosen"}, self.record
        )
        self.assertEqual(ctx["record_name"], "Chosen")
        self.assertEqual(ctx["subtitles"], ["Chosen"])

    def test_the_model_description_comes_from_the_hook(self):
        """`sale` overrides `_get_model_description`; reading `ir.model` directly
        gave this path and the notification pipeline different answers for the
        same record."""
        expected = self.record.with_context(lang=self.env.lang)._get_model_description(
            self.record._name
        )
        ctx = self.env["mixin.mail.render"]._render_encapsulate_context(
            self.body, {}, self.record
        )
        self.assertEqual(ctx["model_description"], expected)

    def test_no_context_record_is_not_an_error(self):
        ctx = self.env["mixin.mail.render"]._render_encapsulate_context(
            self.body, {}, None
        )
        self.assertEqual(ctx["record_name"], "")
        self.assertFalse(ctx["model_description"])
        self.assertEqual(ctx["company"], self.env.company)


@tagged("mail_render", "post_install", "-at_install")
class TestRenderLangContract(common.MailCommon):
    """`_render_lang` answers a language for every id it is given."""

    def test_a_template_with_no_model_answers_rather_than_raising(self):
        """`self.env[False]` raised `KeyError: False`.

        `mail.template.model_id` is not required, and every caller subscripts
        the result on the next expression — `account`, `calendar`, `base_order`,
        `hr_recruitment` and `website_slides` all do — so a template saved
        without a model answered a KeyError to "which language?".
        """
        template = self.env["mail.template"].create({"name": "no model"})
        record = self.env["mail.test.track"].create(
            {"name": "R", "email_from": "r@test.example.com"}
        )
        self.assertEqual(template._render_lang([record.id]), {record.id: False})

    def test_every_id_gets_an_answer(self):
        template = self.env["mail.template"].create(
            {
                "name": "with model",
                "model_id": self.env["ir.model"]._get("mail.test.track").id,
            }
        )
        records = self.env["mail.test.track"].create(
            [
                {"name": "A", "email_from": "a@test.example.com"},
                {"name": "B", "email_from": "b@test.example.com"},
            ]
        )
        self.assertEqual(set(template._render_lang(records.ids)), set(records.ids))


@tagged("mail_render", "post_install", "-at_install")
class TestDynamicFieldNames(common.MailCommon):
    """A model says which of its fields are templates; the type does not."""

    def test_a_declaring_model_is_taken_at_its_word(self):
        from odoo.addons.mail.models.mail_template import DYNAMIC_FIELD_NAMES

        self.assertEqual(
            self.env["mail.template"]._get_dynamic_field_names(),
            set(DYNAMIC_FIELD_NAMES),
        )

    def test_a_silent_model_still_gets_the_inferred_set(self):
        """Dropping the inference would ungate every model that has not declared."""
        composer = self.env["mail.compose.message"]
        inferred = {
            fname
            for fname, field in composer._fields.items()
            if field.type in ("char", "text", "html") and field.store
        }
        self.assertEqual(composer._get_dynamic_field_names(), inferred)
        self.assertIn("body", inferred)


@tagged("mail_render", "post_install", "-at_install")
class TestRendererSerialisationAgrees(common.MailCommon):
    """One template, one set of bytes, whichever renderer produced them.

    Which renderer runs turns on whether *some* placeholder in the body needs an
    evaluator, so a body could be serialised two ways for a reason its author
    never wrote. The evaluation-free path used lxml's HTML serialisation and QWeb
    writes XHTML, so they disagreed on every void element, on a valueless
    attribute, and on a boolean one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env[cls.model].create(
            {"name": "Rec", "email_from": "rec@test.example.com"}
        )

    def _both(self, markup):
        """Render `markup` through each renderer, with one allow-listed placeholder.

        The evaluated path is reached by wrapping that placeholder in something
        no allow-list holds, which is what a real body does by accident.
        """
        mixin = self.env["mixin.mail.render"]
        static = mixin._render_template_qweb(
            markup + '<b t-out="object.name"/>', self.model, [self.record.id]
        )[self.record.id]
        evaluated = mixin._render_template_qweb(
            markup + '<b t-out="object.name or None"/>', self.model, [self.record.id]
        )[self.record.id]
        return str(static), str(evaluated)

    def test_the_two_renderers_serialise_the_same_html_the_same_way(self):
        for markup in (
            "<p>a<br/>b</p>",
            "<p>a<br>b</p>",
            '<img src="x"/>',
            '<div/aa t-nothing="1"></div/aa>',
            '<input type="checkbox" checked/>',
            "<p>&nbsp;x</p>",
            "<p></p>",
            "<div><span></span></div>",
            "<hr/>",
        ):
            with self.subTest(markup=markup):
                static, evaluated = self._both(markup)
                self.assertEqual(static, evaluated)

    def test_an_empty_body_is_empty_not_a_collapsed_wrapper(self):
        """The wrapper is stripped by its affixes, and `<div/>` matches neither."""
        rendered = self.env["mixin.mail.render"]._render_template_qweb(
            '<t t-out="object.user_id.name"/>', self.model, [self.record.id]
        )[self.record.id]
        self.assertEqual(str(rendered), "")

    def test_a_void_element_keeps_its_self_closing_form(self):
        static, evaluated = self._both("<p>x<br/>y</p>")
        self.assertIn("<br/>", static)
        self.assertEqual(static, evaluated)

    def test_the_two_renderers_escape_a_value_the_same_way(self):
        """A quote in a name used to come out `"` from one and `&#34;` from the other.

        The evaluation-free path built its output by putting the value into the
        tree and letting lxml serialise it, and lxml leaves quotes alone in text.
        QWeb escapes a value through markupsafe. Compiling the template to
        literal segments made the escaping this renderer's own decision, so it
        can make QWeb's.
        """
        mixin = self.env["mixin.mail.render"]
        for name in ('say "hi"', "it's", "a & b", "<b>x</b>", "ünï", "plain"):
            with self.subTest(name=name):
                record = self.env[self.model].create(
                    {"name": name, "email_from": "v@test.example.com"}
                )
                static = mixin._render_template_qweb(
                    '<p t-out="object.name"/>', self.model, [record.id]
                )[record.id]
                evaluated = mixin._render_template_qweb(
                    '<p t-out="object.name or None"/>', self.model, [record.id]
                )[record.id]
                self.assertEqual(str(static), str(evaluated))

    def test_a_markup_value_is_inserted_as_markup(self):
        """An html field's value is markup, and both paths must keep it so."""
        mixin = self.env["mixin.mail.render"]
        self.env.user.signature = Markup("<b>Sig &amp; co</b>")
        record = self.env[self.model].create(
            {"name": "M", "email_from": "m@test.example.com", "user_id": self.env.uid}
        )
        static = str(
            mixin._render_template_qweb(
                '<p t-out="object.user_id.signature"/>', self.model, [record.id]
            )[record.id]
        )
        self.assertIn("<b>Sig &amp; co</b>", static)

    def test_a_template_with_no_placeholder_is_still_rendered(self):
        rendered = self.env["mixin.mail.render"]._render_template_qweb(
            "<p>nothing dynamic</p>", self.model, [self.record.id]
        )[self.record.id]
        self.assertEqual(str(rendered), "<p>nothing dynamic</p>")


@tagged("mail_render", "post_install", "-at_install")
class TestStaticMarkerIntegrity(common.MailCommon):
    """The renderer's own scratch marks are not something a body may contain.

    The evaluation-free renderer replaces each `t-out` element's text with
    `U+E000<index>U+E001`, serialises the tree, and splits the string back on
    that pattern. U+E000 is the first Private Use codepoint -- where icon fonts
    put their first glyph -- so it reaches a mail body by ordinary copy-paste,
    and the split then read the body's own text as a placeholder slot.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env[cls.model].create(
            {"name": "Rec", "email_from": "marker@test.example.com"}
        )

    #: what the renderer writes into a `t-out` element before serialising
    MARKER = "\ue000{}\ue001"

    def _render(self, src):
        return str(
            self.env["mixin.mail.render"]._render_template_qweb(
                src, self.model, [self.record.id]
            )[self.record.id]
        )

    def test_a_marker_in_the_body_does_not_become_a_placeholder(self):
        """It rendered `<p>Rec</p>`: the author's literal text, overwritten."""
        marker = self.MARKER.format(0)
        rendered = self._render(f'<p>{marker}</p><b t-out="object.name">d</b>')
        self.assertIn(marker, rendered)
        self.assertEqual(rendered.count("Rec"), 1)

    def test_a_marker_naming_a_slot_that_does_not_exist_is_not_a_crash(self):
        """`holes[5]` raised IndexError straight out of `_render_template`,
        past `_check_render_error` and every caller's error handling."""
        rendered = self._render(
            f'<p>{self.MARKER.format(5)}</p><b t-out="object.name">d</b>'
        )
        self.assertIn("Rec", rendered)


@tagged("mail_render", "post_install", "-at_install")
class TestEmptyRelationRendersTheDefault(common.MailCommon):
    """`<p t-out="object.user_id">nobody</p>` says the same thing everywhere.

    An unset many2one has no display name, so it has no text form, and the
    element body is the author's answer for that. `_compile_out_emit` writes the
    default body only for None and False, and an empty recordset is neither, so
    the evaluated QWeb path emitted the empty string instead -- while the inline
    and evaluation-free engines both answered the default. Which of the three
    runs is decided by whether some *other* placeholder in the same body needs an
    evaluator, so an edit in an unrelated paragraph changed this one's output.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env[cls.model].create(
            {"name": "NoUser", "email_from": "nouser@test.example.com"}
        )
        # forces the evaluated path without touching the expression under test
        cls.force_evaluation = '<i t-out="1 + 1"/>'

    def test_every_engine_answers_the_default(self):
        mixin = self.env["mixin.mail.render"]
        cases = [
            ("inline_template", "{{ object.user_id ||| nobody}}", "nobody"),
            ("qweb", '<p t-out="object.user_id">nobody</p>', "<p>nobody</p>"),
            (
                "qweb",
                '<p t-out="object.user_id">nobody</p>' + self.force_evaluation,
                "<p>nobody</p><i>2</i>",
            ),
        ]
        for engine, src, expected in cases:
            with self.subTest(engine=engine, src=src):
                self.assertEqual(
                    str(
                        mixin._render_template(
                            src, self.model, [self.record.id], engine=engine
                        )[self.record.id]
                    ),
                    expected,
                )

    def test_a_filled_relation_still_renders_its_display_name(self):
        record = self.env[self.model].create(
            {
                "name": "WithUser",
                "email_from": "withuser@test.example.com",
                "user_id": self.env.uid,
            }
        )
        mixin = self.env["mixin.mail.render"]
        for src in (
            '<p t-out="object.user_id">nobody</p>',
            '<p t-out="object.user_id">nobody</p>' + self.force_evaluation,
        ):
            with self.subTest(src=src):
                rendered = str(
                    mixin._render_template_qweb(src, self.model, [record.id])[record.id]
                )
                self.assertIn(self.env.user.display_name, rendered)
                self.assertNotIn("nobody", rendered)


@tagged("mail_render", "post_install", "-at_install")
class TestStaticExpressionRoots(common.MailCommon):
    """`mail_allowed_qweb_expressions` is a hook; widening it is not a crash.

    The allow-list is a list of strings and says nothing about which *root* the
    evaluation-free renderer can resolve -- it knows `object` and `user`. An
    allow-listed expression rooted anywhere else passed the compile check and
    then raised a bare `SyntaxError` out of `_get_static_value`, which no caller
    catches. The root is now part of what the renderer checks before accepting a
    template, so an unknown one falls back to QWeb, which can resolve it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env[cls.model].create(
            {"name": "Roots", "email_from": "roots@test.example.com"}
        )

    def test_an_unreachable_root_does_not_raise_and_does_not_diverge(self):
        """The contract is that neither renderer raises, and that they agree.

        Not *what* the placeholder resolves to: an expression rooted somewhere
        this renderer cannot reach has no value here by definition, and the
        evaluated path resolves an allow-listed expression the same tolerant
        way (`_mail_resolve_allowed`) precisely so the two cannot differ.
        """
        model_cls = type(self.env[self.model])
        original = model_cls.mail_allowed_qweb_expressions
        self.patch(
            model_cls,
            "mail_allowed_qweb_expressions",
            # `env` is in `_render_eval_context` and in no static root table
            lambda self: (*original(self), "env.uid"),
        )
        mixin = self.env["mixin.mail.render"]
        evaluation_free = str(
            mixin._render_template_qweb(
                '<p t-out="env.uid"/>', self.model, [self.record.id]
            )[self.record.id]
        )
        evaluated = str(
            mixin._render_template_qweb(
                '<p t-out="env.uid"/><i t-out="1 + 1"/>', self.model, [self.record.id]
            )[self.record.id]
        )
        self.assertEqual(evaluation_free, "<p></p>")
        self.assertEqual(evaluated, "<p></p><i>2</i>")


@tagged("mail_render", "post_install", "-at_install")
class TestRenderOptionsStayInMail(common.MailCommon):
    """`_render_template`'s options are this module's vocabulary, not QWeb's.

    Every option was forwarded to `_render_batch` as a keyword, and
    `_render_prepare` turns its keywords into context keys -- so `post_process`,
    a step this module runs *after* QWeb returns, travelled through the whole
    render and every ORM call it made.
    """

    def test_a_mail_only_option_does_not_reach_the_qweb_context(self):
        record = self.env["mail.test.track"].create(
            {"name": "Opt", "email_from": "opt@test.example.com"}
        )
        seen = []
        qweb_cls = type(self.env["ir.qweb"])
        original = qweb_cls._render_prepare
        self.patch(
            qweb_cls,
            "_render_prepare",
            lambda self, values, options: (
                seen.append(dict(options)) or original(self, values, options)
            ),
        )
        self.env["mixin.mail.render"]._render_template(
            '<p t-out="1 + 1"/>',
            "mail.test.track",
            [record.id],
            engine="qweb",
            options={"post_process": True, "preserve_comments": True},
        )
        self.assertTrue(seen, "precondition: the render must reach QWeb")
        for options in seen:
            self.assertNotIn("post_process", options)
            self.assertIn("preserve_comments", options)


@tagged("mail_render", "post_install", "-at_install")
class TestStaticProgramIsCompiledOnce(common.MailCommon):
    """Which renderer a template needs is a property of the template.

    Deciding it meant running QWeb's whole code generator over the body to see
    whether it raised, then deep-copying, re-walking and re-serialising the tree
    -- on every render. On a 92 KB body that was 8.9 ms of a 13.2 ms single-record
    render.
    """

    def test_the_decision_survives_across_renders(self):
        model = "mail.test.track"
        record = self.env[model].create(
            {"name": "Once", "email_from": "once@test.example.com"}
        )
        # unique per run: the decision is cached on (model, source, options)
        src = '<p t-out="object.name"/><span>%s</span>' % record.id
        calls = []
        mixin_cls = type(self.env["mixin.mail.render"])
        original = mixin_cls._has_unsafe_expression_template_qweb
        self.patch(
            mixin_cls,
            "_has_unsafe_expression_template_qweb",
            lambda self, template_src, model, fname=None: (
                calls.append(template_src)
                or original(self, template_src, model, fname=fname)
            ),
        )
        for _index in range(5):
            self.env["mixin.mail.render"]._render_template_qweb(src, model, [record.id])
        self.assertEqual(len(calls), 1, "the safety probe ran once per render")


@tagged("mail_render", "post_install", "-at_install")
class TestTheTwoRenderersAgreeOnAllowListedPlaceholders(common.MailCommon):
    """The allow-list is exactly the set both `t-out` renderers must agree on.

    `mail` picks its renderer per *template*: one expression no allow-list holds,
    anywhere in a body, sends every other placeholder in that body down
    `ir.qweb` instead of the evaluation-free renderer. Every way the two
    disagreed was therefore action at a distance — an edit in one paragraph
    changing what another paragraph rendered. `object.contact_name` on a model
    without that field is the sharp case: it rendered the author's default on one
    path and raised `UserError` on the other, and the stock allow-list is written
    for a `crm.lead`-shaped model, so most models have most of it missing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.filled = cls.env[cls.model].create(
            {
                "name": "Filled",
                "email_from": "filled@test.example.com",
                "user_id": cls.env.uid,
            }
        )
        cls.empty = cls.env[cls.model].create(
            {"name": "Empty", "email_from": "empty@test.example.com"}
        )
        # a placeholder no allow-list holds, so the whole body needs an evaluator
        cls.force_evaluation = '<i t-out="1 + 1"/>'

    def _both(self, source, record):
        """Render one body through each renderer and hand back both."""
        mixin = self.env["mixin.mail.render"]

        def go(src):
            rendered = str(
                mixin._render_template_qweb(src, self.model, [record.id])[record.id]
            )
            return rendered.removesuffix("<i>2</i>")

        self.assertFalse(
            mixin._has_unsafe_expression_template_qweb(source, self.model),
            "precondition: the bare body must take the evaluation-free path",
        )
        self.assertTrue(
            mixin._has_unsafe_expression_template_qweb(
                source + self.force_evaluation, self.model
            ),
            "precondition: the forced body must take the QWeb path",
        )
        return go(source), go(source + self.force_evaluation)

    def test_every_allow_listed_placeholder_reads_the_same_on_both(self):
        cases = [
            ('<p t-out="object.name"/>', "filled", "a field the model has"),
            ('<p t-out="object.contact_name"/>', "filled", "a field it does not"),
            ('<p t-out="object.contact_name">cn</p>', "filled", "…with a default"),
            ('<p t-out="object.partner_id">no partner</p>', "filled", "a m2o it lacks"),
            ('<p t-out="object.user_id"/>', "empty", "an unset m2o"),
            ('<p t-out="object.user_id">nobody</p>', "empty", "…with a default"),
            ('<p t-out="object.user_id"/>', "filled", "a set m2o"),
            ('<p t-out="object.user_id.name"/>', "filled", "a path through a m2o"),
            (
                '<p t-out="object.user_id.name">nn</p>',
                "empty",
                "…unset, with a default",
            ),
            ('<p t-out="object.user_id.signature"/>', "filled", "an html value"),
        ]
        for source, which, label in cases:
            with self.subTest(case=label, source=source):
                evaluation_free, evaluated = self._both(source, getattr(self, which))
                self.assertEqual(evaluation_free, evaluated)

    def test_an_allow_listed_field_the_model_lacks_is_not_an_error(self):
        """It raised `UserError` on the evaluated path — so a body that renders
        today started failing the moment anyone added a placeholder elsewhere."""
        evaluation_free, evaluated = self._both(
            '<p t-out="object.contact_name">cn</p>', self.filled
        )
        self.assertEqual(evaluation_free, "<p>cn</p>")
        self.assertEqual(evaluated, "<p>cn</p>")

    def test_a_valueless_placeholder_keeps_its_element_on_both(self):
        """QWeb drops the element entirely; this renderer keeps the blank line,
        and `mail`'s own TestRegexRendering pins keeping it."""
        evaluation_free, evaluated = self._both(
            '<p t-out="object.user_id"/>', self.empty
        )
        self.assertEqual(evaluation_free, "<p></p>")
        self.assertEqual(evaluated, "<p></p>")

    def test_a_non_allow_listed_expression_still_reaches_the_evaluator(self):
        """The tolerant lookup is scoped to the allow-list: everything else must
        still compile to real Python, or `mail.template` loses its expressions."""
        rendered = self.env["mixin.mail.render"]._render_template_qweb(
            '<p t-out="object.name.upper()"/>', self.model, [self.filled.id]
        )[self.filled.id]
        self.assertEqual(str(rendered), "<p>FILLED</p>")


@tagged("mail_render", "post_install", "-at_install")
class TestRenderModelIsChecked(common.MailCommon):
    """A render model that is not a model is a domain error, not a `KeyError`."""

    def test_a_template_without_a_model_says_so(self):
        """`self.env[False]` answered `KeyError: False`, naming neither the
        template nor the field. `model_id` is not required, and `_render_lang`
        was already fixed for exactly this input."""
        template = self.env["mail.template"].create(
            {"name": "no model", "subject": "Hi {{ object.name }}"}
        )
        record = self.env["mail.test.track"].create(
            {"name": "R", "email_from": "r@test.example.com"}
        )
        self.assertFalse(template.render_model)
        with self.assertRaises(UserError):
            template._render_field("subject", [record.id])

    def test_an_unknown_model_says_so_too(self):
        with self.assertRaises(UserError):
            self.env["mixin.mail.render"]._render_template(
                "x", "no.such.model", [1], engine="inline_template"
            )


@tagged("mail_render", "post_install", "-at_install")
class TestUnsafeExpressionScanScope(common.MailCommon):
    """What the placeholder scan reads, and what it has no business reading."""

    def test_a_qweb_view_field_is_not_scanned_as_a_template_body(self):
        """A `qweb_view` field holds a view *reference*, and a view's arch is
        admin content this scan has no business judging. Falling through to the
        qweb check reached "safe" by accident instead: it parsed the reference as
        HTML, and `42` is a text node with no directives in it.
        """
        template = self.env["mail.template"].create(
            {
                "name": "view engine",
                "model_id": self.env["ir.model"]._get("mail.test.track").id,
                "subject": "Hi {{ object.name }}",
                "body_html": Markup('<p t-out="object.name"/>'),
            }
        )
        scanned = []
        mixin_cls = type(template)
        for name in (
            "_has_unsafe_expression_template_qweb",
            "_has_unsafe_expression_template_inline_template",
        ):
            original = getattr(mixin_cls, name)
            self.patch(
                mixin_cls,
                name,
                (
                    lambda self, source, model, fname=None, _o=original: (
                        scanned.append(fname) or _o(self, source, model, fname=fname)
                    )
                ),
            )
        # `body_html` is the field that declares an engine at all; point it at
        # the one whose value is a reference rather than a body
        self.assertEqual(template._fields["body_html"].render_engine, "qweb")
        self.patch(template._fields["body_html"], "render_engine", "qweb_view")
        template._has_unsafe_expression()
        self.assertIn("subject", scanned, "precondition: the scan ran at all")
        self.assertNotIn(
            "body_html", scanned, "a view reference was scanned as placeholder text"
        )

    def test_the_scan_reports_fields_in_a_stable_order(self):
        """Which field is blamed for a rejected template should not depend on
        set iteration order."""
        template = self.env["mail.template"].create(
            {
                "name": "order",
                "model_id": self.env["ir.model"]._get("mail.test.track").id,
                "subject": "Hi {{ object.name }}",
                "email_to": "{{ object.email_from }}",
            }
        )
        seen = []
        mixin_cls = type(template)
        original = mixin_cls._has_unsafe_expression_template_inline_template
        self.patch(
            mixin_cls,
            "_has_unsafe_expression_template_inline_template",
            lambda self, source, model, fname=None: (
                seen.append(fname) or original(self, source, model, fname=fname)
            ),
        )
        template._has_unsafe_expression()
        self.assertEqual(seen, sorted(seen))
