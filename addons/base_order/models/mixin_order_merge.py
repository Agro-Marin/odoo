from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError

DATE_MATCH_THRESHOLD_SECONDS = 86400


class MixinOrderMerge(models.AbstractModel):
    _name = "mixin.order.merge"
    _description = "Order Merge System"

    def action_merge(self):
        orders_to_merge = self._merge_get_eligible_orders()
        self._merge_validate_selection(orders_to_merge)

        groups = self._merge_group_orders(orders_to_merge)
        self._merge_validate_groups(groups)

        merged_ids = []
        for orders in groups:
            if len(orders) > 1:
                merged_id = self._merge_order_group(orders)
                merged_ids.append(merged_id)

        return self._merge_build_result_action(merged_ids)

    def _merge_get_eligible_orders(self):
        return self.filtered(lambda r: r.state == "draft")

    def _merge_validate_selection(self, orders):
        if len(orders) < 2:
            raise UserError(
                _("Please select at least two orders to merge."),
            )

    def _merge_validate_groups(self, groups):
        if not groups:
            raise UserError(
                _(
                    "No compatible orders to merge. Orders must have the same:\n%s",
                    self._get_merge_group_description(),
                ),
            )

    def _get_merge_group_description(self):
        return _("- Partner\n- Currency")

    def _merge_group_orders(self, orders):
        groups = defaultdict(lambda: self.env[self._name])
        for order in orders:
            key = self._prepare_grouped_data(order)
            groups[key] += order
        return [g for g in groups.values() if len(g) > 1]

    def _prepare_grouped_data(self, order):
        return (
            order.partner_id.id,
            order.currency_id.id,
        )

    def _merge_get_target(self, orders):
        return min(orders, key=lambda r: r.date_order)

    def _merge_order_group(self, orders):
        target = self._merge_get_target(orders)
        sources = orders - target

        line_index = self._merge_build_line_index(target)
        self._merge_lines(target, sources, line_index)
        self._merge_metadata(target, sources)
        self._merge_post_messages(target, sources)
        self._merge_finalize(target, sources)

        return target.id

    def _merge_build_line_index(self, target):
        index = defaultdict(list)
        for line in target.line_ids:
            if line.display_type:
                continue
            key = self._merge_get_line_key(line)
            index[key].append(line)
        return index

    def _merge_get_line_key(self, line):
        return (
            line.product_id.id,
            line.product_uom_id.id,
            frozenset(line.analytic_distribution.items())
            if line.analytic_distribution
            else frozenset(),
            line.discount,
            line.price_unit,
            frozenset(line.tax_ids.ids),
        )

    def _merge_lines(self, target, sources, line_index):
        for source_line in sources.line_ids:
            if source_line.display_type:
                source_line.order_id = target
                continue

            key = self._merge_get_line_key(source_line)
            match = self._merge_find_matching_line(
                source_line,
                line_index.get(key, []),
            )

            if match:
                match._merge_order_line(source_line)
            else:
                source_line.order_id = target
                line_index[key].append(source_line)

    def _merge_find_matching_line(self, source_line, candidates):
        line_model = f"{self._name}.line"
        matches = self.env[line_model]

        for candidate in candidates:
            if self._merge_lines_match_date(candidate, source_line):
                matches |= candidate

        if len(matches) > 1:
            matches[0].product_qty += sum(matches[1:].mapped("product_qty"))
            matches[1:].unlink()
            return matches[0]

        return matches[:1]

    def _merge_lines_match_date(self, line1, line2):
        field_name = line1._get_merge_date_field()
        if not field_name:
            return True
        date1 = line1[field_name]
        date2 = line2[field_name]
        if not date1 or not date2:
            return not date1 and not date2
        delta = abs(date1 - date2).total_seconds()
        return delta <= DATE_MATCH_THRESHOLD_SECONDS

    def _merge_metadata(self, target, sources):
        all_origins = [target.origin] + list(sources.mapped("origin"))
        target.origin = ", ".join(filter(None, all_origins))
        self._merge_metadata_refs(target, sources)

    def _merge_metadata_refs(self, target, sources):
        all_refs = [target.partner_ref] + list(sources.mapped("partner_ref"))
        target.partner_ref = ", ".join(filter(None, all_refs))

    def _merge_post_messages(self, target, sources):
        source_names = ", ".join(sources.mapped("name"))
        target.message_post(
            body=_("Merged with: %(sources)s", sources=source_names),
        )
        target_link = target._get_html_link()
        for source in sources:
            source.message_post(
                body=_("Merged into %s", target_link),
            )

    def _merge_finalize(self, target, sources):
        sources.filtered(lambda r: r.state != "cancel").action_cancel()

    def _merge_build_result_action(self, merged_ids):
        action = {
            "type": "ir.actions.act_window",
            "res_model": self._name,
        }
        if len(merged_ids) == 1:
            action["res_id"] = merged_ids[0]
            action["view_mode"] = "form"
        else:
            action["name"] = self._get_merge_result_name()
            action["view_mode"] = "list,kanban,form"
            action["domain"] = [("id", "in", merged_ids)]
        return action

    def _get_merge_result_name(self):
        return _("Merged Orders")
