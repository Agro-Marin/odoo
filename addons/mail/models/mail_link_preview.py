import re
from urllib.parse import urlparse

import requests
from dateutil.relativedelta import relativedelta
from lxml import html

from odoo import api, fields, models, tools
from odoo.tools.misc import OrderedSet

from odoo.addons.mail.tools.discuss import Store
from odoo.addons.mail.tools.link_preview import get_link_preview_from_url


class MailLinkPreview(models.Model):
    _name = "mail.link.preview"
    _inherit = ["bus.listener.mixin"]
    _description = "Store link preview data"
    _rec_name = "source_url"

    source_url = fields.Char("URL", required=True)
    source_url_netloc = fields.Char(
        "URL host",
        compute="_compute_source_url_netloc",
        store=True,
        index=True,
        help="Parsed host of source_url, used for per-host throttling.",
    )
    og_type = fields.Char("Type")
    og_title = fields.Char("Title")
    og_site_name = fields.Char("Site name")
    og_image = fields.Char("Image")
    og_description = fields.Text("Description")
    og_mimetype = fields.Char("MIME type")
    image_mimetype = fields.Char("Image MIME type")
    create_date = fields.Datetime(index=True)
    message_link_preview_ids = fields.One2many(
        "mail.message.link.preview", "link_preview_id", groups="base.group_erp_manager"
    )

    _unique_source_url = models.UniqueIndex("(source_url)")

    @api.model
    def _create_from_message_and_notify(self, message, request_url=None):
        urls = []
        if not tools.is_html_empty(message.body):
            urls = OrderedSet(
                html.fromstring(message.body).xpath("//a[not(@data-oe-model)]/@href")
            )
            if request_url:
                ignore_pattern = re.compile(
                    f"{re.escape(request_url)}(odoo|web|chat)(/|$|#|\\?)"
                )
                urls = list(filter(lambda url: not ignore_pattern.match(url), urls))
        requests_session = requests.Session()
        message_link_previews_ok = self.env["mail.message.link.preview"]
        link_previews_values = []  # list of (sequence, values)
        message_link_previews_values = []  # list of (sequence, mail.link.preview record)
        message_link_preview_by_url = {
            message_link_preview.link_preview_id.source_url: message_link_preview
            for message_link_preview in message.sudo().message_link_preview_ids
        }
        link_preview_by_url = {}
        if len(message_link_preview_by_url) != len(urls):
            # don't make the query if all `mail.message.link.preview` have been found
            link_preview_by_url = {
                link_preview.source_url: link_preview
                for link_preview in self.env["mail.link.preview"].search(
                    [("source_url", "in", urls)]
                )
            }
        for index, url in enumerate(urls):
            if message_link_preview := message_link_preview_by_url.get(url):
                message_link_preview.sequence = index
                message_link_previews_ok += message_link_preview
            elif link_preview := link_preview_by_url.get(url):
                message_link_previews_values.append((index, link_preview))
            elif not self._is_domain_thottled(url):
                if link_preview_values := get_link_preview_from_url(
                    url, requests_session
                ):
                    link_previews_values.append((index, link_preview_values))
            if (
                len(message_link_previews_ok)
                + len(message_link_previews_values)
                + len(link_previews_values)
                >= 5
            ):
                # cap at 5: the check runs after appending this iteration's
                # preview, so ``> 5`` let a 6th through before stopping.
                break
        new_link_preview_by_url = {
            link_preview.source_url: link_preview
            for link_preview in self.env["mail.link.preview"].create(
                [values for sequence, values in link_previews_values]
            )
        }
        for sequence, values in link_previews_values:
            message_link_previews_values.append(
                (sequence, new_link_preview_by_url[values["source_url"]])
            )
        message_link_previews_ok += self.env["mail.message.link.preview"].create(
            [
                {
                    "sequence": sequence,
                    "link_preview_id": link_preview.id,
                    "message_id": message.id,
                }
                for sequence, link_preview in message_link_previews_values
            ]
        )
        (
            message.sudo().message_link_preview_ids - message_link_previews_ok
        )._unlink_and_notify()
        Store(
            bus_channel=message._bus_channel(),
        ).add(message, "message_link_preview_ids").bus_send()

    @api.model
    def _is_link_preview_enabled(self):
        link_preview_throttle = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.link_preview_throttle", 99)
        )
        return link_preview_throttle > 0

    @api.depends("source_url")
    def _compute_source_url_netloc(self):
        for preview in self:
            preview.source_url_netloc = urlparse(preview.source_url or "").netloc

    def _is_domain_thottled(self, url):
        domain = urlparse(url).netloc
        # cr.now() is naive UTC like the stored create_date; datetime.now() is
        # naive *local* time, so on a non-UTC server the "10s" window was skewed
        # by the UTC offset (spanning hours and massively over-throttling).
        date_interval = fields.Datetime.to_string(
            self.env.cr.now() - relativedelta(seconds=10)
        )
        # Count recent previews for the SAME host through the indexed netloc
        # column, instead of fetching the whole create_date window across every
        # host and re-parsing each source_url in Python (O(previews) per url under
        # a preview storm).
        call_counter = self.env["mail.link.preview"].search_count(
            [
                ("create_date", ">", date_interval),
                ("source_url_netloc", "=", domain),
            ]
        )
        link_preview_throttle = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.link_preview_throttle", 99)
        )
        return call_counter > link_preview_throttle

    @api.model
    def _search_or_create_from_url(self, url):
        """Return the URL preview, first from the database if available otherwise make the request."""
        preview = self.env["mail.link.preview"].search([("source_url", "=", url)])
        if not preview:
            if self._is_domain_thottled(url):
                return self.env["mail.link.preview"]
            preview_values = get_link_preview_from_url(url)
            if not preview_values:
                return self.env["mail.link.preview"]
            preview = self.env["mail.link.preview"].create(preview_values)
        return preview

    def _to_store_defaults(self, target):
        return [
            "image_mimetype",
            "og_description",
            "og_image",
            "og_mimetype",
            "og_site_name",
            "og_title",
            "og_type",
            "source_url",
        ]
