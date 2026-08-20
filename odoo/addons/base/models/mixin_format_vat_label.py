from typing import Any

from lxml import etree

from odoo import api, models


class MixinFormatVatLabel(models.AbstractModel):
    _name = "mixin.format.vat.label"
    _description = "Country Specific VAT Label"

    @api.model
    def _get_view_cache_key(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple:
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (self.env.company.country_id.vat_label,)

    @api.model
    def _get_view(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple[etree._Element, Any]:
        arch, view = super()._get_view(view_id, view_type, **options)
        if vat_label := self.env.company.country_id.vat_label:
            for node in arch.iterfind(".//field[@name='vat']"):
                node.set("string", vat_label)
            for node in arch.iterfind(".//label[@for='vat']"):
                node.set("string", vat_label)
        return arch, view
