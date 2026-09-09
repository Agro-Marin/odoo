from odoo import api, models


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    @api.readonly
    def hierarchy_read(
        self, domain, specification, parent_field, child_field=None, order=None
    ):
        """Read the records matching ``domain`` together with what the hierarchy
        view needs to know about their place in the tree.

        When ``child_field`` is given, the children travel in that one2many and
        this method only adds ``parent_field`` to the specification. Otherwise
        the ids of each record's children are aggregated into ``__child_ids__``,
        so that a record can advertise children it does not carry.

        A domain matching exactly one record is the "focus on this record" case:
        its parent and its siblings are returned along with it, so that the view
        has a branch to draw rather than a lone card.
        """
        specification = dict(specification)
        specification.setdefault(parent_field, {"fields": {"display_name": {}}})
        records = self.search(domain, order=order)
        if not records:
            return []

        if len(records) == 1:
            records = self._hierarchy_expand_focused_record(
                records, parent_field, order
            )
            # Records that are the parent of another record in the set already
            # display their children, so they need no child ids.
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
        """Return ``record`` with the branch it sits on.

        With a parent, that is the parent plus the children of both, so the view
        draws ``record`` among its siblings under its own manager. Without one,
        ``record`` is already a root and only its children are missing.
        """
        if record[parent_field]:
            record += record[parent_field]
            siblings_domain = [
                ("id", "not in", record.ids),
                (parent_field, "in", record.ids),
            ]
        else:
            siblings_domain = [(parent_field, "=", record.id), ("id", "!=", record.id)]
        return record + self.search(siblings_domain, order=order)
