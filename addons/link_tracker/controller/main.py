from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request


class LinkTracker(http.Controller):

    @http.route('/r/<string:code>', type='http', auth='public', website=True)
    def full_url_redirect(self, code, **post):
        redirect_url = request.env['link.tracker']._resolve_and_track(
            code,
            ip=request.httprequest.remote_addr,
            country_code=request.geoip.country_code,
        )
        if not redirect_url:
            raise NotFound
        return request.redirect(redirect_url, code=301, local=False)
