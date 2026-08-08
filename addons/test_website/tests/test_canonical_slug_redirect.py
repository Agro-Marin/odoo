# Part of Odoo. See LICENSE file for full copyright and licensing details.
import json

from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestCanonicalSlugRedirect(HttpCase):
    """``ir.http._pre_dispatch`` 301s a frontend URL to its canonical form
    (``/foo/1`` -> ``/foo/egg-1``) by rebuilding the matched rule and comparing
    the result with the URL being served.

    Both sides of that comparison have to be in the same encoding.
    ``rule.build`` percent-quotes; ``request.httprequest.path`` is what werkzeug
    has already decoded. Decoding the current path a *second* time (the old
    ``unquote_plus`` on both sides) turned a literal "%20" inside a converter
    value back into a space, so the comparison could never match and the
    canonical URL was the URL already being served: an infinite 301 loop, cached
    by the browser, on any frontend route carrying a percent-escape-looking
    segment -- a coupon code, a blog tag, a model-page record slug.

    ``/ignore_args/converteronly/<string:a>`` is the plain ``website=True``
    string-converter route this module ships, which is exactly that shape.
    """

    EP = "/ignore_args/converteronly/"

    def _serve(self, encoded_segment):
        return self.url_open(self.EP + encoded_segment, allow_redirects=False)

    def test_percent_escape_lookalike_segments_do_not_loop(self):
        # The value really contains "%20" / "%2B" as characters, hence the
        # double encoding in the request line.
        for encoded, expected in [
            ("a%2520b", "a%20b"),
            ("a%252Bb", "a%2Bb"),
            ("a%2520b%2520c", "a%20b%20c"),
            ("a%253Db", "a%3Db"),
        ]:
            with self.subTest(segment=encoded):
                response = self._serve(encoded)
                self.assertEqual(
                    response.status_code,
                    200,
                    "must be served, not 301'd back at itself",
                )
                self.assertEqual(json.loads(response.content)["a"], expected)

    def test_ordinary_segments_are_still_served(self):
        for encoded, expected in [
            ("plain", "plain"),
            ("a%2Bb", "a+b"),  # "+" is a literal plus in a path, never a space
            ("a%20b", "a b"),
            ("caf%C3%A9", "café"),
        ]:
            with self.subTest(segment=encoded):
                response = self._serve(encoded)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(json.loads(response.content)["a"], expected)

    def test_bare_id_is_still_canonicalised(self):
        # The guard must not cost us the redirect it exists for: a bare-id URL
        # still 301s to the slug.
        country = self.env["res.country"].search([("code", "=", "AD")], limit=1)
        self.assertTrue(country, "res.country AD is a base data record")
        response = self.url_open(
            "/test_lang_url/%s" % country.id, allow_redirects=False
        )
        self.assertEqual(response.status_code, 301)
        self.assertURLEqual(
            response.headers.get("Location"),
            "/test_lang_url/%s" % self.env["ir.http"]._slug(country),
        )
