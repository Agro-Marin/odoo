from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request
from odoo.tools.urls import keep_query


class AppointmentLegacy(http.Controller):
    """
    Retro compatibility layer for legacy endpoint
    """

    @http.route(
        ["/calendar/<string:appointment_type>/appointment"],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def calendar_appointment(self, appointment_type, **kwargs):
        """Redirect the pre-16.0 URL to the current one.

        `appointment_type` is a slug rather than a recordset: the `model()`
        converter browses the record, which needs read access on
        appointment.type that public users no longer have, so this route used to
        404 for exactly the visitors it exists to serve. The sibling legacy route
        in controllers/appointment.py already takes this shape.

        The former `filter_staff_user_ids`, `timezone` and `failed` parameters
        were never read - `keep_query("*")` already forwards them.
        """
        appointment_type_id = request.env["ir.http"]._unslug(appointment_type)[1]
        if not appointment_type_id:
            raise NotFound
        return request.redirect(
            "/calendar/%s?%s" % (appointment_type_id, keep_query("*"))
        )
