from odoo import api, models


class MixinDefaultReadFields(models.AbstractModel):
    _name = "mixin.default.read.fields"
    _description = "Default read field set"

    _UNREADABLE_BY_DEFAULT = frozenset()

    @api.model
    def _is_readable_by_default(self, field):
        return field.exportable and field.name not in self._UNREADABLE_BY_DEFAULT

    @api.model
    @api.deprecated("Override of a deprecated method")
    def check_field_access_rights(self, operation, field_names):
        result = super().check_field_access_rights(operation, field_names)
        if not field_names:
            model_fields = self._fields
            result = [
                fname
                for fname in result
                if self._is_readable_by_default(model_fields[fname])
            ]
        return result

    @api.model
    def _get_fields_default_read(self):
        model_fields = self._fields
        return [
            fname
            for fname in self.fields_get(attributes=())
            if self._is_readable_by_default(model_fields[fname])
        ]

    def read(self, fields=None, load="_classic_read"):
        if not fields:
            fields = self._get_fields_default_read()
        return super().read(fields, load)

    @api.model
    def search_read(
        self, domain=None, fields=None, offset=0, limit=None, order=None, **read_kwargs
    ):
        if not fields:
            fields = self._get_fields_default_read()
        return super().search_read(domain, fields, offset, limit, order, **read_kwargs)
