from odoo import api, models


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    @api.readonly
    def hierarchy_read(
        self,
        domain,
        specification,
        parent_field,
        child_field=None,
        order=None,
        only_roots=False,
    ):
        specification = dict(specification)
        specification.setdefault(parent_field, {"fields": {"display_name": {}}})
        records = self.search(
            [(parent_field, "=", False), *domain] if only_roots else domain, order=order
        )
        if not records and only_roots:
            records = self.search(domain, order=order)
        if not records:
            return []

        if len(records) == 1:
            records = self._hierarchy_expand_focused_record(
                records, parent_field, order
            )
            records_needing_child_ids = records - records[parent_field]
        else:
            records_needing_child_ids = records

        result = records.web_read(specification)
        if not child_field:
            child_ids_per_record_id = {
                record.id: child_ids
                for record, child_ids in self._read_group(
                    [(parent_field, "in", records_needing_child_ids.ids)],
                    (parent_field,),
                    ("id:array_agg",),
                )
            }
            for record_data in result:
                if record_data["id"] in child_ids_per_record_id:
                    record_data["__child_ids__"] = child_ids_per_record_id[
                        record_data["id"]
                    ]
        return result

    def _hierarchy_expand_focused_record(self, record, parent_field, order):
        if not record[parent_field]:
            branch_domain = [(parent_field, "=", record.id), ("id", "!=", record.id)]
        else:
            parent_id = record[parent_field].id
            branch_domain = [
                "&",
                ("id", "!=", record.id),
                "|",
                ("id", "=", parent_id),
                (parent_field, "in", [parent_id, record.id]),
            ]
        return record + self.search(branch_domain, order=order)
