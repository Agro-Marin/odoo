from lxml.builder import E

from odoo.tests.common import BaseCase

from odoo.addons.html_editor.models.ir_qweb_fields import html_to_text


class TestHTMLToText(BaseCase):
    def test_rawstring(self):
        self.assertEqual(
            "foobar",
            html_to_text(E.div("foobar")))

    def test_br(self):
        self.assertEqual(
            "foo\nbar",
            html_to_text(E.div("foo", E.br(), "bar")))

        self.assertEqual(
            "foo\n\nbar\nbaz",
            html_to_text(E.div(
                "foo", E.br(), E.br(),
                "bar", E.br(),
                "baz")))

    def test_p(self):
        self.assertEqual(
            "foo\n\nbar\n\nbaz",
            html_to_text(E.div(
                "foo",
                E.p("bar"),
                "baz")))

        self.assertEqual(
            "foo",
            html_to_text(E.div(E.p("foo"))))

        self.assertEqual(
            "foo\n\nbar",
            html_to_text(E.div("foo", E.p("bar"))))
        self.assertEqual(
            "foo\n\nbar",
            html_to_text(E.div(E.p("foo"), "bar")))

        self.assertEqual(
            "foo\n\nbar\n\nbaz",
            html_to_text(E.div(
                E.p("foo"),
                E.p("bar"),
                E.p("baz"),
            )))

    def test_div(self):
        self.assertEqual(
            "foo\nbar\nbaz",
            html_to_text(E.div(
                "foo",
                E.div("bar"),
                "baz"
            )))

        self.assertEqual(
            "foo",
            html_to_text(E.div(E.div("foo"))))

        self.assertEqual(
            "foo\nbar",
            html_to_text(E.div("foo", E.div("bar"))))
        self.assertEqual(
            "foo\nbar",
            html_to_text(E.div(E.div("foo"), "bar")))

        self.assertEqual(
            "foo\nbar\nbaz",
            html_to_text(E.div(
                "foo",
                E.div("bar"),
                E.div("baz")
            )))

    def test_other_block(self):
        self.assertEqual(
            "foo\nbar\nbaz",
            html_to_text(E.div(
                "foo",
                E.section("bar"),
                "baz"
            )))

    def test_inline(self):
        self.assertEqual(
            "foobarbaz",
            html_to_text(E.div("foo", E.span("bar"), "baz")))

    def test_whitespace(self):
        self.assertEqual(
            "foo bar\nbaz",
            html_to_text(E.div(
                "foo\nbar",
                E.br(),
                "baz")
            ))

        self.assertEqual(
            "foo bar\nbaz",
            html_to_text(E.div(
                E.div(E.span("foo"), " bar"),
                "baz")))
