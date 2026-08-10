import unittest

from markupsafe import Markup

from odoo.libs.text.html import (
    create_link,
    html2plaintext,
    html_keep_url,
    html_normalize,
    html_sanitize,
    plaintext2html,
)


def sanitize(src: str) -> str:
    out = html_sanitize(src)
    assert out is not None, f"html_sanitize returned None for {src!r}"
    return out


class TestHtmlNormalizeEncodingStrip(unittest.TestCase):
    def test_strips_only_the_encoding_attribute(self):
        out = html_normalize('<p><span encoding="x" style="color:red">imp</span> t</p>')
        self.assertIn("imp", out)
        self.assertIn("t", out)
        self.assertIn("color:red", out)
        self.assertNotIn("encoding", out)

    def test_plain_content_unchanged(self):
        out = html_normalize("<p>hi <b>bold</b> there</p>")
        self.assertIn("bold", out)
        self.assertNotIn("encoding", out)


class TestSanitizeSvgLink(unittest.TestCase):
    def test_javascript_scheme_is_stripped(self):
        out = sanitize(
            '<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>'
        )
        self.assertNotIn("javascript:", out)

    def test_data_scheme_is_stripped(self):
        out = sanitize(
            '<svg><a xlink:href="data:text/html;base64,PHNjcmlwdD4="><text>x</text></a></svg>'
        )
        self.assertNotIn("base64", out)

    def test_http_url_survives(self):
        out = sanitize(
            '<svg><a xlink:href="https://ok.example"><text>x</text></a></svg>'
        )
        self.assertIn("https://ok.example", out)


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
        out = html2plaintext(self.DOC, body_id='content"] | //*[@id="other')
        self.assertNotIn("NO", out)
        self.assertNotIn("HELLO", out)

    def test_body_id_miss_returns_empty(self):
        out = html2plaintext(self.DOC, body_id="does-not-exist")
        self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()


class TestSanitizeRemovesActiveContent(unittest.TestCase):
    def test_script_element_is_removed(self):
        out = sanitize("<p>keep</p><script>alert(1)</script>")
        self.assertNotIn("script", out)
        self.assertIn("keep", out)

    def test_event_handler_attribute_is_removed(self):
        out = sanitize('<p onclick="alert(1)">keep</p>')
        self.assertNotIn("onclick", out)
        self.assertIn("keep", out)

    def test_javascript_url_in_href_is_stripped(self):
        out = sanitize('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn("javascript:", out)

    def test_ordinary_markup_survives(self):
        out = sanitize("<p><b>bold</b> and <i>italic</i></p>")
        self.assertIn("<b>bold</b>", out)
        self.assertIn("<i>italic</i>", out)
