from odoo import api, models

from ..tools import debug_log as dbg
from .hr_employee import _ALLOW_READ_HR_EMPLOYEE


class MixinHr(models.AbstractModel):
    _name = _description = "mixin.hr"

    @api.model_create_multi
    def create(self, vals_list):
        dbg.lifecycle.debug(
            "mixin.hr.create on %s: %d vals with employee read allowance",
            self._name,
            len(vals_list),
        )
        special_self = self.with_context(
            _allow_read_hr_employee=_ALLOW_READ_HR_EMPLOYEE
        )
        records = super(MixinHr, special_self).create(vals_list)
        return records.with_env(self.env)

    def write(self, vals):
        dbg.lifecycle.debug(
            "mixin.hr.write on %s: keys=%s with employee read allowance",
            dbg.rec(self),
            dbg.keys(vals),
        )
        special_self = self.with_context(
            _allow_read_hr_employee=_ALLOW_READ_HR_EMPLOYEE
        )
        return super(MixinHr, special_self).write(vals)
