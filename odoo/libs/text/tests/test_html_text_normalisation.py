import unittest

from markupsafe import Markup

from odoo.libs.text.html import (
    append_content_to_html,
    html2plaintext,
    html_to_inner_content,
    prepend_html_content,
)


class TestHtml2PlaintextEntities(unittest.TestCase):
    """Text that reads `&nbsp;` must come out reading `&nbsp;`.

    lxml decodes every entity when it parses and re-escapes only `&`, `<` and
    `>` when it serialises, so a real non-breaking space is a literal U+00A0
    by the time the replacements run.  The only way the five characters
    `&nbsp;` can exist there is the `&amp;` -> `&` replacement manufacturing
    them one line earlier -- which is what used to eat them.
    """

    def test_literal_entity_text_survives(self):
        self.assertEqual(
            html2plaintext("<p>use &amp;nbsp; for a space</p>"),
            "use &nbsp; for a space",
        )

    def test_literal_entity_alone_is_not_swallowed(self):
        # This one used to return "" -- turned into U+00A0, which str.strip()
        # counts as whitespace and removed outright.
        self.assertEqual(html2plaintext("<p>&amp;nbsp;</p>"), "&nbsp;")

    def test_a_real_non_breaking_space_is_still_a_non_breaking_space(self):
        self.assertEqual(html2plaintext("<p>a&nbsp;b</p>"), "a\N{NO-BREAK SPACE}b")

    def test_the_three_reachable_entities_still_decode(self):
        self.assertEqual(html2plaintext("<p>&amp;lt; &lt; &gt;</p>"), "&lt; < >")


class TestHtml2PlaintextWhitespace(unittest.TestCase):
    """Runs collapse to one, not to half.

    `str.replace(" " * 2, " ")` is a single pass, so four spaces became two.
    `html_to_inner_content` twelve lines away already did this correctly.
    """

    def test_long_space_runs_collapse_to_one(self):
        self.assertEqual(html2plaintext("<p>a    b</p>"), "a b")

    def test_matches_html_to_inner_content(self):
        for source in ("<p>a  b</p>", "<p>a    b</p>", "<p>a       b</p>"):
            self.assertEqual(
                html2plaintext(source), html_to_inner_content(source), source
            )

    def test_long_newline_runs_collapse_to_one(self):
        self.assertEqual(html2plaintext("<p>a</p><br><br><br><br><p>b</p>"), "a\nb")

    def test_paragraphs_are_still_one_newline_apart(self):
        self.assertEqual(html2plaintext("<p>one</p><p>two</p>"), "one\ntwo")


class TestAppendContentToHtml(unittest.TestCase):
    """Finding the closing tag must not rewrite the document."""

    def test_caller_markup_is_left_alone(self):
        result = append_content_to_html(
            '<HTML><BODY><A HREF="/x">Hi</A></BODY></HTML>', "x"
        )
        self.assertIn('<A HREF="/x">Hi</A>', result)
        self.assertIn("</BODY>", result)

    def test_closing_tag_with_whitespace_is_found(self):
        # The lowercase-then-literal-find this replaced missed `</body >` and
        # silently appended at the end of the document instead.
        result = append_content_to_html("<html><body>x</body >", "content")
        self.assertTrue(result.endswith("</body >"), result)

    def test_falls_back_to_html_then_to_the_end(self):
        self.assertTrue(
            append_content_to_html("<html>x</html>", "c").endswith("</html>")
        )
        self.assertEqual(
            append_content_to_html("<div>x</div>", "c"), "<div>x</div>\n<p>c</p>\n"
        )

    def test_uppercase_and_lowercase_insert_at_the_same_place(self):
        lower = append_content_to_html("<html><body>x</body></html>", "c")
        upper = append_content_to_html("<HTML><BODY>x</BODY></HTML>", "c")
        self.assertEqual(lower.lower(), upper.lower())


class TestPrependHtmlContent(unittest.TestCase):
    def test_returns_str_and_does_not_over_mark_an_untrusted_body(self):
        # The body is not always trusted; wrapping the join in Markup would
        # declare its unescaped text safe.
        result = prepend_html_content("<body>5 < 6</body>", Markup("<p>c</p>"))
        self.assertIsInstance(result, str)
        self.assertNotIsInstance(result, Markup)
        self.assertEqual(result, "<body><p>c</p>5 < 6</body>")

    def test_content_is_inserted_after_the_body_tag(self):
        self.assertEqual(
            prepend_html_content("<body><p>b</p></body>", "<p>c</p>"),
            "<body><p>c</p><p>b</p></body>",
        )


if __name__ == "__main__":
    unittest.main()
