from odoo import api, models

MEMBERSHIP_MULTI_KEY = "sales_team.membership_multi"
MEMBERSHIP_MULTI_FIELD = "is_membership_multi"


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    def _invalidate_membership_multi(self, keys):
        if MEMBERSHIP_MULTI_KEY not in keys:
            return
        for model_name, model in self.env.registry.items():
            field = model._fields.get(MEMBERSHIP_MULTI_FIELD)
            if field is not None and field.compute and not field.store:
                self.env[model_name].invalidate_model([MEMBERSHIP_MULTI_FIELD])

    @api.model_create_multi
    def create(self, vals_list):
        params = super().create(vals_list)
        params._invalidate_membership_multi(params.mapped("key"))
        return params

    def write(self, vals):
        keys = set(self.mapped("key"))
        res = super().write(vals)
        self._invalidate_membership_multi(keys | set(self.mapped("key")))
        return res

    def unlink(self):
        keys = self.mapped("key")
        res = super().unlink()
        self._invalidate_membership_multi(keys)
        return res
