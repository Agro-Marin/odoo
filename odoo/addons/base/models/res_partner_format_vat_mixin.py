from typing import Any

from lxml import etree

from odoo import api, models


class FormatVatLabelMixin(models.AbstractModel):
    _name = "format.vat.label.mixin"
    _description = "Country Specific VAT Label"

    @api.model
    def _get_view_cache_key(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple:
        """Key the view cache on the company country's ``vat_label``.

        ``_get_view`` relabels the ``vat`` field from that value, so the cache
        keys on the value (not company identity): it dedupes companies sharing a
        label and refreshes when the country or its label changes. Mirrors
        ``format.address.mixin._get_view_cache_key``.
        """
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (self.env.company.country_id.vat_label,)

    @api.model
    def _get_view(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple[etree._Element, Any]:
        """Relabel the vat field/label to the company country's vat_label."""
        arch, view = super()._get_view(view_id, view_type, **options)
        if vat_label := self.env.company.country_id.vat_label:
            for node in arch.iterfind(".//field[@name='vat']"):
                node.set("string", vat_label)
            # Some modules replace the vat field, so also relabel its standalone label
            for node in arch.iterfind(".//label[@for='vat']"):
                node.set("string", vat_label)
        return arch, view
