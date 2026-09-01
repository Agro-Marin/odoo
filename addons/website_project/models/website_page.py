from odoo import api, models


class WebsitePage(models.Model):
    _inherit = "website.page"

    @api.model
    def _is_cache_usable(self, request):
        if request.httprequest.path == "/your-task-has-been-submitted":
            return False
        return super()._is_cache_usable(request)
