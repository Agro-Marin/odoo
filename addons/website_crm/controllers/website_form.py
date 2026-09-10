from odoo import Command, tools
from odoo.http import request

from odoo.addons.phone_validation.tools import phone_validation
from odoo.addons.website.controllers import form


class WebsiteForm(form.WebsiteForm):
    def _get_country(self):
        visitor_partner = (
            request.env["website.visitor"]._get_visitor_from_request().partner_id
        )
        if visitor_partner:
            country = visitor_partner.country_id or request.env.company.country_id
            if country:
                return country
        country_code = request.geoip.country_code
        if country_code:
            return (
                request.env["res.country"]
                .sudo()
                .search([("code", "=", country_code)], limit=1)
            )
        return request.env["res.country"]

    def _handle_website_form(self, model_name, **kwargs):
        model_record = (
            request.env["ir.model"]
            .sudo()
            .search([("model", "=", model_name), ("website_form_access", "=", True)])
        )
        if model_record:
            try:
                data = self.extract_data(model_record, request.params)
            except Exception:  # noqa: S110  no specific management, super will do it
                pass
            else:
                record = data.get("record", {})
                phone_fields = request.env[model_name]._get_phone_number_fields()
                country = request.env["res.country"].browse(record.get("country_id"))
                contact_country = country if country.exists() else self._get_country()
                for phone_field in phone_fields:
                    number = request.params.pop(
                        self._phone_param_name(phone_field), None
                    )
                    if not number:
                        continue
                    fmt_number = phone_validation.phone_format(
                        number,
                        contact_country.code if contact_country else None,
                        contact_country.phone_code if contact_country else None,
                        force_format="INTERNATIONAL",
                        raise_exception=False,
                    )
                    request.update_context(
                        **{f"website_form_{phone_field}": fmt_number or number}
                    )

        if model_name == "crm.lead" and not request.params.get("state_id"):
            geoip_country_code = request.geoip.country_code
            geoip_state_code = (
                request.geoip.subdivisions[0].iso_code
                if request.geoip.subdivisions
                else None
            )
            if geoip_country_code and geoip_state_code:
                state = request.env["res.country.state"].search(
                    [
                        ("code", "=", geoip_state_code),
                        ("country_id.code", "=", geoip_country_code),
                    ]
                )
                if state:
                    request.params["state_id"] = state.id
        return super()._handle_website_form(model_name, **kwargs)

    @staticmethod
    def _phone_param_name(phone_field):
        return phone_field.removesuffix("_ids")

    def create_record(self, request, model_sudo, values, custom, meta=None):
        is_lead_model = model_sudo.model == "crm.lead"
        if is_lead_model:
            for phone_field in model_sudo._get_phone_number_fields():
                number = request.env.context.get(f"website_form_{phone_field}")
                if number:
                    values[phone_field] = [
                        Command.create({"number": number, "type": "landline"})
                    ]
            values_email_normalized = tools.email_normalize(values.get("email_from"))
            visitor_sudo = request.env["website.visitor"]._get_visitor_from_request(
                force_create=True
            )
            visitor_partner = visitor_sudo.partner_id
            if (
                values_email_normalized
                and visitor_partner
                and visitor_partner.email_normalized == values_email_normalized
            ):
                values_phone = request.env.context.get("website_form_phone_ids")
                if values_phone and visitor_partner.phone_ids:
                    sanitized = request.env["phone.number"]._sanitize_number(
                        values_phone, visitor_partner.country_id
                    )
                    if sanitized in visitor_partner.phone_ids.mapped("sanitized"):
                        values["partner_id"] = visitor_partner.id
                else:
                    values["partner_id"] = visitor_partner.id
            if "company_id" not in values:
                values["company_id"] = request.website.company_id.id
            lang = request.env.context.get("lang", False)
            values["lang_id"] = (
                values.get("lang_id") or request.env["res.lang"]._get_data(code=lang).id
            )

        result = super().create_record(request, model_sudo, values, custom, meta=meta)

        if is_lead_model and visitor_sudo and result:
            lead_sudo = request.env["crm.lead"].browse(result).sudo()
            if lead_sudo.exists():
                vals = {"lead_ids": [(4, result)]}
                if not visitor_sudo.lead_ids and not visitor_sudo.partner_id:
                    vals["name"] = lead_sudo.contact_name
                visitor_sudo.write(vals)
        return result
