# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import urllib.parse

from odoo import api, fields, models
from odoo.http import request
from odoo.libs.web import urljoin as url_join

logger = logging.getLogger(__name__)


class MixinWebsiteSeoMetadata(models.AbstractModel):
    _name = "mixin.website.seo.metadata"

    _description = "SEO metadata"

    is_seo_optimized = fields.Boolean(
        "SEO optimized", compute="_compute_is_seo_optimized", store=True
    )
    website_meta_title = fields.Char(
        "Website meta title", translate=True, prefetch="website_meta"
    )
    website_meta_description = fields.Text(
        "Website meta description", translate=True, prefetch="website_meta"
    )
    website_meta_keywords = fields.Char(
        "Website meta keywords", translate=True, prefetch="website_meta"
    )
    website_meta_og_img = fields.Char("Website opengraph image")
    seo_name = fields.Char("Seo name", translate=True, prefetch=True)

    @api.depends(
        "website_meta_title", "website_meta_description", "website_meta_keywords"
    )
    def _compute_is_seo_optimized(self):
        for record in self:
            record.is_seo_optimized = bool(
                record.website_meta_title
                and record.website_meta_description
                and record.website_meta_keywords
            )

    def _default_website_meta(self):
        """This method will return default meta information. It return the dict
        contains meta property as a key and meta content as a value.
        e.g. 'og:type': 'website'.

        Override this method in case you want to change default value
        from any model. e.g. change value of og:image to product specific
        images instead of default images
        """
        self.ensure_one()
        company = request.website.company_id.sudo()
        title = request.website.name
        if "name" in self:
            title = "%s | %s" % (self.name, title)

        img_field = (
            "social_default_image"
            if request.website.has_social_default_image
            else "logo"
        )

        # Default meta for OpenGraph
        default_opengraph = {
            "og:type": "website",
            "og:title": title,
            "og:site_name": request.website.name,
            "og:url": url_join(
                request.website.domain or request.httprequest.url_root,
                self.env["ir.http"]._url_for(request.httprequest.path),
            ),
            "og:image": request.website.image_url(request.website, img_field),
        }
        # Default meta for Twitter
        default_twitter = {
            "twitter:card": "summary_large_image",
            "twitter:title": title,
            "twitter:image": request.website.image_url(
                request.website, img_field, size="300x300"
            ),
        }
        if company.social_twitter:
            default_twitter["twitter:site"] = (
                "@%s" % company.social_twitter.split("/")[-1]
            )

        return {
            "default_opengraph": default_opengraph,
            "default_twitter": default_twitter,
        }

    def get_website_meta(self):
        """This method will return final meta information. It will replace
        default values with user's custom value (if user modified it from
        the seo popup of frontend)

        This method is not meant for overridden. To customize meta values
        override `_default_website_meta` method instead of this method. This
        method only replaces user custom values in defaults.
        """
        root_url = request.website.domain or request.httprequest.url_root.strip("/")
        default_meta = self._default_website_meta()
        opengraph_meta, twitter_meta = (
            default_meta["default_opengraph"],
            default_meta["default_twitter"],
        )
        if self.website_meta_title:
            opengraph_meta["og:title"] = self.website_meta_title
            twitter_meta["twitter:title"] = self.website_meta_title
        if self.website_meta_description:
            opengraph_meta["og:description"] = self.website_meta_description
            twitter_meta["twitter:description"] = self.website_meta_description
        # 19.0: remove domain of absolute URL before odoo/odoo#228253
        og_image = self.website_meta_og_img and urllib.parse.urlunsplit(
            ["", "", *urllib.parse.urlsplit(self.website_meta_og_img)[2:]]
        )
        opengraph_meta["og:image"] = url_join(
            root_url,
            self.env["ir.http"]._url_for(og_image or opengraph_meta["og:image"]),
        )
        twitter_meta["twitter:image"] = url_join(
            root_url,
            self.env["ir.http"]._url_for(og_image or twitter_meta["twitter:image"]),
        )
        return {
            "opengraph_meta": opengraph_meta,
            "twitter_meta": twitter_meta,
            "meta_description": default_meta.get("default_meta_description"),
        }
