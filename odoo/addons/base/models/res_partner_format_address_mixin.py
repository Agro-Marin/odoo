import copy
from typing import Any

from lxml import etree

from odoo import api, models

ADDRESS_FIELDS = ("street", "street2", "zip", "city", "state_id", "country_id")


class FormatAddressMixin(models.AbstractModel):
    _name = "format.address.mixin"
    _description = "Address Format"

    def _extract_fields_from_address(self, address_line: str) -> list[str]:
        """Return the address field keys found in a single ``address_format``
        line, ordered by first occurrence.

        :param str address_line: e.g. ``"zip: %(zip)s, city: %(city)s."`` yields
            ``['zip', 'city']``
        :rtype: list[str]
        """
        address_fields = [
            "%(" + field + ")s"
            for field in ADDRESS_FIELDS + ("state_code", "state_name")
        ]
        # Sort by first position in the line; real ``address_format`` lines do
        # not repeat placeholders.
        return sorted(
            [field[2:-2] for field in address_fields if field in address_line],
            key=lambda field: address_line.index("%(" + field + ")s"),
        )

    def _view_get_address(self, arch: etree._Element) -> etree._Element:
        """Rewrite ``arch`` in place to follow the company country's address
        layout, and return it.

        Either swap in the country's ``address_view_id`` arch when set, else
        reorder zip/city/state fields per the country ``address_format``.
        """
        # consider the country of the user, not the country of the partner we want to display
        address_view_id = self.env.company.country_id.address_view_id.sudo()
        address_format = self.env.company.country_id.address_format
        if (
            address_view_id
            and not self.env.context.get("no_address_format")
            and (not address_view_id.model or address_view_id.model == self._name)
        ):
            # render the partner address accordingly to address_view_id
            address_nodes = arch.xpath("//div[hasclass('o_address_format')]")
            if address_nodes:
                # Fetch and validate the sub-view ONCE, before touching arch: a
                # per-node bail-out could return a half-rewritten view.
                Partner = self.env["res.partner"].with_context(no_address_format=True)
                sub_arch, _sub_view = Partner._get_view(address_view_id.id, "form")
                # On a non-partner model the sub-view may not apply (e.g. missing
                # fields); return arch unchanged in that case.
                if self._name != "res.partner":
                    try:
                        self.env["ir.ui.view"].postprocess_and_fields(
                            sub_arch, model=self._name
                        )
                    except ValueError:
                        return arch
                for address_node in address_nodes:
                    # Deep-copy per node: an lxml element lives at a single spot
                    # in a tree, so reusing it would move it instead of copying.
                    node_arch = copy.deepcopy(sub_arch)
                    new_address_node = node_arch.find(
                        './/div[@class="o_address_format"]'
                    )
                    # Prefer the inner address div if present, else the whole sub-view.
                    replacement = (
                        new_address_node if new_address_node is not None else node_arch
                    )
                    address_node.getparent().replace(address_node, replacement)
        elif address_format and not self.env.context.get("no_address_format"):
            # Reorder the zip/city/state fields to follow the country's format.
            city_line = [
                self._extract_fields_from_address(line)
                for line in address_format.split("\n")
                if "city" in line
            ]
            if city_line:
                # Only the first city-bearing line drives ordering.
                # state_code/state_name both normalize to state_id.
                field_order = city_line[0]
                for address_node in arch.xpath("//div[hasclass('o_address_format')]"):
                    first_field = (
                        field_order[0]
                        if field_order[0] not in ("state_code", "state_name")
                        else "state_id"
                    )
                    concerned_fields = ["zip", "city", "state_id"]
                    concerned_fields = [f for f in concerned_fields if f != first_field]
                    current_field = address_node.find(
                        f".//field[@name='{first_field}']"
                    )
                    # Order the fields present in address_format.
                    for field in field_order[1:]:
                        if field in ("state_code", "state_name"):
                            field = "state_id"
                        previous_field = current_field
                        current_field = address_node.find(f".//field[@name='{field}']")
                        if previous_field is not None and current_field is not None:
                            previous_field.addnext(current_field)
                        if field in concerned_fields:
                            concerned_fields.remove(field)
                    # Append any concerned fields not already placed.
                    for field in concerned_fields:
                        previous_field = current_field
                        current_field = address_node.find(f".//field[@name='{field}']")
                        if previous_field is not None and current_field is not None:
                            previous_field.addnext(current_field)

        return arch

    @api.model
    def _get_view_cache_key(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple:
        """Key the view cache on the address-layout inputs of _view_get_address.

        Keying on the country's ``address_view_id``/``address_format`` VALUES
        (not the company identity) both dedupes across same-country companies
        and stays fresh when those fields change, with no explicit invalidation.
        """
        key = super()._get_view_cache_key(view_id, view_type, **options)
        country = self.env.company.country_id
        return key + (
            country.address_view_id.id,
            country.address_format,
            self.env.context.get("no_address_format"),
        )

    @api.model
    def _get_view(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple[etree._Element, Any]:
        arch, view = super()._get_view(view_id, view_type, **options)
        if view.type == "form":
            arch = self._view_get_address(arch)
        return arch, view
