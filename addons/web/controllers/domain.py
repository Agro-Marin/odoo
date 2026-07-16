from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import Controller, request
from odoo.tools import SQL
from odoo.tools.misc import mute_logger


class Domain(Controller):
    @http.route("/web/domain/validate", type="jsonrpc", auth="user", readonly=True)
    def validate(self, model: str, domain: list) -> bool:
        """Parse `domain` and verify that it can be used to search on `model`
        :return: True when the domain is valid, otherwise False
        :raises ValidationError: if `model` is invalid
        """
        Model = request.env.get(model)
        if Model is None:
            raise ValidationError(_("Invalid model: %s", model))
        try:
            # Building the query raises if the domain is invalid.
            query = Model.sudo()._search(domain)

            # Run in EXPLAIN mode so Postgres parses and plans the query without
            # executing it. (A LIMIT 0 would also avoid execution, but Query.select()
            # omits the LIMIT clause entirely when limit is falsy, so limit=0 here
            # wouldn't produce one.)
            sql = SQL("EXPLAIN %s", query.select())
            with mute_logger("odoo.db"):
                request.env.cr.execute(sql)
            return True
        except Exception:  # pylint: disable=broad-except
            return False
