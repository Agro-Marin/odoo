from odoo import _, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import Controller, request
from odoo.tools import SQL
from odoo.tools.misc import mute_logger

from .utils import is_user_internal


class Domain(Controller):
    @http.route("/web/domain/validate", type="jsonrpc", auth="user", readonly=True)
    def validate(self, model: str, domain: list) -> bool:
        if not is_user_internal(request.session.uid):
            raise AccessError(_("This endpoint is reserved to internal users."))
        Model = request.env.get(model)
        if Model is None:
            raise ValidationError(_("Invalid model: %s", model))
        try:
            query = Model.sudo()._search(domain)

            sql = SQL("EXPLAIN %s", query.select())
            with mute_logger("odoo.db"):
                request.env.cr.execute(sql)
            return True
        except Exception:
            return False
