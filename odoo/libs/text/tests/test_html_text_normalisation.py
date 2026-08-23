import unittest

from lxml import etree
from lxml import html as lxml_html
from markupsafe import Markup

from odoo.libs.text.html import (
    append_content_to_html,
    fromstring,
    html2plaintext,
    html_normalize,
    html_sanitize,
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


class TestHtmlNormalizeRoundTrip(unittest.TestCase):
    """`html_normalize` reparses its own output, and both halves of that matter.

    The round trip reads as dead weight -- parse, serialise, parse again, for
    28% of a small normalise -- and it is not.  Measured over the 51508 HTML
    fragments in this repo, removing it makes `html_sanitize` raise on 1014 of
    them.  If you are here to delete it, this is the case you have to answer.
    """

    def test_fromstring_can_return_a_tree_the_cleaner_cannot_handle(self):
        # The reason: lxml's Cleaner calls doc.rewrite_links(), which lives on
        # HtmlElement, and `fromstring` builds a bare _Element for some inputs.
        self.assertFalse(hasattr(etree.Element("p"), "rewrite_links"))
        self.assertTrue(hasattr(lxml_html.fromstring("<p>x</p>"), "rewrite_links"))

    def test_sanitize_survives_an_input_that_produces_a_bare_element(self):
        # `Many2one<string>` is one of the 1014: `<string>` is an unknown tag,
        # and the tree `fromstring` returns for it has no rewrite_links.
        self.assertEqual(str(html_sanitize("Many2one<string>")), "<p>Many2one</p>")

    def test_the_probe_above_is_not_vacuous(self):
        doc, _ = fromstring("Many2one<string>")
        self.assertNotIsInstance(
            doc,
            lxml_html.HtmlElement,
            "fromstring no longer returns a bare _Element here, so this suite "
            "no longer covers why the round trip exists -- find a new input.",
        )

    def test_non_ascii_inside_a_comment_survives(self):
        # Without encoding="unicode" the round trip emits ASCII bytes with
        # charrefs, and the HTML parser does not entity-decode comment content
        # on the way back, so the escaping was permanent.
        self.assertEqual(
            html_normalize("<p>Bonjour</p><!-- Résumé du café --><p>Adiós</p>"),
            "<p>Bonjour</p><!-- Résumé du café --><p>Adiós</p>",
        )

    def test_non_ascii_inside_a_comment_survives_sanitization(self):
        self.assertEqual(
            str(html_sanitize("<p>Hi</p><!-- Résumé -->")), "<p>Hi</p><!-- Résumé -->"
        )

    def test_non_ascii_in_text_was_never_the_problem(self):
        self.assertEqual(html_normalize("<p>Adiós</p>"), "<p>Adiós</p>")
