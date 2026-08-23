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


class TestHtml2PlaintextKeepsStructure(unittest.TestCase):
    """Runs of breaks are halved, not collapsed -- and that is deliberate.

    This was very nearly "fixed" to collapse runs to one, on the grounds that
    `html_to_inner_content` twelve lines away already used a regex for it.  The
    two are not doing the same job: `html_to_inner_content` emits a single line
    and has no structure to lose, while this function emits structured plain
    text where a run of breaks is a paragraph gap.  Collapsing removed the
    blank lines that a `<br/>` or a table boundary produces.
    """

    def test_a_break_between_blocks_still_makes_a_blank_line(self):
        self.assertEqual(
            html2plaintext("<h2>A</h2>\n<br/>\n<h3>B</h3>"), "**A**\n\n*B*"
        )

    def test_adjacent_blocks_stay_one_line_apart(self):
        self.assertEqual(html2plaintext("<p>one</p><p>two</p>"), "one\ntwo")

    def test_html_to_inner_content_collapses_because_it_has_no_structure(self):
        self.assertEqual(html_to_inner_content("<p>a    b</p>"), "a b")
        self.assertEqual(html_to_inner_content("<p>a</p><br><br><p>b</p>"), "a b")


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
