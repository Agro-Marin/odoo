# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class UomUom(models.Model):
    _inherit = "uom.uom"

    def _unprotected_uom_xml_ids(self):
        # When the Timesheets app is installed the Hours UoM becomes master
        # data, so it must drop out of the unprotected list.
        #
        # Call super and filter, rather than returning a literal: a hardcoded
        # list silently discards anything `uom` adds later, and makes the
        # result depend on MRO order when another module (sale_planning) does
        # the same for the same unit.
        return [
            xml_id
            for xml_id in super()._unprotected_uom_xml_ids()
            if xml_id != "product_uom_hour"
        ]

    # widget used in the webclient when this unit is the one used to encode timesheets.
    timesheet_widget = fields.Char("Widget", export_string_translation=False)
