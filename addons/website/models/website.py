import base64
import fnmatch
import functools
import hashlib
import inspect
import json
import logging
import re
import threading
import types
from collections import defaultdict
from urllib.parse import urlencode, urlparse, urlunparse

import requests
import werkzeug.routing
from lxml import etree, html
from markupsafe import escape

from odoo import api, fields, models, release, tools
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Domain
from odoo.http import request
from odoo.libs.sql import escape_psql
from odoo.libs.web import contains_dot_segments
from odoo.modules.module import get_manifest
from odoo.tools import SQL, Query
from odoo.tools.image import image_process
from odoo.tools.translate import _

from odoo.addons.iap.tools import iap_tools
from odoo.addons.portal.controllers.portal import pager
from odoo.addons.website.models.ir_http import sitemap_qs2dom
from odoo.addons.website.tools import get_base_domain, similarity_score, text_from_html

logger = logging.getLogger(__name__)


DEFAULT_CDN_FILTERS = [
    "^/[^/]+/static/",
    "^/web/(css|js)/",
    "^/web/image",
    "^/web/content",
    "^/web/assets",
    "^/website/image/",
]

DEFAULT_WEBSITE_ENDPOINT = "https://website.api.odoo.com"
DEFAULT_OLG_ENDPOINT = "https://olg.api.odoo.com"


TEMPLATE_AFFECTING_FIELDS = frozenset(
    {
        "cdn_activated",
        "cdn_url",
        "cdn_filters",
        "cookies_bar",
        "block_third_party_domains",
        "custom_blocked_third_party_domains",
    }
)


DEFAULT_BLOCKED_THIRD_PARTY_DOMAINS = "youtu.be\nyoutube.com\nyoutube-nocookie.com\ninstagram.com\ninstagr.am\nig.me\nvimeo.com\ndailymotion.com\ndai.ly\nyouku.com\ntudou.com\nfacebook.com\nfacebook.net\nfb.com\nfb.me\nfb.watch\ntiktok.com\nx.com\ntwitter.com\nt.co\ngoogletagmanager.com\ngoogle-analytics.com\ngoogle.com\ngoogle.ad\ngoogle.ae\ngoogle.com.af\ngoogle.com.ag\ngoogle.al\ngoogle.am\ngoogle.co.ao\ngoogle.com.ar\ngoogle.as\ngoogle.at\ngoogle.com.au\ngoogle.az\ngoogle.ba\ngoogle.com.bd\ngoogle.be\ngoogle.bf\ngoogle.bg\ngoogle.com.bh\ngoogle.bi\ngoogle.bj\ngoogle.com.bn\ngoogle.com.bo\ngoogle.com.br\ngoogle.bs\ngoogle.bt\ngoogle.co.bw\ngoogle.by\ngoogle.com.bz\ngoogle.ca\ngoogle.cd\ngoogle.cf\ngoogle.cg\ngoogle.ch\ngoogle.ci\ngoogle.co.ck\ngoogle.cl\ngoogle.cm\ngoogle.cn\ngoogle.com.co\ngoogle.co.cr\ngoogle.com.cu\ngoogle.cv\ngoogle.com.cy\ngoogle.cz\ngoogle.de\ngoogle.dj\ngoogle.dk\ngoogle.dm\ngoogle.com.do\ngoogle.dz\ngoogle.com.ec\ngoogle.ee\ngoogle.com.eg\ngoogle.es\ngoogle.com.et\ngoogle.fi\ngoogle.com.fj\ngoogle.fm\ngoogle.fr\ngoogle.ga\ngoogle.ge\ngoogle.gg\ngoogle.com.gh\ngoogle.com.gi\ngoogle.gl\ngoogle.gm\ngoogle.gr\ngoogle.com.gt\ngoogle.gy\ngoogle.com.hk\ngoogle.hn\ngoogle.hr\ngoogle.ht\ngoogle.hu\ngoogle.co.id\ngoogle.ie\ngoogle.co.il\ngoogle.im\ngoogle.co.in\ngoogle.iq\ngoogle.is\ngoogle.it\ngoogle.je\ngoogle.com.jm\ngoogle.jo\ngoogle.co.jp\ngoogle.co.ke\ngoogle.com.kh\ngoogle.ki\ngoogle.kg\ngoogle.co.kr\ngoogle.com.kw\ngoogle.kz\ngoogle.la\ngoogle.com.lb\ngoogle.li\ngoogle.lk\ngoogle.co.ls\ngoogle.lt\ngoogle.lu\ngoogle.lv\ngoogle.com.ly\ngoogle.co.ma\ngoogle.md\ngoogle.me\ngoogle.mg\ngoogle.mk\ngoogle.ml\ngoogle.com.mm\ngoogle.mn\ngoogle.com.mt\ngoogle.mu\ngoogle.mv\ngoogle.mw\ngoogle.com.mx\ngoogle.com.my\ngoogle.co.mz\ngoogle.com.na\ngoogle.com.ng\ngoogle.com.ni\ngoogle.ne\ngoogle.nl\ngoogle.no\ngoogle.com.np\ngoogle.nr\ngoogle.nu\ngoogle.co.nz\ngoogle.com.om\ngoogle.com.pa\ngoogle.com.pe\ngoogle.com.pg\ngoogle.com.ph\ngoogle.com.pk\ngoogle.pl\ngoogle.pn\ngoogle.com.pr\ngoogle.ps\ngoogle.pt\ngoogle.com.py\ngoogle.com.qa\ngoogle.ro\ngoogle.ru\ngoogle.rw\ngoogle.com.sa\ngoogle.com.sb\ngoogle.sc\ngoogle.se\ngoogle.com.sg\ngoogle.sh\ngoogle.si\ngoogle.sk\ngoogle.com.sl\ngoogle.sn\ngoogle.so\ngoogle.sm\ngoogle.sr\ngoogle.st\ngoogle.com.sv\ngoogle.td\ngoogle.tg\ngoogle.co.th\ngoogle.com.tj\ngoogle.tl\ngoogle.tm\ngoogle.tn\ngoogle.to\ngoogle.com.tr\ngoogle.tt\ngoogle.com.tw\ngoogle.co.tz\ngoogle.com.ua\ngoogle.co.ug\ngoogle.co.uk\ngoogle.com.uy\ngoogle.co.uz\ngoogle.com.vc\ngoogle.co.ve\ngoogle.co.vi\ngoogle.com.vn\ngoogle.vu\ngoogle.ws\ngoogle.rs\ngoogle.co.za\ngoogle.co.zm\ngoogle.co.zw\ngoogle.cat"


def to_punycode(host):
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def from_punycode(host):
    try:
        return host.encode("ascii").decode("idna")
    except UnicodeError:
        return host


class Website(models.Model):
    _name = "website"

    _description = "Website"
    _order = "sequence, id"

    def website_domain(self):
        return Domain("website_id", "in", [False, *self.ids])

    def _active_languages(self):
        return self.env["res.lang"].search([]).ids

    def _default_default_lang_id(self):
        lang_code = self.env["ir.default"]._get("res.partner", "lang")
        def_lang_id = self.env["res.lang"]._get_data(code=lang_code).id
        return def_lang_id or self._active_languages()[0]

    name = fields.Char("Website Name", required=True)
    sequence = fields.Integer(default=10)
    domain = fields.Char("Website Domain", help="E.g. https://www.mydomain.com")
    domain_punycode = fields.Char(
        string="Punycode Domain",
        compute="_compute_domain_punycode",
        store=False,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    language_ids = fields.Many2many(
        "res.lang",
        "website_lang_rel",
        "website_id",
        "lang_id",
        string="Languages",
        default=_active_languages,
        required=True,
    )
    language_count = fields.Count("language_ids", "Number of languages")
    default_lang_id = fields.Many2one(
        "res.lang", string="Default Language", default=_default_default_lang_id, required=True
    )
    auto_redirect_lang = fields.Boolean(
        "Autoredirect Language",
        default=True,
        help="Should users be redirected to their browser's language",
    )
    cookies_bar = fields.Boolean(
        "Cookies Bar", help="Display a customizable cookies bar on your website."
    )
    configurator_done = fields.Boolean(
        help="True if configurator has been completed or ignored"
    )
    block_third_party_domains = fields.Boolean(
        "Block 3rd-party domains",
        help="Block 3rd-party domains that may track users (YouTube, Google Maps, etc.).",
        default=True,
    )
    custom_blocked_third_party_domains = fields.Text(
        "User list of blocked 3rd-party domains",
        groups="website.group_website_designer",
        translate=False,
    )
    blocked_third_party_domains = fields.Text(
        "List of blocked 3rd-party domains",
        compute="_compute_blocked_third_party_domains",
    )

    def _default_social_facebook(self):
        return self.env.ref("base.main_company").social_facebook

    def _default_social_github(self):
        return self.env.ref("base.main_company").social_github

    def _default_social_linkedin(self):
        return self.env.ref("base.main_company").social_linkedin

    def _default_social_youtube(self):
        return self.env.ref("base.main_company").social_youtube

    def _default_social_instagram(self):
        return self.env.ref("base.main_company").social_instagram

    def _default_social_twitter(self):
        return self.env.ref("base.main_company").social_twitter

    def _default_social_tiktok(self):
        return self.env.ref("base.main_company").social_tiktok

    def _default_social_discord(self):
        return self.env.ref("base.main_company").social_discord

    def _default_logo(self):
        with tools.file_open("website/static/src/img/website_logo.svg", "rb") as f:
            return base64.b64encode(f.read())

    logo = fields.Binary(
        "Website Logo", default=_default_logo, help="Display this logo on the website."
    )
    social_twitter = fields.Char("X Account", default=_default_social_twitter)
    social_facebook = fields.Char("Facebook Account", default=_default_social_facebook)
    social_github = fields.Char("GitHub Account", default=_default_social_github)
    social_linkedin = fields.Char("LinkedIn Account", default=_default_social_linkedin)
    social_youtube = fields.Char("Youtube Account", default=_default_social_youtube)
    social_instagram = fields.Char(
        "Instagram Account", default=_default_social_instagram
    )
    social_tiktok = fields.Char("TikTok Account", default=_default_social_tiktok)
    social_discord = fields.Char("Discord Account", default=_default_social_discord)
    social_default_image = fields.Binary(
        string="Default Social Share Image",
        help="If set, replaces the website logo as the default social share image.",
    )
    has_social_default_image = fields.Boolean(
        compute="_compute_has_social_default_image", store=True
    )

    google_analytics_key = fields.Char("Google Analytics Key")
    google_search_console = fields.Char(
        help="Google key, or Enable to access first reply"
    )

    google_maps_api_key = fields.Char("Google Maps API Key")

    plausible_shared_key = fields.Char()
    plausible_site = fields.Char()

    user_id = fields.Many2one("res.users", string="Public User", required=True)
    cdn_activated = fields.Boolean("Content Delivery Network (CDN)")
    cdn_url = fields.Char("CDN Base URL", default="")
    cdn_filters = fields.Text(
        "CDN Filters",
        default=lambda s: "\n".join(DEFAULT_CDN_FILTERS),
        help="URL matching those filters will be rewritten using the CDN Base URL",
    )
    partner_id = fields.Many2one(
        related="user_id.partner_id", string="Public Partner", readonly=False
    )
    menu_id = fields.Many2one(
        "website.menu", compute="_compute_menu_id", string="Main Menu"
    )
    homepage_url = fields.Char(help="E.g. /contactus or /shop")
    custom_code_head = fields.Html("Custom <head> code", sanitize=False)
    custom_code_footer = fields.Html("Custom end of <body> code", sanitize=False)

    robots_txt = fields.Html(
        "Robots.txt",
        translate=False,
        groups="website.group_website_designer",
        sanitize=False,
    )

    def _default_favicon(self):
        with tools.file_open("web/static/img/favicon.ico", "rb") as f:
            return base64.b64encode(f.read())

    favicon = fields.Binary(
        string="Website Favicon",
        help="This field holds the image used to display a favicon on the website.",
        default=_default_favicon,
    )
    theme_id = fields.Many2one("ir.module.module", help="Installed theme")

    specific_user_account = fields.Boolean(
        "Specific User Account",
        help="If True, new accounts will be associated to the current website",
    )
    auth_signup_uninvited = fields.Selection(
        [
            ("b2b", "On invitation"),
            ("b2c", "Free sign up"),
        ],
        string="Customer Account",
        default="b2b",
    )

    _domain_unique = models.Constraint(
        "unique(domain)",
        "Website Domain should be unique.",
    )

    @api.onchange("language_ids")
    def _onchange_language_ids(self):
        language_ids = self.language_ids._origin
        if language_ids and self.default_lang_id not in language_ids:
            self.default_lang_id = language_ids[0]

    @api.depends("domain")
    def _compute_domain_punycode(self):
        for website in self:
            website_domain = website.domain or ""
            parsed = urlparse(website_domain)
            hostname = parsed.hostname or ""
            if hostname:
                netloc = parsed.netloc.replace(hostname, to_punycode(hostname), 1)
                website.domain_punycode = urlunparse(parsed._replace(netloc=netloc))
            else:
                website.domain_punycode = website_domain

    @api.depends("social_default_image")
    def _compute_has_social_default_image(self):
        for website in self:
            website.has_social_default_image = bool(website.social_default_image)

    def _compute_menu_id(self):
        all_menus = self.env["website.menu"].search_fetch(
            Domain("website_id", "in", self.ids)
        )

        for website in self:
            menus = all_menus.filtered(
                lambda m, website=website: m.website_id == website
            )

            children = dict.fromkeys(menus, ())
            for menu in menus:
                if menu.parent_id and menu.parent_id in menus:
                    children[menu.parent_id] += (menu.id,)
            for menu, child_items in children.items():
                menu._fields["child_id"]._update_cache(menu, child_items)

            menus.mapped("is_visible")

            top_menus = menus.filtered(lambda m: not m.parent_id)
            website.menu_id = top_menus[:1].id

    @api.depends("custom_blocked_third_party_domains")
    def _compute_blocked_third_party_domains(self):
        for website in self:
            custom_list = website.sudo().custom_blocked_third_party_domains

            full_list = DEFAULT_BLOCKED_THIRD_PARTY_DOMAINS
            if custom_list:
                lines = custom_list.splitlines()
                custom_domains = "\n".join(
                    line for line in lines if line and line[0] != "#"
                )
                if lines and lines[0].startswith("#ignore_default"):
                    full_list = custom_domains
                else:
                    full_list += f"\n{custom_domains}"

            website.blocked_third_party_domains = full_list

    def _get_blocked_third_party_domains_list(self):
        return [
            domain
            for line in (self.blocked_third_party_domains or "").split("\n")
            if (domain := line.strip().lower())
        ]

    def _get_blocked_iframe_containers_classes(self):
        return {
            "s_map",
            "s_instagram_page",
            "o_facebook_page",
            "o_background_video",
            "media_iframe_video",
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._handle_create_write(vals)

            if "user_id" not in vals:
                company = self.env["res.company"].browse(
                    vals.get("company_id")
                ) or self.env.company
                vals["user_id"] = company._get_public_user().id

        websites = super().create(vals_list)
        self.env.registry.clear_cache()
        websites.company_id._compute_website_id()
        for website in websites:
            website._bootstrap_homepage()

        if (
            not self.env.user.has_group("website.group_multi_website")
            and self.search_count([]) > 1
        ):
            all_user_groups = "base.group_portal,base.group_user,base.group_public"
            groups = self.env["res.groups"].concat(
                *(self.env.ref(it) for it in all_user_groups.split(","))
            )
            groups.write(
                {"implied_ids": [(4, self.env.ref("website.group_multi_website").id)]}
            )

        return websites

    def write(self, vals):
        public_user_to_change_websites = self.env["website"]
        original_company = self.company_id
        values = vals
        self._handle_create_write(values)

        self.env.registry.clear_cache()

        if "company_id" in values and "user_id" not in values:
            public_user_to_change_websites = self.filtered(
                lambda w: w.sudo().user_id.company_id.id != values["company_id"]
            )
            if public_user_to_change_websites:
                company = self.env["res.company"].browse(values["company_id"])
                super(Website, public_user_to_change_websites).write(
                    dict(values, user_id=company and company._get_public_user().id)
                )

        result = super(Website, self - public_user_to_change_websites).write(values)

        if not TEMPLATE_AFFECTING_FIELDS.isdisjoint(values):
            self.env.registry.clear_cache("templates")

        if "sequence" in values or "company_id" in values:
            (original_company | self.company_id)._compute_website_id()

        if "cookies_bar" in values:
            for website in self:
                existing_policy_page = self.env["website.page"].search(
                    [
                        ("website_id", "=", website.id),
                        ("url", "=", "/cookie-policy"),
                    ]
                )
                if not values["cookies_bar"]:
                    existing_policy_page.unlink()
                elif not existing_policy_page:
                    cookies_view = self.env.ref(
                        "website.cookie_policy", raise_if_not_found=False
                    )
                    if cookies_view:
                        cookies_view.with_context(website_id=website.id).write(
                            {"website_id": website.id}
                        )
                        specific_cook_view = website.with_context(
                            website_id=website.id
                        ).viewref("website.cookie_policy")
                        self.env["website.page"].create(
                            {
                                "is_published": True,
                                "website_indexed": False,
                                "url": "/cookie-policy",
                                "website_id": website.id,
                                "view_id": specific_cook_view.id,
                            }
                        )

        return result

    @api.model
    def _handle_create_write(self, vals):
        self._handle_favicon(vals)
        self._handle_domain(vals)
        self._handle_homepage_url(vals)

    @api.model
    def _handle_favicon(self, vals):
        if vals.get("favicon"):
            vals["favicon"] = base64.b64encode(
                image_process(
                    base64.b64decode(vals["favicon"]),
                    size=(256, 256),
                    crop="center",
                    output_format="ICO",
                )
            )

    @api.model
    def _handle_domain(self, vals):
        if vals.get("domain"):
            vals["domain"] = self._normalize_domain_url(vals["domain"])

    def _normalize_domain_url(self, url):
        normalized_url = url
        if not normalized_url.startswith(("http://", "https://")):
            normalized_url = "https://%s" % normalized_url
        return normalized_url.rstrip("/")

    @api.model
    def _handle_homepage_url(self, vals):
        homepage_url = vals.get("homepage_url")
        if homepage_url:
            vals["homepage_url"] = homepage_url.rstrip("/")

    @api.constrains("domain")
    def _check_domain(self):
        for record in self:
            if not record.domain:
                continue

            try:
                parsed = urlparse(record.domain)
            except ValueError:
                raise ValidationError(
                    _("The provided website domain is not a valid URL.")
                ) from None

            if contains_dot_segments(parsed.path):
                raise ValidationError(
                    _(
                        "The domain path cannot contain relative path segments like '/./' or '/../'."
                    )
                )

    @api.constrains("homepage_url")
    def _check_homepage_url(self):
        for website in self.filtered("homepage_url"):
            if not website.homepage_url.startswith("/"):
                raise ValidationError(
                    _("The homepage URL should be relative and start with '/'.")
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_default_website(self):
        default_website = self.env.ref(
            "website.default_website", raise_if_not_found=False
        )
        if default_website and default_website in self:
            raise UserError(
                _(
                    "You cannot delete default website %s. Try to change its settings instead",
                    default_website.name,
                )
            )

    def unlink(self):
        self._remove_attachments_on_website_unlink()

        companies = self.company_id
        res = super().unlink()
        self.env.registry.clear_cache()
        companies._compute_website_id()
        return res

    def _remove_attachments_on_website_unlink(self):
        attachments_to_unlink = self.env["ir.attachment"].search(
            [
                ("website_id", "in", self.ids),
                "|",
                "|",
                ("key", "!=", False),
                ("url", "=like", "/_custom/%"),
                ("url", "ilike", ".assets\\_"),
            ]
        )
        attachments_to_unlink.unlink()

    def create_and_redirect_configurator(self):
        self._force()
        configurator_action_todo = self.env.ref("website.website_configurator_todo")
        return configurator_action_todo.action_launch()

    def _idna_url(self, url):
        return get_base_domain(url.lower(), True).encode("idna").decode("ascii")

    def _is_indexable_url(self, url):
        return self._idna_url(url) == self._idna_url(self.domain)


    def _api_rpc(self, route, params, endpoint_param_name, default_endpoint, **kwargs):
        params["version"] = release.version
        IrConfigParameter = self.env["ir.config_parameter"].sudo()
        api_endpoint = IrConfigParameter.get_param(
            endpoint_param_name, default_endpoint
        )
        return iap_tools.iap_jsonrpc(api_endpoint + route, params=params, **kwargs)

    def _website_api_rpc(self, route, params):
        return self._api_rpc(
            route, params, "website.website_api_endpoint", DEFAULT_WEBSITE_ENDPOINT
        )

    def _OLG_api_rpc(self, route, params):
        return self._api_rpc(
            route, params, "website.olg_api_endpoint", DEFAULT_OLG_ENDPOINT, timeout=45
        )

    def get_cta_data(self, website_purpose, website_type):
        return {"cta_btn_text": False, "cta_btn_href": "/contactus"}

    def _get_snippet_defaults(self, snippet):
        return {}

    def _get_snippet_view_key(self, snippet, page_code):
        if "." not in snippet:
            snippet = "website." + snippet
        module, snippet = snippet.split(".")
        return f"{module}.configurator_{page_code}_{snippet}"

    def _preconfigure_snippet(self, snippet, el, customizations):
        def modify_class(target_classes, class_name, operation):
            if operation == "remove" and class_name in target_classes:
                target_classes.remove(class_name)
            elif operation == "add" and class_name not in target_classes:
                target_classes.append(class_name)

        default_settings = self._get_snippet_defaults(snippet)
        if not (customizations or default_settings):
            return

        snippet_classes = el.get("class", "").split()

        filter_name = customizations.get("filter_xmlid") or default_settings.get(
            "filter_xmlid"
        )
        if filter_name:
            selected_filter = self.env.ref(filter_name)
            el.set("data-filter-id", str(selected_filter.id))
            el.set("data-number-of-records", str(selected_filter.limit))

        selected_template_key = customizations.get(
            "template_key"
        ) or default_settings.get("template_key")
        if selected_template_key:
            el.set("data-template-key", selected_template_key)
            template_class = re.sub(
                r".*\.dynamic_filter_template_", "s_", selected_template_key
            )
            if template_class not in snippet_classes:
                snippet_classes.append(template_class)

        snippet_classes.append("o_colored_level")

        class_modifications = [
            (
                "remove",
                customizations.get("remove_classes", [])
                or default_settings.get("remove_classes", []),
            ),
            (
                "add",
                customizations.get("add_classes", [])
                or default_settings.get("add_classes", []),
            ),
        ]

        for operation, items in class_modifications:
            for item in items:
                if isinstance(item, dict):
                    for selector, classes in item.items():
                        child_el = el.xpath(f"//*[hasclass('{selector}')]")
                        if child_el:
                            node = child_el[0]
                            child_classes = node.get("class", "").split()
                            modify_class(child_classes, classes, operation)
                            node.set("class", " ".join(child_classes))
                else:
                    modify_class(snippet_classes, item, operation)

        data_attributes = {
            **default_settings.get("data_attributes", {}),
            **customizations.get("data_attributes", {}),
        }
        for key, value in data_attributes.items():
            el.set(f"data-{key}", value)

        el.set("class", " ".join(snippet_classes))

        style = customizations.get("style", {}) or default_settings.get("style", {})
        if style:
            style_attr = " ".join(f"{attr}: {value};" for attr, value in style.items())
            el.set("style", style_attr)

        if "background" in customizations:
            self._set_background_options(el, customizations["background"])

        return

    def _set_background_options(self, el, background_options):
        snippet_classes = el.get("class").split()
        snippet_style = (el.get("style") or "").split()

        if "color" in background_options:
            snippet_classes = [c for c in snippet_classes if not c.startswith("o_cc")]
            snippet_classes.append("o_cc " + background_options["color"])
        if "image" in background_options:
            snippet_classes.append("oe_img_bg o_bg_img_center")
            snippet_style.append(background_options["image"])
        if "shape" in background_options:
            el.set(
                "data-oe-shape-data", background_options["shape"]["data-oe-shape-data"]
            )
            shape_el = html.fromstring(background_options["shape"]["element"])
            el.insert(0, shape_el)

        el.set("class", " ".join(snippet_classes))
        el.set("style", " ".join(snippet_style))

    @api.model
    def get_theme_configurator_snippets(self, theme_name):
        configurator_snippets = {
            **get_manifest("website")["configurator_snippets"],
            **get_manifest(theme_name).get("configurator_snippets", {}),
        }
        configurator_snippets_addons = {
            **get_manifest(theme_name).get("configurator_snippets_addons", {}),
        }

        if not configurator_snippets_addons:
            return configurator_snippets

        installed_modules = self.env["ir.module.module"]._installed()

        for module_name, module_addon in configurator_snippets_addons.items():
            if module_name not in installed_modules:
                continue
            for page, snippets_to_insert in module_addon.items():
                snippet_list = configurator_snippets.setdefault(page, [])
                for snippet_name, position, target in snippets_to_insert:
                    if snippet_name in snippet_list:
                        continue
                    try:
                        snippet_idx = snippet_list.index(target) + (position == "after")
                        snippet_list.insert(snippet_idx, snippet_name)
                    except ValueError:
                        logger.error(
                            "Skipping snippet '%s' because the target snippet is misconfigured.",
                            snippet_name,
                        )

        return configurator_snippets

    def configurator_set_menu_links(self, menu_company, module_data):
        menus = self.env["website.menu"].search(
            [("url", "in", list(module_data.keys())), ("website_id", "=", self.id)]
        )
        for m in menus:
            m.sequence = module_data[m.url]["sequence"]

    def configurator_get_footer_links(self):
        return [
            {"text": _("Privacy Policy"), "href": "/privacy"},
        ]

    @api.model
    def configurator_init(self):
        r = {}
        current_website = self.get_current_website()
        company = current_website.company_id
        configurator_features = self.env["website.configurator.feature"].search([])
        r["features"] = [
            {
                "id": feature.id,
                "name": feature.name,
                "description": feature.description,
                "type": "page" if feature.page_view_id else "app",
                "icon": feature.icon,
                "website_config_preselection": feature.website_config_preselection,
                "module_state": feature.module_id.state,
            }
            for feature in configurator_features
        ]
        r["logo"] = False
        if not company.uses_default_logo:
            r["logo"] = company.logo.decode("utf-8")
        r["configurator_done"] = current_website.configurator_done
        try:
            result = self._website_api_rpc(
                "/api/website/1/configurator/industries",
                {"lang": self.env.context.get("lang")},
            )
            r["industries"] = result["industries"]
        except AccessError as e:
            logger.warning(e.args[0])
            r["industries"] = []
        return r

    @api.model
    def configurator_recommended_themes(self, industry_id, palette, result_nbr_max=3):
        Module = request.env["ir.module.module"]
        domain = Module.get_themes_domain()
        domain = Domain.AND([[("name", "!=", "theme_default")], domain])
        client_themes = Module.search(domain).mapped("name")
        client_themes_img = {
            t: get_manifest(t).get("images_preview_theme", {})
            for t in client_themes
            if get_manifest(t)
        }
        themes_suggested = self._website_api_rpc(
            "/api/website/2/configurator/recommended_themes/%s"
            % (industry_id if industry_id > 0 else ""),
            {
                "client_themes": client_themes_img,
                "result_nbr_max": result_nbr_max,
            },
        )
        process_svg = self.env["website.configurator.feature"]._process_svg
        for theme in themes_suggested:
            theme["svg"] = process_svg(theme["name"], palette, theme.pop("image_urls"))
        return themes_suggested

    @api.model
    def configurator_skip(self):
        website = self.get_current_website()
        theme = self.env["ir.module.module"].search([("name", "=", "theme_default")])
        website.configurator_done = True
        return theme.button_choose_theme()

    @api.model
    def configurator_missing_industry(self, unknown_industry):
        self._website_api_rpc(
            "/api/website/unknown_industry",
            {
                "unknown_industry": unknown_industry,
                "lang": self.env.context.get("lang"),
            },
        )

    @api.model
    def configurator_apply(self, **kwargs):
        website = self.get_current_website()
        theme_name = kwargs["theme_name"]
        theme = self.env["ir.module.module"].search([("name", "=", theme_name)])
        redirect_url = theme.button_choose_theme()

        website.configurator_done = True

        tour_asset_id = self.env.ref("website.configurator_tour")
        tour_asset_id.copy(
            {"key": tour_asset_id.key, "website_id": website.id, "active": True}
        )

        logo_attachment_id = kwargs.get("logo_attachment_id")
        company = website.company_id
        if logo_attachment_id:
            attachment = self.env["ir.attachment"].browse(logo_attachment_id)
            attachment.write(
                {
                    "res_model": "website",
                    "res_field": "logo",
                    "res_id": website.id,
                }
            )
        elif not logo_attachment_id and not company.uses_default_logo:
            website.logo = company.logo.decode("utf-8")

        selected_palette = kwargs.get("selected_palette")
        if selected_palette:
            Assets = self.env["website.assets"]
            selected_palette_name = (
                selected_palette if isinstance(selected_palette, str) else "base-1"
            )
            Assets.make_scss_customization(
                "/website/static/src/scss/options/user_values.scss",
                {"color-palettes-name": "'%s'" % selected_palette_name},
            )
            if isinstance(selected_palette, list):
                Assets.make_scss_customization(
                    "/website/static/src/scss/options/colors/user_color_palette.scss",
                    {
                        f"o-color-{i}": color
                        for i, color in enumerate(selected_palette, 1)
                    },
                )

        cta_data = website.get_cta_data(
            kwargs.get("website_purpose"), kwargs.get("website_type")
        )
        if cta_data["cta_btn_text"]:
            xpath_view = "website.snippets"
            parent_view = (
                self.env["website"]
                .with_context(website_id=website.id)
                .viewref(xpath_view)
            )
            self.env["ir.ui.view"].create(
                {
                    "name": parent_view.key + " CTA",
                    "key": parent_view.key + "_cta",
                    "inherit_id": parent_view.id,
                    "website_id": website.id,
                    "type": "qweb",
                    "priority": 32,
                    "arch_db": """
                    <data>
                        <xpath expr="//t[@t-set='cta_btn_href']" position="replace">
                            <t t-set="cta_btn_href">%s</t>
                        </xpath>
                        <xpath expr="//t[@t-set='cta_btn_text']" position="replace">
                            <t t-set="cta_btn_text">%s</t>
                        </xpath>
                    </data>
                """
                    % (
                        escape(cta_data["cta_btn_href"]),
                        escape(cta_data["cta_btn_text"]),
                    ),
                }
            )
            try:
                view_id = self.env["website"].viewref("website.header_call_to_action")
                el = etree.fromstring(view_id.arch_db)
            except (MissingError, etree.XMLSyntaxError) as e:
                logger.warning("Could not update the header call to action: %s", e)
            else:
                btn_cta_el = el.xpath("//a[hasclass('btn_cta')]")
                if btn_cta_el:
                    btn_cta_el[0].attrib["href"] = cta_data["cta_btn_href"]
                    btn_cta_el[0].text = cta_data["cta_btn_text"]
                view_id.with_context(website_id=website.id).write(
                    {"arch_db": etree.tostring(el)}
                )

        features = self.env["website.configurator.feature"].browse(
            kwargs.get("selected_features")
        )

        menu_company = self.env["website.menu"]
        if (
            len(features.filtered("menu_sequence")) > 5
            and len(features.filtered("menu_company")) > 1
        ):
            menu_company = self.env["website.menu"].create(
                {
                    "name": _("Company"),
                    "parent_id": website.menu_id.id,
                    "website_id": website.id,
                    "sequence": 40,
                }
            )

        pages_views = {}
        modules = self.env["ir.module.module"]
        module_data = {}
        for feature in features:
            add_menu = bool(feature.menu_sequence)
            if feature.module_id:
                if feature.module_id.state != "installed":
                    modules += feature.module_id
                if add_menu:
                    if feature.module_id.name != "website_blog":
                        module_data[feature.feature_url] = {
                            "sequence": feature.menu_sequence
                        }
                    else:
                        blogs = module_data.setdefault("#blog", [])
                        blogs.append(
                            {"name": feature.name, "sequence": feature.menu_sequence}
                        )
            elif feature.page_view_id:
                result = self.env["website"].new_page(
                    name=feature.name,
                    add_menu=add_menu,
                    page_values={"url": feature.feature_url, "is_published": True},
                    menu_values=add_menu
                    and {
                        "url": feature.feature_url,
                        "sequence": feature.menu_sequence,
                        "parent_id": (feature.menu_company and menu_company.id)
                        or website.menu_id.id,
                    },
                    template=feature.page_view_id.key,
                )
                pages_views[feature.iap_page_code] = result["view_id"]

        if modules:
            modules.button_immediate_install()

        self.env["website"].browse(website.id).configurator_set_menu_links(
            menu_company, module_data
        )

        self.env["website"].configurator_addons_apply(**kwargs)

        website = self.env["website"].browse(website.id)

        footer_links = website.configurator_get_footer_links()
        footer_ids = [
            "website.template_footer_contact",
            "website.footer_custom",
            "website.template_footer_links",
            "website.template_footer_minimalist",
            "website.template_footer_mega",
            "website.template_footer_mega_columns",
            "website.template_footer_mega_links",
        ]
        for footer_id in footer_ids:
            view_id = self.env["website"].viewref(footer_id)
            if view_id:
                try:
                    arch_string = etree.fromstring(view_id.arch_db)
                except etree.XMLSyntaxError as e:
                    logger.warning(
                        "Failed to update footer links in view %s: %s", footer_id, e
                    )
                else:
                    el = arch_string.xpath("//t[@t-set='configurator_footer_links']")
                    if not el:
                        logger.warning(
                            "No 'configurator_footer_links' found in view %s", footer_id
                        )
                        continue
                    el[0].attrib["t-value"] = json.dumps(footer_links)
                    view_id.with_context(website_id=website.id).write(
                        {"arch_db": etree.tostring(arch_string)}
                    )

        industry_id = kwargs["industry_id"]
        custom_resources = self._website_api_rpc(
            "/api/website/2/configurator/custom_resources/%s"
            % (industry_id if industry_id > 0 else ""),
            {"theme": theme_name},
        )

        requested_pages = set(pages_views.keys()).union({"homepage"})
        configurator_snippets = website.get_theme_configurator_snippets(theme_name)
        industry = kwargs["industry_name"]

        IrQweb = self.env["ir.qweb"].with_context(
            website_id=website.id, lang=website.default_lang_id.code
        )
        text_generation_target_lang = self.get_current_website().default_lang_id.code
        text_must_be_translated_for_openai = not text_generation_target_lang.startswith(
            "en_"
        )

        html_text_processor = self.env[
            "website.html.text.processor"
        ]._with_processing_context(
            IrQweb=IrQweb,
            cta_data=cta_data,
            text_generation_target_lang=text_generation_target_lang,
            text_must_be_translated_for_openai=text_must_be_translated_for_openai,
        )
        generated_content = {}
        translated_content = {}
        for page_code in requested_pages - {"privacy_policy"}:
            snippet_list = configurator_snippets.get(page_code, [])
            for snippet in snippet_list:
                snippet_key = website._get_snippet_view_key(snippet, page_code)
                (
                    html_text_processor,
                    snippet_generated_content,
                    snippet_translated_content,
                ) = html_text_processor._get_snippet_content(snippet_key)
                generated_content.update(snippet_generated_content)
                translated_content.update(snippet_translated_content)

        translated_ratio = html_text_processor._calculate_translation_ratio(
            generated_content, translated_content
        )
        if translated_ratio > 0.8:
            try:
                database_id = (
                    self.env["ir.config_parameter"].sudo().get_param("database.uuid")
                )
                response = self._OLG_api_rpc(
                    "/api/olg/1/generate_placeholder",
                    {
                        "placeholders": list(generated_content.keys()),
                        "lang": website.default_lang_id.name,
                        "industry": industry,
                        "database_id": database_id,
                    },
                )
                name_replace_parser = re.compile(r"XXXX", re.MULTILINE)
                for key in generated_content:
                    if response.get(key):
                        generated_content[key] = name_replace_parser.sub(
                            lambda _m: website.name, response[key]
                        )
            except AccessError:
                pass
        else:
            logger.info(
                "Skip AI text generation because translation coverage is too low (%s%%)",
                translated_ratio * 100,
            )

        for index, page_code in enumerate(sorted(requested_pages)):
            snippet_list = configurator_snippets.get(page_code, [])
            if page_code == "homepage":
                page_view_id = self.with_context(website_id=website.id).viewref(
                    "website.homepage"
                )
            else:
                page_view_id = self.env["ir.ui.view"].browse(pages_views[page_code])
            rendered_snippets = []
            nb_snippets = len(snippet_list)
            theme_customizations = get_manifest(theme_name).get(
                "theme_customizations", {}
            )
            for i, snippet in enumerate(snippet_list, start=1):
                try:
                    snippet_key = website._get_snippet_view_key(snippet, page_code)
                    el = html_text_processor._update_snippet_content(
                        generated_content, snippet_key
                    )

                    el.attrib["data-snippet"] = snippet

                    customizations = theme_customizations.get(snippet, {})

                    website._preconfigure_snippet(snippet, el, customizations)

                    dialog_preview_els = el.find_class("s_dialog_preview")
                    for preview_el in dialog_preview_els:
                        preview_el.getparent().remove(preview_el)

                    if i == 1:
                        shape_el = el.xpath("//*[hasclass('o_we_shape')]")
                        if shape_el:
                            shape_el[0].attrib["class"] += (
                                " o_header_extra_shape_mapping"
                            )

                    if i == nb_snippets:
                        shape_el = el.xpath("//*[hasclass('o_we_shape')]")
                        if shape_el:
                            shape_el[0].attrib["class"] += (
                                " o_footer_extra_shape_mapping"
                            )
                    rendered_snippet = etree.tostring(el, encoding="unicode")
                    rendered_snippets.append(rendered_snippet)
                except ValueError as e:
                    logger.warning(e)
            page_view_id.save(
                value=f'<div class="oe_structure">{"".join(rendered_snippets)}</div>',
                xpath="(//div[hasclass('oe_structure')])[last()]",
            )
            page_view_id.copy(
                {
                    "key": f"{index}_{page_view_id.key}_configurator_pages_landing",
                    "website_id": website.id,
                }
            )

        images = custom_resources.get("images", {})
        names = (
            self.env["ir.model.data"]
            .search(
                [
                    ("name", "=ilike", f"configurator\\_{website.id}\\_%"),
                    ("module", "=", "website"),
                    ("model", "=", "ir.attachment"),
                ]
            )
            .mapped("name")
        )
        for name, image_src in images.items():
            extn_identifier = "configurator_%s_%s" % (website.id, name.split(".")[1])
            if extn_identifier in names:
                continue
            try:
                response = requests.get(image_src, timeout=3)
                response.raise_for_status()
            except Exception as e:
                logger.warning("Failed to download image: %s.\n%s", image_src, e)
            else:
                attachment = self.env["ir.attachment"].create(
                    {
                        "name": name,
                        "website_id": website.id,
                        "key": name,
                        "type": "binary",
                        "raw": response.content,
                        "public": True,
                    }
                )
                self.env["ir.model.data"].create(
                    {
                        "name": extn_identifier,
                        "module": "website",
                        "model": "ir.attachment",
                        "res_id": attachment.id,
                        "noupdate": True,
                    }
                )

        def fallback_create_missing_industry_image(image_name, fallback_img_name):
            image_name = f"website.{image_name}"
            if image_name not in images and f"website.{fallback_img_name}" in images:
                extn_identifier = "configurator_%s_%s" % (
                    website.id,
                    image_name.split(".")[1],
                )
                if extn_identifier not in names:
                    attachment = self.env["ir.attachment"].create(
                        {
                            "name": image_name,
                            "website_id": website.id,
                            "key": image_name,
                            "type": "binary",
                            "raw": self.env.ref(
                                f"website.configurator_{website.id}_{fallback_img_name}"
                            ).raw,
                            "public": True,
                        }
                    )
                    self.env["ir.model.data"].create(
                        {
                            "name": extn_identifier,
                            "module": "website",
                            "model": "ir.attachment",
                            "res_id": attachment.id,
                            "noupdate": True,
                        }
                    )

        fallback_industry_images = [
            ("s_intro_pill_default_image", "library_image_10"),
            ("s_intro_pill_default_image_2", "library_image_14"),
            ("s_banner_default_image_2", "s_image_text_default_image"),
            ("s_banner_default_image_3", "s_product_list_default_image_1"),
            ("s_striped_top_default_image", "s_picture_default_image"),
            ("s_text_cover_default_image", "s_cover_default_image"),
            ("s_showcase_default_image", "s_image_text_default_image"),
            ("s_image_hexagonal_default_image", "s_cover_default_image"),
            ("s_image_hexagonal_default_image_1", "s_company_team_image_1"),
            ("s_accordion_image_default_image", "s_image_text_default_image"),
            ("s_pricelist_boxed_default_background", "s_product_catalog_default_image"),
            ("s_image_title_default_image", "s_cover_default_image"),
            ("s_key_images_default_image_1", "s_media_list_default_image_1"),
            ("s_key_images_default_image_2", "s_image_text_default_image"),
            ("s_key_images_default_image_3", "s_media_list_default_image_2"),
            ("s_key_images_default_image_4", "s_text_image_default_image"),
            ("s_kickoff_default_image", "s_cover_default_image"),
            ("s_quadrant_default_image_1", "library_image_03"),
            ("s_quadrant_default_image_2", "library_image_10"),
            ("s_quadrant_default_image_3", "library_image_13"),
            ("s_quadrant_default_image_4", "library_image_05"),
            ("s_sidegrid_default_image_1", "library_image_03"),
            ("s_sidegrid_default_image_2", "library_image_10"),
            ("s_sidegrid_default_image_3", "library_image_13"),
            ("s_sidegrid_default_image_4", "library_image_05"),
            ("s_cta_box_default_image", "library_image_02"),
            ("s_image_punchy_default_image", "s_cover_default_image"),
            ("s_image_frame_default_image", "s_carousel_default_image_2"),
            ("s_carousel_intro_default_image_1", "s_cover_default_image"),
            ("s_carousel_intro_default_image_2", "s_image_text_default_image"),
            ("s_carousel_intro_default_image_3", "s_text_image_default_image"),
            ("s_website_form_overlay_default_image", "s_cover_default_image"),
            ("s_website_form_cover_default_image", "s_cover_default_image"),
            ("s_split_intro_default_image", "s_cover_default_image"),
            ("s_framed_intro_default_image", "s_cover_default_image"),
            ("s_wavy_grid_default_image_1", "s_cover_default_image"),
            ("s_wavy_grid_default_image_2", "s_image_text_default_image"),
            ("s_wavy_grid_default_image_3", "s_text_image_default_image"),
            ("s_wavy_grid_default_image_4", "s_carousel_default_image_1"),
            ("s_timeline_images_default_image_1", "s_media_list_default_image_1"),
            ("s_timeline_images_default_image_2", "s_media_list_default_image_2"),
            ("s_carousel_cards_default_image_1", "s_carousel_default_image_1"),
            ("s_carousel_cards_default_image_2", "s_carousel_default_image_2"),
            ("s_carousel_cards_default_image_3", "s_carousel_default_image_3"),
            ("s_banner_connected_default_image", "s_cover_default_image"),
        ]
        for image_name, fallback_img_name in fallback_industry_images:
            try:
                fallback_create_missing_industry_image(image_name, fallback_img_name)
            except Exception:
                logger.debug(
                    "Configurator fallback image %s could not be created",
                    image_name,
                    exc_info=True,
                )

        return {"url": redirect_url, "website_id": website.id}

    def configurator_addons_apply(self, industry_name=None, **kwargs):
        pass

    def _bootstrap_homepage(self):
        Page = self.env["website.page"]
        standard_homepage = self.env.ref("website.homepage", raise_if_not_found=False)
        if not standard_homepage:
            return

        new_homepage_view = """<t name="Homepage" t-name="website.homepage">
    <t t-call="website.layout" pageName.f="homepage">
        <div id="wrap" class="oe_structure oe_empty"/>
    </t>
</t>"""
        standard_homepage.with_context(website_id=self.id).arch_db = new_homepage_view

        homepage_page = Page.search(
            [
                ("website_id", "=", self.id),
                ("key", "=", standard_homepage.key),
            ],
            limit=1,
        )
        if not homepage_page:
            homepage_page = Page.create(
                {
                    "website_published": True,
                    "url": "/",
                    "view_id": self.with_context(website_id=self.id)
                    .viewref("website.homepage")
                    .id,
                }
            )
        homepage_page.url = "/"

        default_menu = self.env.ref("website.main_menu")
        self.copy_menu_hierarchy(default_menu)
        home_menu = self.env["website.menu"].search(
            [("website_id", "=", self.id), ("url", "=", "/")]
        )
        home_menu.page_id = homepage_page

    def copy_menu_hierarchy(self, top_menu):
        def copy_menu(menu, t_menu):
            new_menu = menu.copy(
                {
                    "parent_id": t_menu.id,
                    "website_id": self.id,
                }
            )
            for submenu in menu.child_id:
                copy_menu(submenu, new_menu)

        for website in self:
            new_top_menu = top_menu.copy(
                {
                    "name": _("Top Menu for Website %s", website.id),
                    "website_id": website.id,
                }
            )
            for submenu in top_menu.child_id:
                copy_menu(submenu, new_top_menu)

    @api.model
    def new_page(
        self,
        name=False,
        add_menu=False,
        template="website.default_page",
        ispage=True,
        namespace=None,
        page_values=None,
        menu_values=None,
        sections_arch=None,
        page_title=None,
    ):
        template_record = self.env.ref(template, raise_if_not_found=False)
        if not template_record:
            raise UserError(_("'%s' is not a valid template reference.", template))
        if namespace:
            template_module = namespace
        else:
            template_module = template.partition(".")[0]
        page_url = "/" + self.env["ir.http"]._slugify(name, max_length=1024, path=True)
        page_url = self.get_unique_path(page_url)
        page_key = self.env["ir.http"]._slugify(name)
        result = {"url": page_url}

        if not name:
            name = "Home"
            page_key = "home"

        arch = template_record.arch
        if sections_arch:
            tree = html.fromstring(arch)
            wrap = tree.xpath('//div[@id="wrap"]')[0]
            for section in html.fromstring(f"<wrap>{sections_arch}</wrap>"):
                wrap.append(section)
            arch = etree.tostring(tree, encoding="unicode")
        website_id = self.env.context.get("website_id")
        key = self.get_unique_key(page_key, template_module)
        view = template_record.copy({"website_id": website_id, "key": key})

        view.with_context(lang=None).write(
            {
                "arch": arch.replace(template, key),
                "name": page_title or name,
            }
        )
        result["view_id"] = view.id

        if view.arch_fs:
            view.arch_fs = False

        website = self.get_current_website()
        if ispage:
            default_page_values = {
                "url": page_url,
                "website_id": website.id,
                "view_id": view.id,
                "track": True,
            }
            if page_values:
                default_page_values.update(page_values)
            page = self.env["website.page"].create(default_page_values)
            result["page_id"] = page.id
        if add_menu:
            menu = self.env["website.menu"].search(
                [
                    ("url", "=", page_url),
                    ("website_id", "=", website.id),
                ],
                limit=1,
            )
            if not menu:
                default_menu_values = {
                    "name": name,
                    "url": page_url,
                    "parent_id": website.menu_id.id,
                    "page_id": page.id if ispage else False,
                    "website_id": website.id,
                }
                if menu_values:
                    default_menu_values.update(menu_values)
                menu = self.env["website.menu"].create(default_menu_values)
            result["menu_id"] = menu.id
        return result

    def get_unique_path(self, page_url):
        inc = 0
        website_id = (
            self.env.context.get("website_id", False) or self.get_current_website().id
        )
        domain_static = [("website_id", "=", website_id)]
        page_temp = page_url
        while (
            self.env["website.page"]
            .with_context(active_test=False)
            .sudo()
            .search([("url", "=", page_temp)] + domain_static)
        ):
            inc += 1
            page_temp = page_url + ((inc and "-%s" % inc) or "")
        return page_temp

    def _get_plausible_script_url(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "website.plausible_script", "https://plausible.io/js/plausible.js"
            )
        )

    def _get_plausible_server(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("website.plausible_server", "https://plausible.io")
        )

    def _get_plausible_share_url(self):
        embed_url = f"/share/{self.plausible_site}?auth={self.plausible_shared_key}&embed=true&theme=system"
        return (
            self.plausible_shared_key
            and tools.urls.urljoin(self._get_plausible_server(), embed_url)
        ) or ""

    def get_unique_key(self, string, template_module=False):
        if template_module:
            string = template_module + "." + string
        elif not string.startswith("website."):
            string = "website." + string

        key_copy = string
        inc = 0
        website_id = self.env.context.get("website_id", False)
        if website_id:
            domain_static = Domain("website_id", "in", (False, website_id))
        else:
            domain_static = self.get_current_website().website_domain()
        while (
            self.env["ir.ui.view"]
            .with_context(active_test=False)
            .sudo()
            .search(Domain("key", "=", key_copy) & domain_static)
        ):
            inc += 1
            key_copy = string + ((inc and "-%s" % inc) or "")
        return key_copy

    @api.model
    def search_url_dependencies(self, res_model, res_ids):
        dependencies = {}
        current_website = self.get_current_website()
        page_model_name = "Page"

        def _handle_views_and_pages(views):
            page_views = views.filtered("page_ids")
            views -= page_views
            if page_views:
                dependencies.setdefault(page_model_name, [])
                dependencies[page_model_name] += [
                    {
                        "field_name": "Content",
                        "record_name": page.name,
                        "link": page.url,
                        "model_name": page_model_name,
                    }
                    for page in page_views.page_ids
                ]
            return views

        search_criteria = []
        for record in self.env[res_model].browse([int(res_id) for res_id in res_ids]):
            website = ("website_id" in record and record.website_id) or current_website
            url = ("website_url" in record and record.website_url) or record.url
            search_criteria.append((url, website.website_domain()))

        for model_name, field_name in self._get_fields_html():
            Model = self.env[model_name]
            if not Model.has_access("read"):
                continue

            domains = []
            for url, website_domain in search_criteria:
                domains.append(
                    Domain.AND(
                        [
                            [(field_name, "ilike", url)],
                            website_domain if hasattr(Model, "website_id") else [],
                        ]
                    )
                )

            dependency_records = Model.search(Domain.OR(domains))
            if model_name == "ir.ui.view":
                dependency_records = _handle_views_and_pages(dependency_records)
            if dependency_records:
                model_label = self.env["ir.model"]._display_name_for([model_name])[0][
                    "display_name"
                ]
                field_string = Model.fields_get([field_name])[field_name]["string"]
                dependencies.setdefault(model_label, [])
                dependencies[model_label] += [
                    {
                        "field_name": field_string,
                        "record_name": rec.display_name,
                        "link": ("website_url" in rec and rec.website_url)
                        or f"/odoo/{model_name}/{rec.id}",
                        "model_name": model_label,
                    }
                    for rec in dependency_records
                ]

        return dependencies


    @api.model
    def get_current_website(self, fallback=True):
        is_frontend_request = request and getattr(request, "is_frontend", False)
        if request and request.session.get("force_website_id"):
            forced_id = request.session["force_website_id"]
            if self._is_forced_website_live(forced_id):
                return self.browse(forced_id)
            request.session.pop("force_website_id")

        website_id = self.env.context.get("website_id")
        if website_id:
            return self.browse(website_id)

        if not is_frontend_request and not fallback:
            return self.browse(False)


        domain_name = (
            (request and request.httprequest.host)
            or (
                hasattr(threading.current_thread(), "url")
                and threading.current_thread().url
            )
            or ""
        )
        website_id = self.sudo()._get_current_website_id(domain_name, fallback=fallback)
        return self.browse(website_id)

    @api.model
    def _is_forced_website_live(self, website_id):
        token = (website_id, self.pool.ormcache_lrus["default"].generation)
        if getattr(request, "_website_forced_token", None) == token:
            return True
        if not self.browse(website_id).exists():
            return False
        request._website_forced_token = token
        return True

    @api.model
    @tools.ormcache("domain_name", "fallback")
    def _get_current_website_id(self, domain_name, fallback=True):
        def _remove_port(domain_name):
            return (domain_name or "").split(":")[0]

        def _filter_domain(website, domain_name, ignore_port=False):
            website_domain = get_base_domain(website.domain_punycode)
            if ignore_port:
                website_domain = _remove_port(website_domain)
                domain_name = _remove_port(domain_name)
            return website_domain.lower() == (domain_name or "").lower()

        domain_name = to_punycode(domain_name or "")
        domain_name_idna = from_punycode(domain_name)

        found_websites = self.search(
            [
                "|",
                ("domain", "ilike", escape_psql(_remove_port(domain_name))),
                ("domain", "ilike", escape_psql(_remove_port(domain_name_idna))),
            ]
        )
        websites = found_websites.filtered(lambda w: _filter_domain(w, domain_name))
        websites = websites or found_websites.filtered(
            lambda w: _filter_domain(w, domain_name, ignore_port=True)
        )

        if not websites:
            if not fallback:
                return False
            return self.search([], limit=1).id

        return websites[0].id

    def _force(self):
        self._force_website(self.id)

    def _force_website(self, website_id):
        if request:
            request.session["force_website_id"] = (
                website_id and str(website_id).isdigit() and int(website_id)
            )

    @api.model
    def is_public_user(self):
        return request.env.user.id == request.website._get_cached("user_id")

    @api.model
    def viewref(self, view_id, raise_if_not_found=True):
        if not isinstance(view_id, (int, str)):
            raise ValueError(
                "Expecting a string or an integer, not a %s." % (type(view_id))
            )

        return (
            self.env["ir.ui.view"]
            .sudo()
            .with_context(active_test=False)
            ._get_template_view(view_id, raise_if_not_found=raise_if_not_found)
        )

    @api.model
    def is_view_active(self, key):
        return (
            self.env["ir.ui.view"]
            .with_context(active_test=False)
            ._get_cached_template_info(key)
            .get("active")
        )

    @api.model
    def get_template(self, template):
        if isinstance(template, str) and "." not in template:
            template = "website.%s" % template
        return self.env["ir.ui.view"]._get_template_view(template).sudo()

    @api.model
    def pager(self, url, total, page=1, step=30, scope=5, url_args=None):
        return pager(url, total, page=page, step=step, scope=scope, url_args=url_args)

    def rule_is_enumerable(self, rule):
        endpoint = rule.endpoint
        methods = endpoint.routing.get("methods") or ["GET"]

        converters = list(rule._converters.values())
        if not (
            "GET" in methods
            and endpoint.routing["type"] == "http"
            and endpoint.routing["auth"] in ("none", "public")
            and endpoint.routing.get("website", False)
            and all(hasattr(converter, "generate") for converter in converters)
        ):
            return False

        sign = inspect.signature(endpoint.original_endpoint)
        params = list(sign.parameters.values())[1:]
        supported_kinds = (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

        return all(
            p.name in rule._converters
            for p in params
            if p.kind in supported_kinds and p.default is inspect.Parameter.empty
        )

    def _enumerate_pages(self, query_string=None, force=False):
        domain = [("view_id", "!=", False), ("url", "!=", "/")]
        if not force:
            domain += [
                ("website_indexed", "=", True),
                ("website_published", "=", True),
                ("visibility", "=", False),
                "|",
                ("date_publish", "=", False),
                ("date_publish", "<=", fields.Datetime.now()),
            ]

        if query_string:
            domain += [("url", "like", query_string)]

        pages = self._get_website_pages(domain)

        for page in pages:
            record = {"loc": page["url"], "id": page["id"], "name": page["name"]}
            if page.view_id.priority != 16:
                record["priority"] = min(round(page.view_id.priority / 32.0, 1), 1)
            last_dates = [d for d in (page.write_date, page.view_write_date) if d]
            if last_dates:
                record["lastmod"] = max(last_dates).date()
            yield record

        router = self.env["ir.http"].routing_map()
        url_set = set()

        sitemap_endpoint_done = set()

        def _norm(url):
            return "/" if url == "/" else url.rstrip("/")

        def _unwrap_callable(f):
            if isinstance(f, functools.partial):
                f = f.func
            if isinstance(f, types.MethodType):
                return f.__func__
            return f

        for rule in router.iter_rules():
            sitemap_func = rule.endpoint.routing.get("sitemap")
            if sitemap_func is False:
                continue

            if callable(sitemap_func):
                func_key = _unwrap_callable(sitemap_func)
                if func_key in sitemap_endpoint_done:
                    continue
                sitemap_endpoint_done.add(func_key)
                for loc in sitemap_func(
                    self.with_context(lang=self.default_lang_id.code).env,
                    rule,
                    query_string,
                ):
                    loc_norm = {**loc, "loc": _norm(loc["loc"])}
                    url = loc_norm["loc"]
                    if url not in url_set:
                        yield loc_norm
                        url_set.add(url)
                continue

            if not self.rule_is_enumerable(rule):
                continue

            if "sitemap" not in rule.endpoint.routing:
                logger.warning(
                    "No Sitemap value provided for controller %s (%s)",
                    rule.endpoint.original_endpoint,
                    ",".join(rule.endpoint.routing["routes"]),
                )

            converters = rule._converters or {}
            if (
                query_string
                and not converters
                and (query_string not in rule.build({}, append_unknown=False)[1])
            ):
                continue

            values = [{}]
            convitems = sorted(
                converters.items(),
                key=lambda x: (
                    hasattr(x[1], "domain") and (x[1].domain != "[]"),
                    rule._trace.index((True, x[0])),
                ),
            )

            for i, (name, converter) in enumerate(convitems):
                website_domain = None
                if "website_id" in self.env[converter.model]._fields and (
                    not converter.domain or converter.domain == "[]"
                ):
                    website_domain = (
                        "[('website_id', 'in', (False, current_website_id))]"
                    )

                newval = []
                for val in values:
                    query = i == len(convitems) - 1 and query_string
                    if query:
                        r = "".join(
                            [x[1] for x in rule._trace[1:] if not x[0]]
                        )
                        query = sitemap_qs2dom(
                            query, r, self.env[converter.model]._rec_name
                        )
                        if query.is_false():
                            continue

                    for rec in converter.generate(
                        self.env, args=val, dom=query, domain=website_domain
                    ):
                        newval.append(val.copy())
                        newval[-1].update(
                            {name: rec.with_context(lang=self.default_lang_id.code)}
                        )
                values = newval

            for value in values:
                _domain_part, url = rule.build(value, append_unknown=False)
                url = _norm(url)
                pattern = query_string and "*%s*" % "*".join(query_string.split("/"))
                if not query_string or fnmatch.fnmatch(url.lower(), pattern):
                    page = {"loc": url}
                    if url in url_set:
                        continue
                    url_set.add(url)

                    yield page

    def get_website_page_ids(self):
        if not self.env.user.has_group("website.group_website_restricted_editor"):
            raise AccessError(_("Access Denied"))

        domain = Domain("url", "!=", False)
        pages_sudo = self.env["website.page"].sudo()

        if not self or not self.exists():
            pages = pages_sudo.search(domain)
            return {None: pages.ids}

        pages_by_website = {}
        for website in self:
            website_domain = Domain.AND((domain, website.website_domain()))
            pages = pages_sudo.search(website_domain)
            pages_for_website = pages.with_context(
                website_id=website.id
            )._get_most_specific_pages()
            pages_by_website[website.id] = pages_for_website.ids

        return pages_by_website

    def _get_website_pages(self, domain=None, order="name", limit=None):
        website = self.get_current_website()
        domain = Domain(domain or Domain.TRUE) & website.website_domain()
        pages = self.env["website.page"].sudo().search(domain, order=order, limit=limit)
        return pages.with_context(website_id=website.id)._get_most_specific_pages()

    def search_pages(self, needle=None, limit=None):
        name = self.env["ir.http"]._slugify(needle, max_length=50, path=True)
        res = []
        for page in self._enumerate_pages(query_string=name, force=True):
            res.append(page)
            if len(res) == limit:
                break
        return res

    def check_existing_page(self, page):
        if (
            len(
                self._get_website_pages(
                    domain=[("url", "=", page), ("view_id", "!=", False)], limit=1
                )
            )
            > 0
        ):
            return True

        redirects_domain = self.get_current_website().website_domain() & Domain(
            [("url_from", "=", page), ("redirect_type", "in", ("301", "302"))]
        )
        if len(self.env["website.rewrite"].search(redirects_domain, limit=1)) > 0:
            return True

        router = (
            request.env["ir.http"]
            .routing_map()
            .bind_to_environ(request.httprequest.environ)
        )
        if not router.test(path_info=page, method="GET"):
            return False

        try:
            rule, args = router.match(page, method="GET", return_rule=True)
        except werkzeug.routing.RequestRedirect:
            return True

        try:
            for arg in args:
                if isinstance(args[arg], models.BaseModel):
                    args[arg] = args[arg].with_user(self.env.uid)
                    if (
                        hasattr(args[arg], "website_id")
                        and args[arg].website_id
                        and args[arg].website_id != self
                    ):
                        return False
            rule.build(args, append_unknown=False)
        except MissingError:
            return False
        return True

    def get_suggested_controllers(self):
        return [
            (_("Homepage"), self.env["ir.http"]._url_for("/"), "website"),
            (
                _("Contact Us"),
                self.env["ir.http"]._url_for("/contactus"),
                "website_crm",
            ),
        ]

    @api.model
    def image_url(self, record, field, size=None):
        sudo_record = record.sudo()
        sha = hashlib.sha512(str(sudo_record.write_date).encode("utf-8")).hexdigest()[
            :7
        ]
        size = "" if size is None else "/%s" % size
        return "/web/image/%s/%s/%s%s?unique=%s" % (
            record._name,
            record.id,
            field,
            size,
            sha,
        )

    def get_cdn_url(self, uri):
        self.ensure_one()
        if not uri:
            return ""
        cdn_url = self.cdn_url
        cdn_filters = (self.cdn_filters or "").splitlines()
        for flt in cdn_filters:
            if flt and re.match(flt, uri):
                return tools.urls.urljoin(cdn_url, uri)
        return uri

    @api.model
    def action_dashboard_redirect(self):
        if self.env.user.has_group("base.group_system") or self.env.user.has_group(
            "website.group_website_designer"
        ):
            return self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
                "website.backend_dashboard"
            )
        raise AccessError(
            _("You don't have the necessary access rights to access this dashboard.")
        )

    def get_client_action_url(self, url, mode_edit=False, mode_debug=0):
        action_params = {
            "path": url,
        }
        if mode_edit:
            action_params["enable_editor"] = 1
        if mode_debug:
            action_params["debug"] = mode_debug
        return "/odoo/action-website.website_preview?" + urlencode(action_params)

    def get_client_action(self, url, mode_edit=False, website_id=False):
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id("website.website_preview")
        action["params"] = {
            "path": url,
            "enable_editor": mode_edit,
            "website_id": website_id,
        }
        return action

    def button_go_website(self, path="/"):
        self._force()
        return self.get_client_action(path)

    def _get_canonical_url(self):
        self.ensure_one()
        return self.env["ir.http"]._url_localized(
            lang_code=request.lang.code, canonical_domain=self.get_base_url()
        )

    def _is_canonical_url(self):
        self.ensure_one()
        current_url = (
            request.httprequest.url_root[:-1]
            + request.httprequest.environ["REQUEST_URI"]
        )
        canonical_url = self._get_canonical_url()
        return current_url == canonical_url

    @tools.ormcache("self.id")
    def _get_cached_values(self):
        self.ensure_one()


        self.fetch(
            ["user_id", "company_id", "default_lang_id", "homepage_url", "cookies_bar"]
        )
        return {
            "user_id": self.user_id.id,
            "company_id": self.company_id.id,
            "default_lang_id": self.default_lang_id.id,
            "homepage_url": self.homepage_url,
            "cookies_bar": self.cookies_bar,
        }

    def _get_cached(self, field):
        return self._get_cached_values()[field]

    def _get_fields_html_blacklist(self):
        return (
            "mail.message",
            "mail.activity",
            "digest.tip",
        )

    def _get_fields_html(self):
        html_fields = [("ir.ui.view", "arch_db")]
        cr = self.env.cr
        cr.execute(
            """
            SELECT f.model,
                   f.name
              FROM ir_model_fields f
              JOIN ir_model m
                ON m.id = f.model_id
             WHERE f.ttype = 'html'
               AND f.store = true
               AND m.transient = false
               AND f.model NOT LIKE 'ir.actions%%'
               AND f.model != ALL(%s)
        """,
            ([list(self._get_fields_html_blacklist())]),
        )
        for (
            model_name,
            field_name,
        ) in cr.fetchall():
            try:
                model = self.env[model_name]
                field = model._fields[field_name]
                if model._abstract or model._table_query or not field.store:
                    continue
            except KeyError:
                continue

            html_fields.append((model_name, field_name))
        return html_fields

    def _is_snippet_used(
        self, snippet_module, snippet_id, asset_version, asset_type, html_fields
    ):
        snippet_occurences = []
        snippet_template_html = self.env["ir.qweb"]._render(
            f"{snippet_module}.{snippet_id}", raise_if_not_found=False
        )
        if snippet_template_html:
            match = re.search(r'<([^>]*class="[^>]*)>', snippet_template_html)
            if match:
                snippet_occurences.append(match.group())

        if self._check_snippet_used(snippet_occurences, asset_type, asset_version):
            return True

        html_fields = [
            (self.env[model_name], field_name) for model_name, field_name in html_fields
        ]
        self.env.cr.execute(
            SQL(" UNION ").join(
                SQL(
                    "SELECT regexp_matches(%s, %s, 'g') FROM %s",
                    model._field_to_sql(model._table, field_name),
                    f'<([^>]*data-snippet="{snippet_id}"[^>]*)>',
                    SQL.identifier(model._table),
                )
                for model, field_name in html_fields
            )
        )

        snippet_occurences = [r[0][0] for r in self.env.cr.fetchall()]
        return self._check_snippet_used(snippet_occurences, asset_type, asset_version)

    def _check_snippet_used(self, snippet_occurences, asset_type, asset_version):
        for snippet in snippet_occurences:
            if asset_version == "000":
                if f"data-v{asset_type}" not in snippet:
                    return True
            elif f'data-v{asset_type}="{asset_version}"' in snippet:
                return True
        return False

    def _check_user_can_modify(self, record):
        record.check_access("write")

    def _disable_unused_snippets_assets(self):
        snippet_assets = (
            self.env["ir.asset"]
            .with_context(active_test=False)
            .search_fetch(
                [("path", "like", "/static%/snippets/")], ["active", "path"], order="id"
            )
        )
        snippet_re = re.compile(
            r"(\w*)\/.*\/snippets\/(\w*)\/(\d{3})(?:_\w*)?\.(js|scss)"
        )
        html_fields = self._get_fields_html()
        snippet_used = {}
        for snippet_asset in snippet_assets:
            match = snippet_re.match(snippet_asset.path)
            if not match:
                continue
            (snippet_module, snippet_id, asset_version, asset_type) = match.groups()
            if asset_type == "scss":
                asset_type = "css"
            key = (
                snippet_id,
                asset_version,
                asset_type,
            )
            if key not in snippet_used:
                snippet_used[key] = self._is_snippet_used(
                    snippet_module, snippet_id, asset_version, asset_type, html_fields
                )
            is_snippet_used = snippet_used[key]
            if is_snippet_used != snippet_asset.active:
                snippet_asset.active = is_snippet_used
                if (
                    snippet_id == "s_quotes_carousel"
                    and asset_type == "css"
                    and asset_version in ["000", "001"]
                ):
                    old_blockquote_key = ("s_blockquote", "000", "css")
                    if not snippet_used.get(old_blockquote_key):
                        snippet_used[old_blockquote_key] = True
                        old_blockquote_asset = snippet_assets.filtered(
                            lambda asset: (
                                asset.path
                                == "website/static/src/snippets/s_blockquote/000.scss"
                            )
                        )
                        if old_blockquote_asset and not old_blockquote_asset.active:
                            old_blockquote_asset.active = True
        self.env["ir.asset"].flush_model()

    def _search_get_details(self, search_type, order, options):
        result = []
        if search_type in ["pages", "all"]:
            result.append(
                self.env["website.page"]._search_get_detail(self, order, options)
            )
        return result

    def _search_with_fuzzy(self, search_type, search, limit, order, options):
        fuzzy_term = False
        search_details = self._search_get_details(search_type, order, options)
        if search and options.get("allowFuzzy", True):
            fuzzy_term = self._search_find_fuzzy_term(search_details, search)
            if fuzzy_term:
                count, results = self._search_exact(
                    search_details, fuzzy_term, limit, order
                )
                if fuzzy_term.lower() == search.lower():
                    fuzzy_term = False
            else:
                count, results = self._search_exact(
                    search_details, search, limit, order
                )
        else:
            count, results = self._search_exact(search_details, search, limit, order)
        return count, results, fuzzy_term

    def _search_exact(self, search_details, search, limit, order):
        all_results = []
        total_count = 0
        for search_detail in search_details:
            model = self.env[search_detail["model"]]
            results, count = model._search_fetch(search_detail, search, limit, order)
            search_detail["results"] = results
            total_count += count
            search_detail["count"] = count
            all_results.append(search_detail)
        return total_count, all_results

    def _search_render_results(self, search_details, limit):
        for search_detail in search_details:
            fields = search_detail["fetch_fields"]
            results = search_detail["results"]
            icon = search_detail["icon"]
            mapping = search_detail["mapping"]
            results_data = results._search_render_results(fields, mapping, icon, limit)
            search_detail["results_data"] = results_data
        return search_details

    def _search_find_fuzzy_term(
        self, search_details, search, limit=1000, word_list=None
    ):
        if (
            len(search) < 4
            or " " in search
            or len(re.findall(r"\d", search)) / len(search) >= 0.8
        ):
            return search
        search = search.lower()
        words = set()
        best_score = 0
        best_word = None
        enumerate_words = (
            self._trigram_enumerate_words
            if self.env.registry.has_trigram
            else self._basic_enumerate_words
        )
        for word in word_list or enumerate_words(search_details, search, limit):
            if search in word:
                return search
            if word[0] == search[0] and word not in words:
                similarity = similarity_score(search, word)
                if similarity > best_score:
                    best_score = similarity
                    best_word = word
                words.add(word)
        return best_word

    def _search_get_indirect_fields(self, fields, model):
        indirect_fields = {}
        for field in fields:
            field_parts = field.split(".")
            if len(field_parts) != 2:
                continue
            direct, indirect = field_parts
            if direct not in model._fields:
                continue
            direct_field = model._fields[direct]
            comodel_name = direct_field.comodel_name
            if comodel_name not in self.env:
                continue
            comodel_fields = self.env[comodel_name]._fields
            cofield = None
            if hasattr(direct_field, "_description_relation_field"):
                cofield = direct_field._description_relation_field
                if cofield not in comodel_fields:
                    continue
            if indirect in comodel_fields:
                indirect_fields[field] = {
                    "direct": direct,
                    "indirect": indirect,
                    "comodel": self.env[comodel_name],
                    "cofield": cofield,
                }
        return indirect_fields

    def _trigram_enumerate_words(self, search_details, search, limit):
        def get_similarity_subquery(
            model, fields, id_column, rel_table="", rel_joinkey=""
        ):
            subquery = Query(self.env.cr, model._table, model._table_query)
            unaccent = self.env.registry.unaccent
            similarity = SQL(
                "GREATEST(%(similarities)s) as similarity",
                similarities=SQL(", ").join(
                    SQL(
                        "word_similarity(%(search)s, %(field)s)",
                        search=unaccent(SQL("%s", search)),
                        field=unaccent(
                            model._field_to_sql(model._table, field, subquery)
                        ),
                    )
                    for field in fields
                ),
            )
            where_clauses = []
            for field_name in fields:
                field = model._fields[field_name]
                if field.translate:
                    alias = model._table
                    if field.related and not field.store:
                        _, field, alias = model._traverse_related_sql(
                            model._table, field, subquery
                        )
                    where_clauses.append(
                        SQL(
                            "(%(search)s <%% %(jsonb_path)s AND %(search)s <%% (%(field)s))",
                            search=unaccent(SQL("%s", search)),
                            jsonb_path=unaccent(
                                SQL(
                                    "jsonb_path_query_array(%s, '$.*')::text",
                                    SQL.identifier(alias, field.name),
                                )
                            ),
                            field=unaccent(
                                model._field_to_sql(model._table, field_name, subquery)
                            ),
                        )
                    )
                else:
                    where_clauses.append(
                        SQL(
                            "%(search)s <%% %(field)s",
                            search=unaccent(SQL("%s", search)),
                            field=unaccent(
                                model._field_to_sql(model._table, field_name, subquery)
                            ),
                        )
                    )
            subquery.add_where(SQL(" OR ").join(where_clauses))
            tbl_alias = model._table
            if rel_table:
                rel_alias = subquery.make_alias(rel_table, rel_joinkey)
                subquery.add_join(
                    "JOIN",
                    rel_alias,
                    rel_table,
                    SQL(
                        "%s = %s",
                        SQL.identifier(rel_alias, rel_joinkey),
                        SQL.identifier(model._table, "id"),
                    ),
                )
                tbl_alias = rel_alias
            return subquery.select(
                SQL("%s as id", SQL.identifier(tbl_alias, id_column)), similarity
            )

        match_pattern = r"[\w./-]{%s,}" % min(4, len(search) - 3)
        self.env.cr.execute("SET LOCAL pg_trgm.word_similarity_threshold to 0.3;")
        for search_detail in search_details:
            model_name, fields = search_detail["model"], search_detail["search_fields"]
            model = self.env[model_name]
            if search_detail.get("requires_sudo"):
                model = model.sudo()
            domain = Domain.AND(search_detail["base_domain"])
            direct_fields = set(fields).intersection(model._fields)
            indirect_fields = self._search_get_indirect_fields(fields, model)
            indirect_fields_info = defaultdict(
                dict
            )
            for name, indirect_field in indirect_fields.items():
                indirect_fields_info[indirect_field["comodel"]][name] = indirect_field
            subqueries = [get_similarity_subquery(model, direct_fields, "id")]
            for comodel in indirect_fields_info:
                comodel_similarity_fields = set()
                id_column = rel_table = rel_joinkey = ""
                for indirect_field_info in indirect_fields_info[comodel].values():
                    direct_field = model._fields[indirect_field_info["direct"]]
                    if direct_field.type == "one2many":
                        comodel_similarity_fields.add(indirect_field_info["indirect"])
                        id_column = indirect_field_info["cofield"]
                    elif direct_field.type == "many2many":
                        comodel_similarity_fields.add(indirect_field_info["indirect"])
                        id_column = direct_field.column1
                        rel_table = direct_field.relation
                        rel_joinkey = direct_field.column2
                subqueries.append(
                    get_similarity_subquery(
                        comodel,
                        comodel_similarity_fields,
                        id_column,
                        rel_table,
                        rel_joinkey,
                    )
                )
            query = SQL(
                """
                SELECT id,
                    MAX(similarity) as _best_similarity
                FROM (%s) sub
                GROUP BY id
                ORDER BY _best_similarity DESC
                LIMIT %s
            """,
                SQL("\nUNION ALL\n").join(subqueries),
                limit,
            )
            self.env.cr.execute(query)
            ids = {row[0] for row in self.env.cr.fetchall()}
            domain = Domain.AND([domain, Domain([("id", "in", list(ids))])])
            records = model.search_read(domain, direct_fields, limit=limit)
            for record in records:
                for value in record.values():
                    if isinstance(value, str):
                        value = value.lower()
                        yield from re.findall(match_pattern, value)
            if indirect_fields:
                records = model.search(domain, limit=limit)
                for indirect_field in indirect_fields:
                    for value in records.mapped(indirect_field):
                        if isinstance(value, str):
                            value = value.lower()
                            yield from re.findall(match_pattern, value)

    def _basic_enumerate_words(self, search_details, search, limit):
        match_pattern = r"[\w./-]{%s,}" % min(4, len(search) - 3)
        first = escape_psql(search[0])
        for search_detail in search_details:
            model_name, fields = search_detail["model"], search_detail["search_fields"]
            model = self.env[model_name]
            if search_detail.get("requires_sudo"):
                model = model.sudo()
            domain = Domain.AND(search_detail["base_domain"])
            direct_fields = set(fields).intersection(model._fields)
            indirect_fields = self._search_get_indirect_fields(fields, model)
            fields = direct_fields.union(indirect_fields)
            fields_domain = Domain.OR(
                Domain(field, "=ilike", pattern)
                for field in fields
                for pattern in (
                    "%s%%" % first,
                    "%% %s%%" % first,
                    "%%>%s%%" % first,
                )
            )
            domain &= fields_domain
            perf_limit = 1000
            records = model.search_read(domain, direct_fields, limit=perf_limit)
            if len(records) == perf_limit:
                exact_records, _count = model._search_fetch(
                    search_detail, search, 1, None
                )
                if exact_records:
                    yield search
            for record in records:
                for field, value in record.items():
                    if isinstance(value, str):
                        value = value.lower()
                        if field == "arch_db":
                            value = text_from_html(value)
                        for word in re.findall(match_pattern, value):
                            if word[0] == search[0]:
                                yield word.lower()
            if indirect_fields:
                records = model.search(domain, limit=limit)
                for indirect_field in indirect_fields:
                    for value in records.mapped(indirect_field):
                        if isinstance(value, str):
                            value = value.lower()
                            yield from re.findall(match_pattern, value)

    def _all_consents_granted(self):
        self.ensure_one()
        return not self.cookies_bar or self.env["ir.http"]._is_allowed_cookie(
            "optional"
        )
