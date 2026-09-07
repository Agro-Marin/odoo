from odoo import Command, api, exceptions, models

from odoo.addons.phone_validation.tools import phone_validation


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    def _get_phone_number_fields(self):
        return [
            fname
            for fname in ("phone_ids",)
            if fname in self._fields
            and self._fields[fname].type == "many2many"
            and self._fields[fname].comodel_name == "phone.number"
        ]

    def _phone_get_numbers(self, fname=False):
        self.check_singleton()
        numbers = self.env["phone.number"]
        for field_name in [fname] if fname else self._get_phone_number_fields():
            if field_name in self._fields:
                numbers |= self[field_name]
        return numbers

    def _phone_get_number(self, *types, fname=False):
        return self._phone_get_numbers(fname=fname)._primary(*types)

    def _phone_replace_number(self, fname, number, *types):
        self.check_singleton()
        old = self._phone_get_numbers(fname=fname)._primary(*types)
        commands = [Command.create({"number": number, "type": old.type or "mobile"})]
        if old:
            commands.insert(0, Command.unlink(old.id))
        self.write({fname: commands})

    def _phone_get_country(self):
        country_by_record = {}
        record_country_fname = self._phone_get_country_field()
        for record in self:
            if record_country_fname and (
                record_country := record[record_country_fname]
            ):
                country_by_record[record.id] = record_country
                continue
            for partner_field in self.env[self._name]._mail_get_partner_fields():
                partner_records = record[partner_field]
                if countries := partner_records.country_id:
                    country_by_record[record.id] = countries[0]
        return country_by_record

    @api.model
    def _phone_get_country_field(self):
        if "country_id" in self:
            return "country_id"
        return False

    def _phone_format(
        self,
        fname=False,
        number=False,
        country=False,
        force_format="E164",
        raise_exception=False,
    ):
        if not number:
            self.check_singleton()
            phone = self._phone_get_number(fname=fname)
            number = phone.number
            if phone.country_id and not country:
                country = phone.country_id
        if not number:
            return False

        if not country and self:
            self.check_singleton()
            country = self._phone_get_country().get(self.id)
        if not country:
            country = self.env.company.country_id

        return self._phone_format_number(
            number,
            country=country,
            force_format=force_format,
            raise_exception=raise_exception,
        )

    def _phone_format_number(
        self, number, country, force_format="E164", raise_exception=False
    ):
        if not number:
            return False

        try:
            number = phone_validation.phone_format(
                number,
                country.code,
                country.phone_code,
                force_format=force_format,
                raise_exception=True,
            )
        except exceptions.UserError:
            if raise_exception:
                raise
            number = False
        return number
