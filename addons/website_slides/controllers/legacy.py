from odoo import http
from odoo.http import request
from odoo.tools.urls import keep_query


class WebsiteSlidesLegacy(http.Controller):
    @http.route(
        ["/slides/all", "/slides/all/tag/<string:slug_tags>"],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
        readonly=True,
    )
    def slides_channel_all(self, slug_tags=None, **post):
        if slug_tags:
            return request.redirect(f"/slides/tag/{slug_tags}?{keep_query('*')}")
        return request.redirect(f"/slides?{keep_query('*')}")
