import json
import logging
from datetime import date, timedelta

from psycopg.errors import LockNotAvailable

from odoo import _, fields, http
from odoo.fields import Domain
from odoo.http import request
from odoo.tools import file_open, format_amount

from odoo.addons.account.controllers.portal import PortalAccount

_logger = logging.getLogger(__name__)


class PosController(PortalAccount):
    @http.route("/pos/service-worker.js", type="http", auth="user")
    def pos_web_service_worker(self):
        return request.make_response(
            self._get_pos_service_worker(),
            [
                ("Content-Type", "text/javascript"),
                ("Service-Worker-Allowed", "/pos"),
            ],
        )

    def _get_pos_service_worker(self):
        with file_open("point_of_sale/static/src/app/service_worker.js") as f:
            return f.read()

    @http.route(["/pos/web", "/pos/ui"], type="http", auth="user")
    def old_pos_web(self, config_id=False, from_backend=False, **k):
        return self.pos_web(config_id, from_backend, **k)

    @http.route(
        ["/pos/ui/<config_id>", "/pos/ui/<config_id>/<path:subpath>"],
        auth="user",
        type="http",
    )
    def pos_web(self, config_id=False, from_backend=False, subpath=None, **k):
        is_internal_user = request.env.user._is_internal()
        pos_config = False
        if not is_internal_user:
            return request.not_found()
        if not request.env.user.has_group("point_of_sale.group_pos_user"):
            return request.redirect("/odoo/action-point_of_sale.action_client_pos_menu")
        if config_id:
            try:
                config_id = int(config_id)
            except (TypeError, ValueError):
                return request.not_found()
        domain = [
            ("state", "in", ["opening_control", "opened"]),
            ("user_id", "=", request.session.uid),
            ("rescue", "=", False),
        ]
        if config_id and request.env["pos.config"].sudo().browse(config_id).exists():
            domain = Domain.AND([domain, [("config_id", "=", config_id)]])
            pos_config = request.env["pos.config"].sudo().browse(config_id)
        pos_session = request.env["pos.session"].sudo().search(domain, limit=1)

        if not pos_session and config_id:
            domain = [
                ("state", "in", ["opening_control", "opened"]),
                ("rescue", "=", False),
                ("config_id", "=", config_id),
            ]
            pos_session = request.env["pos.session"].sudo().search(domain, limit=1)

        if (
            not pos_config
            or not pos_config.active
            or (pos_config.has_active_session and not pos_session)
        ):
            return request.redirect("/odoo/action-point_of_sale.action_client_pos_menu")

        if not pos_config.has_active_session:
            try:
                request.env.cr.execute(
                    "SELECT id FROM pos_config WHERE id = %s FOR UPDATE NOWAIT",
                    (pos_config.id,),
                )
            except LockNotAvailable:
                return request.redirect(
                    "/odoo/action-point_of_sale.action_client_pos_menu"
                )
            pos_config.open_ui()
            pos_session = request.env["pos.session"].sudo().search(domain, limit=1)

        company = pos_session.company_id
        session_info = request.env["ir.http"].session_info()
        allowed_companies = session_info["user_companies"]["allowed_companies"]
        if company.id not in allowed_companies:
            return request.redirect("/odoo/action-point_of_sale.action_client_pos_menu")
        session_info["user_context"]["allowed_company_ids"] = company.ids
        session_info["user_companies"] = {
            "current_company": company.id,
            "allowed_companies": {company.id: allowed_companies[company.id]},
        }
        session_info["nomenclature_id"] = pos_session.company_id.nomenclature_id.id
        session_info["fallback_nomenclature_id"] = (
            pos_session.config_id.fallback_nomenclature_id.id
        )
        use_lna = bool(
            pos_session.env["ir.config_parameter"].get_param("point_of_sale.use_lna")
        )
        context = {
            "from_backend": 1 if from_backend else 0,
            "use_pos_fake_tours": bool(k.get("tours")),
            "session_info": session_info,
            "pos_session_id": pos_session.id,
            "pos_config_id": pos_session.config_id.id,
            "access_token": pos_session.config_id.access_token,
            "last_data_change": pos_session.config_id.last_data_change.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "urls_to_cache": json.dumps(
                pos_config._get_url_to_cache(request.session.debug)
            ),
            "use_lna": use_lna,
        }
        response = request.render("point_of_sale.index", context)
        response.headers["Cache-Control"] = "no-store"
        return response

    @http.route(["/pos/ping"], type="jsonrpc", auth="user")
    def pos_ping(self):
        return {"response": "pong"}

    @http.route("/pos/sale_details_report", type="http", auth="user")
    def print_sale_details(self, date_start=False, date_stop=False, **kw):
        if not request.env.user.has_group("point_of_sale.group_pos_manager"):
            return request.not_found()
        pdf, _ = request.env["ir.actions.report"]._render_qweb_pdf(
            "point_of_sale.sale_details_report",
            data={"date_start": date_start, "date_stop": date_stop},
        )
        pdfhttpheaders = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf)),
        ]
        return request.make_response(pdf, headers=pdfhttpheaders)

    @staticmethod
    def _parse_ticket_date(value):
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @http.route(
        ["/pos/ticket"], type="http", auth="public", website=True, sitemap=False
    )
    def invoice_request_screen(self, **kwargs):
        errors = {}
        form_values = {}
        if request.httprequest.method == "POST":
            for field in ["pos_reference", "date_order", "ticket_code"]:
                if not kwargs.get(field):
                    errors[field] = " "
                else:
                    form_values[field] = kwargs.get(field)

            date_order = None
            if not errors:
                date_order = fields.Datetime.to_datetime(
                    self._parse_ticket_date(form_values["date_order"])
                )
                if not date_order:
                    errors["date_order"] = " "

            if errors:
                errors["generic"] = _("Please fill all the required fields.")
            elif len(form_values["pos_reference"]) < 12:
                errors["pos_reference"] = _(
                    "The Ticket Number should be at least 12 characters long."
                )
            else:
                order = (
                    request.env["pos.order"]
                    .sudo()
                    .search(
                        [
                            (
                                "pos_reference",
                                "=like",
                                "%"
                                + form_values["pos_reference"]
                                .strip()
                                .replace("%", r"\%")
                                .replace("_", r"\_"),
                            ),
                            ("date_order", ">=", date_order - timedelta(days=1)),
                            ("date_order", "<", date_order + timedelta(days=2)),
                            ("ticket_code", "=", form_values["ticket_code"]),
                        ],
                        limit=1,
                    )
                )
                if order:
                    return request.redirect(
                        "/pos/ticket/validate?access_token=%s" % (order.access_token)
                    )
                else:
                    errors["generic"] = _("No sale order found.")

        elif request.httprequest.method == "GET":
            if kwargs.get("order_uuid"):
                order = (
                    self.env["pos.order"]
                    .sudo()
                    .search([("uuid", "=", kwargs["order_uuid"])], limit=1)
                )
                if order:
                    return request.redirect(
                        "/pos/ticket/validate?access_token=%s" % (order.access_token)
                    )

        return request.render(
            "point_of_sale.ticket_request_with_code",
            {
                "errors": errors,
                "banner_error": " ".join(errors.values()),
                "form_values": form_values,
            },
        )

    @http.route(
        ["/pos/ticket/validate"],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def show_ticket_validation_screen(self, access_token="", **kwargs):
        def _parse_additional_values(fields, prefix, kwargs):
            res, res_prefixed = {}, {}
            for field in fields:
                key = prefix + field.name
                if key in kwargs:
                    val = kwargs.pop(key)
                    res[field.name] = val
                    res_prefixed[key] = val
            return res, res_prefixed

        if not access_token:
            return request.not_found()
        pos_order = (
            request.env["pos.order"]
            .sudo()
            .search([("access_token", "=", access_token)], limit=1)
        )
        if not pos_order:
            return request.not_found()

        if pos_order.state not in ("paid", "done"):
            return request.not_found()

        pos_order = pos_order.with_company(pos_order.company_id).with_context(
            allowed_company_ids=pos_order.company_id.ids
        )

        if pos_order.account_move and pos_order.account_move.is_sale_document():
            return request.redirect(
                "/my/invoices/%s?access_token=%s"
                % (
                    pos_order.account_move.id,
                    pos_order.account_move._portal_ensure_token(),
                )
            )

        if not request.env["res.company"]._with_locked_records(
            pos_order, allow_raising=False
        ):
            return None

        pos_order_country = pos_order.company_id.account_fiscal_country_id
        additional_partner_fields = request.env[
            "res.partner"
        ].get_partner_localisation_fields_required_to_invoice(pos_order_country)
        additional_invoice_fields = request.env[
            "account.move"
        ].get_invoice_localisation_fields_required_to_invoice(pos_order_country)

        user_is_connected = not request.env.user._is_public()

        form_values = {"extra_field_values": {}}
        partner = (
            user_is_connected and request.env.user.partner_id
        ) or pos_order.partner_id
        if kwargs and request.httprequest.method == "POST":
            form_values.update(kwargs)
            partner_values, prefixed_partner_values = _parse_additional_values(
                additional_partner_fields, "partner_", kwargs
            )
            form_values["extra_field_values"].update(prefixed_partner_values)
            invoice_values, prefixed_invoice_values = _parse_additional_values(
                additional_invoice_fields, "invoice_", kwargs
            )
            form_values["extra_field_values"].update(prefixed_invoice_values)
            partner, feedback_dict = self._create_or_update_address(
                partner, **(kwargs | partner_values)
            )
            form_values.update(feedback_dict)
            missing_fields, error_messages = self._validate_extra_form_details(
                partner_values | invoice_values,
                additional_partner_fields + additional_invoice_fields,
            )
            form_values.update(
                {
                    "invalid_field": form_values.get("invalid_fields", [])
                    + list(missing_fields),
                    "messages": form_values.get("messages", []) + error_messages,
                }
            )
            if not form_values.get("invalid_fields"):
                return self._get_invoice(
                    partner,
                    invoice_values,
                    pos_order,
                    additional_invoice_fields,
                    kwargs,
                )

        elif user_is_connected:
            return self._get_invoice(
                partner, {}, pos_order, additional_invoice_fields, kwargs
            )

        if "country" not in form_values:
            form_values["country"] = pos_order_country

        if partner:
            if additional_partner_fields:
                form_values["extra_field_values"] = {
                    "partner_" + field.name: (
                        partner[field.name].id
                        if field.ttype == "many2one"
                        else partner[field.name]
                    )
                    for field in additional_partner_fields
                    if field.name not in form_values["extra_field_values"]
                }

            if not partner.country_id or not partner.street:
                form_values["partner_address"] = False
            else:
                form_values["partner_address"] = partner._display_address()

        return request.render(
            "point_of_sale.ticket_validation_screen",
            {
                **self._prepare_address_form_values(partner, **kwargs),
                "partner": partner,
                "address_url": f"/my/account?redirect=/pos/ticket/validate?access_token={access_token}",
                "user_is_connected": user_is_connected,
                "format_amount": format_amount,
                "env": request.env,
                "pos_order": pos_order,
                "invoice_required_fields": additional_invoice_fields,
                "partner_required_fields": additional_partner_fields,
                "access_token": access_token,
                "invoice_sending_methods": {"email": _("by Email")},
                **form_values,
            },
        )

    def _validate_extra_form_details(
        self, addtional_form_values, additional_required_fields
    ):
        missing_fields = set()
        error_messages = []
        for field in additional_required_fields:
            if (
                field.name not in addtional_form_values
                or not addtional_form_values[field.name]
            ):
                missing_fields.add(field.name)
                error_messages.append(
                    _("The field %s must be filled.", field.field_description.lower())
                )
        return missing_fields, error_messages

    def _get_invoice(
        self, partner, invoice_values, pos_order, additional_invoice_fields, kwargs
    ):

        pos_order.partner_id = partner
        with_context = {}
        for field in additional_invoice_fields:
            with_context.update(
                {f"default_{field.name}": invoice_values.get(field.name)}
            )
        pos_order.with_context(with_context).action_pos_order_invoice()
        return request.redirect(
            "/my/invoices/%s?access_token=%s"
            % (pos_order.account_move.id, pos_order.account_move._portal_ensure_token())
        )
