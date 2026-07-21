
from odoo import api, fields, models


class BarcodesBarcode_Events_Mixin(models.AbstractModel):
    """Mixin for models that react to a barcode scanned in their form view."""

    # The form view must contain
    # `<field name="_barcode_scanned" widget="barcode_handler"/>`. Models using
    # this mixin must implement `on_barcode_scanned`: it works like an onchange
    # and receives the scanned barcode as parameter.
    _name = 'barcodes.barcode_events_mixin'
    _description = 'Barcode Event Mixin'

    _barcode_scanned = fields.Char("Barcode Scanned", help="Value of the last barcode scanned.", store=False)

    @api.onchange('_barcode_scanned')
    def _on_barcode_scanned(self):
        barcode = self._barcode_scanned
        if barcode:
            self._barcode_scanned = ""
            return self.on_barcode_scanned(barcode)
        return None

    def on_barcode_scanned(self, barcode):
        raise NotImplementedError(self.env._("In order to use barcodes.barcode_events_mixin, method on_barcode_scanned must be implemented"))
