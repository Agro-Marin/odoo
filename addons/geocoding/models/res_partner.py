from odoo import _, api, fields, models, modules

ADDRESS_FIELDS = ("street", "street2", "zip", "city", "state_id", "country_id")
COORDINATE_FIELDS = ("partner_latitude", "partner_longitude")


class ResPartner(models.Model):
    _inherit = "res.partner"

    date_localization = fields.Date(string="Geolocation Date")

    def write(self, vals):
        if self._is_geolocation_stale(vals):
            vals = dict(vals, partner_latitude=0.0, partner_longitude=0.0)
        return super().write(vals)

    def _is_geolocation_stale(self, vals):
        """Whether `vals` moves the address without supplying a new position.

        Both coordinates have to be supplied together: a write carrying only
        one of them describes no point, so the stored pair is dropped rather
        than left half-updated. A write restating the address a partner
        already has moves nothing and keeps its coordinates.
        """
        written_address_fields = [field for field in ADDRESS_FIELDS if field in vals]
        if not written_address_fields:
            return False
        if all(field in vals for field in COORDINATE_FIELDS):
            return False
        for partner in self:
            for field_name in written_address_fields:
                current = partner[field_name]
                if self._fields[field_name].type == "many2one":
                    current = current.id
                if (current or False) != (vals[field_name] or False):
                    return True
        return False

    @api.model
    def _geo_localize(self, street="", zip_code="", city="", state="", country=""):
        """Return (latitude, longitude) for the given address, or None if not found."""
        geo_obj = self.env["geocoder"]
        search = geo_obj.geo_query_address(
            street=street, zip_code=zip_code, city=city, state=state, country=country
        )
        result = geo_obj.geo_find(search, force_country=country)
        if result is None:
            search = geo_obj.geo_query_address(city=city, state=state, country=country)
            result = geo_obj.geo_find(search, force_country=country)
        return result

    def geo_localize(self):
        """Geolocate self's partners and notify the user of any that could not be matched."""
        # We need country names in English below
        if not self.env.context.get("force_geo_localize") and (
            self.env.context.get("import_file")
            or modules.module.current_test
            or not self.env.registry.ready
        ):
            return False
        partners_not_geo_localized = self.env["res.partner"]
        for partner in self.with_context(lang="en_US"):
            result = self._geo_localize(
                partner.street,
                partner.zip,
                partner.city,
                partner.state_id.name,
                partner.country_id.name,
            )

            if result:
                partner.write(
                    {
                        "partner_latitude": result[0],
                        "partner_longitude": result[1],
                        "date_localization": fields.Date.context_today(partner),
                    }
                )
            else:
                partners_not_geo_localized |= partner
        if partners_not_geo_localized:
            self.env.user._bus_send(
                "simple_notification",
                {
                    "type": "danger",
                    "title": _("Warning"),
                    "message": _(
                        "No match found for %(partner_names)s address(es).",
                        partner_names=", ".join(
                            partners_not_geo_localized.mapped("display_name")
                        ),
                    ),
                },
            )
        return True
