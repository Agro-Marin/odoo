import json

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL

_debug = DebugLog(__name__)


class MixinAccountMerge(models.AbstractModel):
    _name = "mixin.account.merge"
    _inherit = ["mixin.merge"]
    _description = "Accounting Merge Wizard Mixin"

    _merge_model = None
    _merge_records_field = None

    disable_merge_button = fields.Boolean(compute="_compute_disable_merge_button")

    @api.model
    @_debug.perf.timed
    def default_get(self, fields):
        _debug.lifecycle("default_get", records=self)
        res = super().default_get(fields)
        requested = {self._merge_records_field, "wizard_line_ids"}
        if not set(fields) & requested or set(res) & requested:
            _debug.logic(
                "merge_defaults_skipped", reason="records_not_requested_or_set"
            )
            return res

        active_model = self.env.context.get("active_model")
        if active_model != self._merge_model:
            _debug.logic(
                "merge_defaults_rejected",
                reason="wrong_model",
                active_model=active_model,
            )
            raise UserError(self._get_merge_messages()["wrong_model"])
        if len(self.env.context.get("active_ids") or []) < 2:
            _debug.logic("merge_defaults_rejected", reason="fewer_than_two_records")
            raise UserError(self._get_merge_messages()["too_few"])

        res[self._merge_records_field] = [
            Command.set(self.env.context.get("active_ids"))
        ]
        return res

    def _get_merge_messages(self):
        raise NotImplementedError

    def _get_grouping_key(self, record):
        raise NotImplementedError

    def _get_mergeable_records(self):
        self.check_singleton()
        return self[self._merge_records_field]._origin

    @_debug.perf.timed
    def _compute_wizard_line_ids(self):
        for wizard in self:
            Line = wizard.wizard_line_ids
            records = wizard._get_mergeable_records()
            vals_list = []
            sequence = 0
            for key, group in records.grouped(wizard._get_grouping_key).items():
                grouping_key = str(key)
                vals_list.append(
                    {
                        "display_type": "line_section",
                        "grouping_key": grouping_key,
                        "sequence": (sequence := sequence + 1),
                        Line._merge_record_field: group[0].id,
                    }
                )
                vals_list.extend(
                    {
                        "display_type": Line._merge_record_display_type,
                        "grouping_key": grouping_key,
                        "is_selected": True,
                        "sequence": (sequence := sequence + 1),
                        Line._merge_record_field: record.id,
                    }
                    for record in group
                )
            _debug.pipeline(
                "merge_groups_built",
                wizard=wizard,
                records=len(records),
                wizard_lines=len(vals_list),
            )
            wizard.wizard_line_ids = [Command.clear()] + [
                Command.create(vals) for vals in vals_list
            ]

    @api.depends("wizard_line_ids.is_selected", "wizard_line_ids.info")
    def _compute_disable_merge_button(self):
        for wizard in self:
            wizard.disable_merge_button = all(
                len(group) < 2
                for group in wizard.wizard_line_ids._get_mergeable_groups()
            )

    @_debug.perf.timed
    def action_merge(self):
        _debug.lifecycle("action_merge", records=self)
        for wizard in self:
            Line = wizard.wizard_line_ids
            for group in Line._get_mergeable_groups():
                if len(group) > 1:
                    self._action_merge(
                        group.sorted(Line._merge_record_hashed_field, reverse=True)[
                            Line._merge_record_field
                        ]
                    )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "sticky": False,
                "message": self._get_merge_messages()["merged"],
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.model
    @_debug.perf.timed
    def _check_access_rights(self, records):
        records.check_access("write")
        if forbidden_companies := (
            records.sudo().company_ids - self.env.user.company_ids
        ):
            raise UserError(
                self.env._(
                    "You do not have the right to perform this operation as you do not have access to the following companies: %s.",
                    ", ".join(company.name for company in forbidden_companies),
                )
            )

    @api.model
    @_debug.perf.timed
    def _action_merge(self, records):
        _debug.lifecycle("_action_merge", records=self)
        record_to_merge_into = records[0]
        records_to_remove = records[1:]
        companies = records.sudo().company_ids
        _debug.pipeline(
            "merge_planned",
            model=self._merge_model,
            destination=record_to_merge_into,
            removed=records_to_remove,
            companies=companies,
        )

        self._check_access_rights(records)
        prepared = self._prepare_merge(records)
        self._update_foreign_keys_generic(
            self._merge_model, records_to_remove, record_to_merge_into
        )
        self._update_reference_fields_generic(
            self._merge_model, records_to_remove, record_to_merge_into
        )
        self._merge_translated_names(records)
        self._delete_merged_records(records_to_remove)
        self._finalize_merge(record_to_merge_into, companies, prepared)

    @api.model
    def _prepare_merge(self, records):
        return None

    @api.model
    def _merge_translated_names(self, records):
        table = SQL.identifier(records._table)
        name_by_id = dict(
            self.env.execute_query(
                SQL(
                    "SELECT id, name FROM %(table)s WHERE id IN %(ids)s",
                    table=table,
                    ids=tuple(records.ids),
                )
            )
        )
        _debug.perf.count("merged_names_fetched", rows=len(name_by_id))
        merged_name = {}
        for record_id in reversed(records.ids):
            merged_name.update(name_by_id[record_id] or {})
        self.env.cr.execute(
            SQL(
                "UPDATE %(table)s SET name = %(name)s WHERE id = %(id)s",
                table=table,
                name=json.dumps(merged_name),
                id=records[0].id,
            )
        )
        _debug.perf.count("merged_name_written", rows=self.env.cr.rowcount)

    @api.model
    def _delete_merged_records(self, records):
        self.env.invalidate_all()
        self.env.cr.execute(
            SQL(
                "DELETE FROM %(table)s WHERE id IN %(ids)s",
                table=SQL.identifier(records._table),
                ids=tuple(records.ids),
            )
        )
        _debug.perf.count("merged_records_deleted", rows=self.env.cr.rowcount)
        self.env.registry.clear_cache()

    @api.model
    def _finalize_merge(self, record, companies, prepared):
        record.sudo().company_ids = companies


class MixinAccountMergeLine(models.AbstractModel):
    _name = "mixin.account.merge.line"
    _description = "Accounting Merge Wizard Line Mixin"

    _merge_record_field = None
    _merge_record_display_type = None
    _merge_record_hashed_field = None

    grouping_key = fields.Char()
    sequence = fields.Integer()
    is_selected = fields.Boolean()
    info = fields.Char(
        compute="_compute_info",
        help="Contains either the section name or error message, depending on the line type.",
    )

    def _get_merge_record(self):
        return self[self._merge_record_field]

    def _get_merge_section_name(self):
        raise NotImplementedError

    def _get_mergeable_groups(self):
        return (
            self.filtered(
                lambda line: (
                    line.display_type == self._merge_record_display_type
                    and line.is_selected
                    and not line.info
                )
            )
            .grouped("grouping_key")
            .values()
        )

    def _compute_info(self):
        for line in self.filtered(lambda l: l.display_type == "line_section"):
            line.info = line._get_merge_section_name()
        for group in (
            self.filtered(lambda l: l.display_type == self._merge_record_display_type)
            .grouped(lambda l: (l.wizard_id, l.grouping_key))
            .values()
        ):
            group.info = False
            group._update_info_conflicts()

    def _update_info_conflicts(self):
        self._update_info_company_conflict()
        self._update_info_hashed_moves_conflict()

    def _update_info_company_conflict(self):
        companies_seen = self.env["res.company"]
        owner_by_company = {}
        for line in self:
            if not line.is_selected or line.info:
                continue
            if shared_companies := (line.company_ids & companies_seen):
                _debug.logic(
                    "merge_company_conflict",
                    wizard_line=line,
                    companies=shared_companies,
                )
                line.info = self.env._(
                    "Belongs to the same company as %s.",
                    owner_by_company[shared_companies[0]].display_name,
                )
            else:
                companies_seen |= line.company_ids
                for company in line.company_ids:
                    owner_by_company.setdefault(company, line._get_merge_record())

    def _update_info_hashed_moves_conflict(self):
        record_to_merge_into = None
        for line in self:
            if (
                not line.is_selected
                or line.info
                or not line[self._merge_record_hashed_field]
            ):
                continue
            if record_to_merge_into is None:
                record_to_merge_into = line._get_merge_record()
            else:
                line.info = self.env._(
                    "Contains hashed entries, but %s also has hashed entries.",
                    record_to_merge_into.display_name,
                )
