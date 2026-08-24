import logging
import re
from html import unescape

import markupsafe
from lxml import etree, html

from odoo import api, models
from odoo.tools.mail import TEXT_URL_REGEX, URL_SKIP_PROTOCOL_REGEX, is_html_empty

from odoo.addons.link_tracker.tools.html import (
    find_links_with_urls_and_labels,
    url_is_blacklisted,
)

_logger = logging.getLogger(__name__)

#: Skipped by ``_shorten_links_text`` before any caller blacklist. ``/r/`` is
#: ours -- shortening a short link chains a redirect onto itself. Anything else
#: belongs to the module that owns the route, and arrives through
#: ``_shorten_links_text_skip_prefixes``.
TEXT_SHORTEN_SKIP_PATHS = ('/r/',)


class MixinMailRender(models.AbstractModel):
    _inherit = "mixin.mail.render"

    # ------------------------------------------------------------
    # TOOLS
    # ------------------------------------------------------------

    @api.model
    def _shorten_links(self, body, link_tracker_vals, blacklist=None, base_url=None):
        """ Shorten links in an html content. Every ``<a>`` href is made
        absolute and replaced by a '/r/<code>' short URL, the route introduced
        in this module (mailto, tel and sms hrefs are skipped).

        :param link_tracker_vals: values given to the created link.tracker, containing
          for example: campaign_id, medium_id, source_id, and any other relevant fields
          like mass_mailing_id in mass_mailing;
        :param list blacklist: list of (local) URLs to not shorten (e.g.
          '/unsubscribe_from_list')
        :param str base_url: either given, either based on config parameter

        :return: updated html
        """
        if not body or is_html_empty(body):
            return body
        # TODO: take a record instead, to enable website-based URLs
        base_url = base_url or self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        short_schema = base_url + '/r/'

        try:
            # `fromstring` synthesises a wrapper element around a fragment with
            # several roots, so a two-paragraph body came back wrapped in a
            # `<div>` it never had. `fragments_fromstring` keeps the roots as they
            # are; the price is that the first item may be the leading text.
            fragments = html.fragments_fromstring(body)
        except etree.ParserError:
            # A body that parses to nothing -- an mso conditional comment and
            # nothing else -- used to raise out of here, onto the send path.
            _logger.warning("link_tracker: could not parse an html body, leaving its links alone")
            return body
        if not fragments:
            return body

        link_nodes, urls_and_labels = find_links_with_urls_and_labels(
            fragments, base_url, skip_regex=rf'^{URL_SKIP_PROTOCOL_REGEX}', skip_prefix=short_schema,
            skip_list=blacklist)
        if not link_nodes:
            return body

        links_trackers = self.env['link.tracker'].search_or_create([
            dict(link_tracker_vals, **url_and_label) for url_and_label in urls_and_labels
        ])
        for node, link_tracker in zip(link_nodes, links_trackers, strict=True):
            node.set("href", link_tracker.short_url)

        new_html = ''.join(
            fragment if isinstance(fragment, str)
            else html.tostring(fragment, encoding="unicode", method="xml")
            for fragment in fragments
        )
        if isinstance(body, markupsafe.Markup):
            # The input was trusted and the serializer is ours: nothing between
            # parse and serialise introduces markup the parser did not already see.
            new_html = markupsafe.Markup(new_html)

        return new_html

    @api.model
    def _shorten_links_text_skip_prefixes(self, base_url):
        """Absolute URL prefixes ``_shorten_links_text`` leaves alone.

        A hook rather than a constant so a route's own module can claim it. This
        one used to carry ``/sms/`` -- ``mass_mailing_sms``'s unsubscribe page --
        in a module that does not depend on ``sms``, and every caller of
        ``_shorten_links_text`` inherited that carve-out whether or not it could
        ever emit one.
        """
        return tuple(base_url + path for path in TEXT_SHORTEN_SKIP_PATHS)

    @api.model
    def _shorten_links_text(self, content, link_tracker_vals, blacklist=None, base_url=None):
        """ Shorten links in a string content. Works like ``_shorten_links`` but
        targeting string content, not html.

        :return: updated content
        """
        if not content:
            return content
        base_url = base_url or self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        skip_prefixes = self._shorten_links_text_skip_prefixes(base_url)

        # Sorted, not a bare set: iteration order used to vary with
        # PYTHONHASHSEED, so which URL got which code changed between runs.
        original_urls = sorted(set(TEXT_URL_REGEX.findall(content)))
        to_shorten = [
            url for url in original_urls
            if not url.startswith(skip_prefixes) and not url_is_blacklisted(url, blacklist)
        ]
        if not to_shorten:
            return content

        # One call, not one per URL: `search_or_create` is a batch API and calling
        # it with a single-item list inside the loop cost ~8 queries per link
        # against 4 for the whole batch.
        links = self.env['link.tracker'].search_or_create([
            dict(link_tracker_vals, url=unescape(url)) for url in to_shorten
        ])
        for original_url, link in zip(to_shorten, links, strict=True):
            if link.short_url:
                # Ensures we only replace the same link and not a subpart of a longer one, multiple times if applicable
                content = re.sub(
                    re.escape(original_url) + r'(?![\w@:%.+&~#=/-])',
                    lambda _match, short_url=link.short_url: short_url,
                    content,
                )

        return content
