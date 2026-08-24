from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from lxml import etree

from odoo.tests import common


class MockLinkTracker(common.BaseCase):

    def setUp(self):
        super().setUp()

        def _get_title_from_url(url):
            return "Test_TITLE"

        link_tracker_title_patch = patch('odoo.addons.link_tracker.models.link_tracker.LinkTracker._get_title_from_url', wraps=_get_title_from_url)
        self.startPatcher(link_tracker_title_patch)

    def _get_href_from_anchor_id(self, body, anchor_id):
        """ Parse an html body to find the href of an element given its ID. """
        html = etree.fromstring(body, parser=etree.HTMLParser())
        return html.xpath("//*[@id='%s']" % anchor_id)[0].attrib.get('href')

    def _get_code_from_short_url(self, short_url):
        return self.env['link.tracker.code'].sudo().search([
            ('code', '=', short_url.split('/r/')[-1])
        ])

    def _get_tracker_from_short_url(self, short_url):
        return self._get_code_from_short_url(short_url).link_id

    def assertLinkShortenedHtml(self, body, link_info, link_params=None):
        """ Assert the anchor of ``link_info`` in an HTML content is shortened
        (or not), and that its tracker carries ``link_params``.

        :param tuple link_info: (anchor id, expected target url, is shortened)
        """
        (anchor_id, url, is_shortened) = link_info
        anchor_href = self._get_href_from_anchor_id(body, anchor_id)
        if is_shortened:
            self.assertTrue('/r/' in anchor_href, '%s should be shortened: %s' % (anchor_id, anchor_href))
            link_tracker = self._get_tracker_from_short_url(anchor_href)
            self.assertEqual(url, link_tracker.url)
            self.assertLinkParams(url, link_tracker, link_params=link_params)
        else:
            self.assertTrue('/r/' not in anchor_href, '%s should not be shortened: %s' % (anchor_id, anchor_href))
            self.assertEqual(anchor_href, url)

    def assertLinkShortenedText(self, body, link_info, link_params=None):
        """ Assert the url of ``link_info`` in a text content is shortened
        (or not), and that its tracker carries ``link_params``.

        :param tuple link_info: (expected target url, is shortened)
        """
        (url, is_shortened) = link_info
        link_tracker = self.env['link.tracker'].search([('url', '=', url)])
        if is_shortened:
            self.assertEqual(len(link_tracker), 1)
            self.assertIn(link_tracker.short_url, body, '%s should be shortened' % (url))
            self.assertLinkParams(url, link_tracker, link_params=link_params)
        else:
            self.assertEqual(len(link_tracker), 0)
            self.assertIn(url, body)

    def assertLinkParams(self, url, link_tracker, link_params=None):
        """ Assert the tracker redirects to ``url`` with ``link_params`` as
        query parameters. """
        # check UTMS are correctly set on redirect URL
        original_url = urlsplit(url)
        redirect_url = urlsplit(link_tracker.redirected_url)
        redirect_params = dict(parse_qsl(redirect_url.query))
        self.assertEqual(redirect_url.scheme, original_url.scheme)
        self.assertEqual(redirect_url.netloc, original_url.netloc)
        self.assertEqual(redirect_url.path, original_url.path)
        if link_params:
            self.assertEqual(redirect_params, link_params)
