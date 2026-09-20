from odoo import api, models


class MixinDefaultReadFields(models.AbstractModel):
    _name = "mixin.default.read.fields"
    _description = "Default read field set"

    _UNREADABLE_BY_DEFAULT = frozenset()

    @api.model
    def _is_readable_by_default(self, field):
        return (
            field.exportable
            and field.name not in self._UNREADABLE_BY_DEFAULT
            and super()._is_readable_by_default(field)
        )
