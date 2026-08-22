# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class HrApplicantCategory(models.Model):
    _name = 'hr.applicant.category'
    _description = "Category of applicant"
    # `name` (translated, unique on the source term), `active`, `color` and
    # `code` come from the mixin, whose index replaces the `unique (name)`
    # constraint this model declared -- that one compared whole jsonb documents
    # once `name` became translatable. Flat: applicant tags do not nest.
    _inherit = ['mixin.tag']
