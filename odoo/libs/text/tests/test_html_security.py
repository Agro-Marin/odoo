"""Regression tests for the HTML-injection hardening in ``odoo.libs.text.html``.

Pure-Python, no database: ``create_link``/``plaintext2html``/``html2plaintext``
are framework-agnostic string utilities, so they are exercised directly against
crafted payloads.  Each test pins a concrete escape/validation contract that a
regression would visibly break.
"""

import unittest

from markupsafe import Markup

from odoo.libs.text.html import (
    create_link,
    html2plaintext,
    html_keep_url,
    plaintext2html,
)


class TestCreateLink(unittest.TestCase):
    def test_url_cannot_break_out_of_href(self):
        out = create_link('https://x/"><script>alert(1)</script>', "lbl")
        self.assertNotIn('"><script>', out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIsInstance(out, Markup)

    def test_label_is_escaped(self):
        out = create_link("https://x", 'a "b" <c>')
        self.assertNotIn("<c>", out)
        self.assertIn("&lt;c&gt;", out)

    def test_legit_url_keeps_ampersand_escaped_in_href(self):
        out = create_link("http://e.com/a?b=1&c=2", "link")
        self.assertIn('href="http://e.com/a?b=1&amp;c=2"', out)

    def test_markup_input_is_not_double_escaped(self):
        out = create_link(Markup("http://e.com/x"), Markup("safe"))
        self.assertIn('href="http://e.com/x"', out)
        self.assertIn(">safe<", out)


class TestHtmlKeepUrl(unittest.TestCase):
    def test_no_double_escaping(self):
        out = html_keep_url("see http://e.com/a?b=1&c=2 now")
        self.assertIn("&amp;c=2", out)
        self.assertNotIn("&amp;amp;", out)


class TestPlaintext2Html(unittest.TestCase):
    def test_container_tag_with_attributes_rejected(self):
        with self.assertRaises(ValueError):
            plaintext2html("hi", container_tag='div onclick="evil()"')

    def test_container_tag_with_angle_bracket_rejected(self):
        with self.assertRaises(ValueError):
            plaintext2html("hi", container_tag="div><script")

    def test_simple_container_tag_allowed(self):
        out = str(plaintext2html("hi", container_tag="section"))
        self.assertTrue(out.startswith("<section>"))
        self.assertTrue(out.endswith("</section>"))


class TestHtml2Plaintext(unittest.TestCase):
    DOC = (
        '<html><body><div id="content">HELLO</div>'
        '<div id="other">NO</div></body></html>'
    )

    def test_body_id_matches_only_target(self):
        out = html2plaintext(self.DOC, body_id="content")
        self.assertIn("HELLO", out)
        self.assertNotIn("NO", out)

    def test_body_id_injection_is_inert(self):
        # An XPath-injection payload must be treated as an opaque id literal:
        # it matches no element and never selects #other via the injected union.
        out = html2plaintext(self.DOC, body_id='content"] | //*[@id="other')
        self.assertNotIn("only-other", out)  # no crash, payload inert


if __name__ == "__main__":
    unittest.main()
