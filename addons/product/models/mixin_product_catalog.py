from odoo import api, models
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog
from odoo.tools.misc import clean_context

_debug = DebugLog(__name__)


class MixinProductCatalog(models.AbstractModel):
    _name = "mixin.product.catalog"
    _description = "Product Catalog Mixin"

    @api.readonly
    def action_add_from_catalog(self):
        self.check_singleton()
        kanban_view_id = self.env.ref("product.view_product_product_kanban_catalog").id
        search_view_id = self.env.ref("product.view_product_product_search_catalog").id
        additional_context = self._prepare_catalog_extra_context()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Products"),
            "res_model": "product.product",
            "views": [(kanban_view_id, "kanban"), (False, "form")],
            "search_view_id": [search_view_id, "search"],
            "domain": self._get_domain_product_catalog(),
            "context": {**self._prepare_catalog_action_context(), **additional_context},
        }

    def _prepare_catalog_action_context(self):
        return clean_context(self.env.context)

    def _get_order_line_values(self, child_field=False):
        return {
            "quantity": 0,
            "readOnly": self._is_readonly() if self else False,
        }

    def _get_domain_product_catalog(self) -> Domain:
        return (
            Domain("company_id", "=", False)
            | Domain("company_id", "parent_of", self.company_id.id)
        ) & Domain("type", "!=", "combo")

    def _get_product_catalog_record_lines(self, product_ids, **kwargs):
        return {}

    def _get_product_catalog_order_data(self, products, **kwargs):
        return {
            product.id: {
                "productType": product.type,
                "uomDisplayName": product.uom_id.display_name,
                "code": product.code or "",
            }
            for product in products
        }

    def _get_product_catalog_order_line_info(
        self, product_ids, child_field=False, **kwargs
    ):
        order_line_info = {}

        for product, record_lines in self._get_product_catalog_record_lines(
            product_ids, child_field=child_field, **kwargs
        ).items():
            order_line_info[product.id] = {
                **record_lines._get_product_catalog_lines_data(
                    parent_record=self, **kwargs
                ),
                "productType": product.type,
                "code": product.code or "",
            }
            if not order_line_info[product.id].get("uomDisplayName"):
                order_line_info[product.id]["uomDisplayName"] = (
                    product.uom_id.display_name
                )

        default_data = self._get_order_line_values(child_field)
        products = self.env["product.product"].browse(product_ids)
        product_data = self._get_product_catalog_order_data(products, **kwargs)

        for product_id, data in product_data.items():
            if product_id in order_line_info:
                continue
            order_line_info[product_id] = {**default_data, **data}

        return order_line_info

    def _prepare_catalog_extra_context(self):
        return {
            "display_uom": self.env.user.has_group("uom.group_uom"),
            "order_id": self.id,
            "product_catalog_order_model": self._name,
        }

    def _is_readonly(self):
        return False

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        return 0

    @_debug.perf.timed
    def _create_section(self, child_field, name, position, **kwargs):
        parent_field = self._get_parent_field_on_child_model()

        if _debug.logic.enabled and not parent_field:
            _debug.logic("section_create_skipped", reason="no_parent_field")
        if not parent_field:
            return {}

        lines = self[child_field].sorted("sequence")
        line_model = lines._name
        sequence = 10
        if lines:
            sequence = (
                lines[0].sequence - 1 if position == "top" else lines[-1].sequence + 1
            )

        section = self.env[line_model].create(
            {
                parent_field: self.id,
                "name": name,
                "display_type": "line_section",
                "sequence": sequence,
                **self._prepare_default_create_section_values(),
            }
        )

        _debug.pipeline(
            "section_created",
            records=self,
            section=section,
            position=position,
            sequence=sequence,
        )
        return {
            "id": section.id,
            "sequence": section.sequence,
        }

    def _get_new_line_sequence(self, child_field, section_id):
        lines = self[child_field].sorted("sequence")

        sequence = (lines and lines[-1].sequence + 1) or 10
        if section_id:
            section_found = False
            for line in lines:
                if line.display_type != "line_section":
                    continue
                if section_found:
                    sequence = line.sequence
                    break
                if line.id == section_id:
                    section_found = True
        elif section_lines := lines.filtered_domain(
            [
                ("display_type", "=", "line_section"),
            ]
        ):
            sequence = section_lines[0].sequence

        _debug.logic(
            "line_sequence_chosen",
            section=section_id,
            sequence=sequence,
            lines=len(lines),
        )
        for line in lines.filtered_domain([("sequence", ">=", sequence)]):
            line.sequence += 1

        return sequence

    def _get_sections(self, child_field, **kwargs):
        sections = {}
        no_section_count = 0
        lines = self[child_field]
        for line in lines.sorted("sequence"):
            if line.display_type == "line_section":
                sections[line.id] = {
                    "id": line.id,
                    "name": line.name,
                    "sequence": line.sequence,
                    "line_count": 0,
                }
            elif self._is_line_valid_for_section_line_count(line):
                sec_id = line.get_line_parent_section().id
                if sec_id and sec_id in sections:
                    sections[sec_id]["line_count"] += 1
                else:
                    no_section_count += 1

        if no_section_count > 0 or not sections:
            sections[False] = {
                "id": False,
                "name": self.env._("No Section"),
                "sequence": lines[0].sequence - 1 if lines else 0,
                "line_count": no_section_count,
            }

        _debug.pipeline(
            "sections_collected",
            sections=len(sections),
            unsectioned=no_section_count,
        )
        return sorted(sections.values(), key=lambda x: x["sequence"])

    def _prepare_default_create_section_values(self):
        return {}

    def _get_parent_field_on_child_model(self):
        return ""

    def _is_line_valid_for_section_line_count(self, line):
        return (
            not line.display_type
            and line.product_type != "combo"
            and line.product_uom_qty > 0
        )

    @_debug.perf.timed
    def _resequence_sections(self, sections, child_field, **kwargs):
        lines = self[child_field].sorted("sequence")
        move_section, target_section = sections

        move_block = lines.filtered(
            lambda line: (
                line.id == move_section["id"]
                or line.get_line_parent_section().id == move_section["id"]
            ),
        )

        target_block = lines.filtered(
            lambda line: (
                line.id == target_section["id"]
                or line.get_line_parent_section().id == target_section["id"]
            ),
        )

        remaining_lines = lines - move_block
        insert_after = move_section["sequence"] < target_section["sequence"]
        insert_index = len(remaining_lines)
        for idx, line in enumerate(remaining_lines):
            if line.id == (
                target_block[-1].id if insert_after else target_section["id"]
            ):
                insert_index = idx + 1 if insert_after else idx
                break

        reordered_lines = (
            remaining_lines[:insert_index] + move_block + remaining_lines[insert_index:]
        )
        _debug.logic(
            "section_insert_position",
            document=self,
            move_section=move_section.get("id"),
            target_section=target_section.get("id"),
            insert_after=insert_after,
            insert_index=insert_index,
            moved_lines=len(move_block),
            remaining_lines=len(remaining_lines),
        )

        sections = {}
        for sequence, line in enumerate(reordered_lines, start=1):
            line.sequence = sequence
            if line.display_type == "line_section":
                sections[line.id] = sequence

        _debug.pipeline(
            "sections_resequenced",
            document=self,
            lines=len(reordered_lines),
            sections=len(sections),
        )
        return sections
