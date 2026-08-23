import datetime
import logging
from ast import literal_eval
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import SQL

_logger = logging.getLogger("odoo.addons.base.partner.merge")


class BasePartnerMergeLine(models.TransientModel):
    _name = "base.partner.merge.line"

    _description = "Merge Partner Line"
    _order = "min_id asc"

    wizard_id = fields.Many2one("base.partner.merge.automatic.wizard", "Wizard")
    min_id = fields.Integer("MinID")
    aggr_ids = fields.Char("Ids", required=True)


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _name = "base.partner.merge.automatic.wizard"
    _inherit = ["mixin.merge"]
    _description = "Merge Partner Wizard"

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        res = super().default_get(fields)
        active_ids = self.env.context.get("active_ids")
        if self.env.context.get("active_model") == "res.partner" and active_ids:
            if "state" in fields:
                res["state"] = "selection"
            if "partner_ids" in fields:
                res["partner_ids"] = [Command.set(active_ids)]
            if "dst_partner_id" in fields:
                res["dst_partner_id"] = self._get_ordered_partner(active_ids)[-1].id
        return res

    group_by_email = fields.Boolean("Email")
    group_by_name = fields.Boolean("Name")
    group_by_is_company = fields.Boolean("Is Company")
    group_by_vat = fields.Boolean("VAT")
    group_by_parent_id = fields.Boolean("Parent Company")

    state = fields.Selection(
        [
            ("option", "Option"),
            ("selection", "Selection"),
            ("finished", "Finished"),
        ],
        readonly=True,
        required=True,
        string="State",
        default="option",
    )

    number_group = fields.Integer("Group of Contacts", readonly=True)
    current_line_id = fields.Many2one("base.partner.merge.line", string="Current Line")
    line_ids = fields.One2many("base.partner.merge.line", "wizard_id", string="Lines")
    partner_ids = fields.Many2many(
        "res.partner", string="Contacts", context={"active_test": False}
    )
    dst_partner_id = fields.Many2one("res.partner", string="Destination Contact")

    exclude_contact = fields.Boolean("A user associated to the contact")
    exclude_journal_item = fields.Boolean("Journal Items associated to the contact")
    maximum_group = fields.Integer("Maximum of Group of Contacts")
    absorb_source_values = fields.Boolean(
        "Absorb Source Values",
        default=True,
        help="Fill the destination's empty fields from the contacts merged into "
        "it. Turn it off to keep the destination's own identity, which is what a "
        "catch-all contact needs.",
    )

    _MERGE_SIZE_LIMIT = 3
    _IDENTIFYING_GROUPBY_FIELDS = frozenset({"email", "name", "vat"})

    def _merge_absorbs_source_values(self) -> bool:
        return not self or self.absorb_source_values

    def _get_excluded_merge_tables(self, model: str) -> set[str]:
        tables = super()._get_excluded_merge_tables(model)
        if model == "res.partner" and not self._merge_absorbs_source_values():
            tables.add("res_partner_bank")
        return tables

    @api.model
    def _update_foreign_keys(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> None:
        self._update_foreign_keys_generic("res.partner", src_partners, dst_partner)

    @api.model
    def _update_reference_fields(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> None:
        additional_update_records = [
            {"model": "calendar.event", "field_model": "res_model"}
        ]
        self._update_reference_fields_generic(
            "res.partner", src_partners, dst_partner, additional_update_records
        )

    def _get_fields_summable(self) -> list[str]:
        return []

    def _get_fields_excluded_value(self) -> tuple[str, ...]:
        return ()

    def _get_fields_deferred_value(self) -> tuple[str, ...]:
        return ("barcode",)

    @api.model
    def _update_values(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> dict[str, Any]:
        deferred_values = self._update_values_generic(
            src_partners,
            dst_partner,
            summable_fields=self._get_fields_summable(),
            deferred_fields=("parent_id", *self._get_fields_deferred_value()),
            excluded_fields=self._get_fields_excluded_value(),
        )
        parent_id = deferred_values.pop("parent_id", None)
        if parent_id and parent_id != dst_partner.id:
            try:
                dst_partner.write({"parent_id": parent_id})
            except ValidationError:
                _logger.info(
                    "Skip recursive partner hierarchies for parent_id %s of partner: %s",
                    parent_id,
                    dst_partner.id,
                )
        return deferred_values

    @api.model
    def _merge_bank_accounts(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> None:
        all_src_accounts = src_partners.bank_ids

        for src_account in all_src_accounts:
            duplicate_account = dst_partner.bank_ids.filtered(
                lambda a, src_account=src_account: (
                    a.sanitized_acc_number == src_account.sanitized_acc_number
                )
            )
            if duplicate_account:
                self._update_foreign_keys_generic(
                    "res.partner.bank", src_account, duplicate_account
                )
                self._update_reference_fields_generic(
                    "res.partner.bank", src_account, duplicate_account
                )
                src_account.sudo().unlink()
            else:
                src_account.sudo().write({"partner_id": dst_partner.id})

    def _merge(
        self,
        partner_ids: list[int],
        dst_partner: models.BaseModel | None = None,
        extra_checks: bool = True,
    ) -> None:
        if self.env.is_admin():
            extra_checks = False

        Partner = self.env["res.partner"]
        partner_ids = Partner.browse(partner_ids).exists()
        if len(partner_ids) < 2:
            return

        child_ids = Partner.browse()
        for partner in partner_ids:
            child_ids |= Partner.search([("id", "child_of", [partner.id])]) - partner
        if partner_ids & child_ids:
            raise UserError(
                self.env._("You cannot merge a contact with one of his parent.")
            )

        if len(partner_ids.with_context(active_test=False).user_ids) > 1:
            raise UserError(
                self.env._(
                    "You cannot merge contacts linked to more than one user even if only one is active."
                )
            )

        if extra_checks and len({partner.email for partner in partner_ids}) > 1:
            raise UserError(
                self.env._(
                    "All contacts must have the same email. Only the Administrator can merge contacts with different emails."
                )
            )

        if dst_partner and dst_partner in partner_ids:
            src_partners = partner_ids - dst_partner
        else:
            ordered_partners = self._get_ordered_partner(partner_ids.ids)
            dst_partner = ordered_partners[-1]
            src_partners = ordered_partners[:-1]
        _logger.info("dst_partner: %s", dst_partner.id)

        if dst_partner.company_id:
            partner_ids.mapped("user_ids").sudo().write(
                {
                    "company_ids": [Command.link(dst_partner.company_id.id)],
                    "company_id": dst_partner.company_id.id,
                }
            )

        deferred_values = {}
        if self._merge_absorbs_source_values():
            self._merge_bank_accounts(src_partners, dst_partner)

        self._update_foreign_keys(src_partners, dst_partner)
        self._update_reference_fields(src_partners, dst_partner)
        if self._merge_absorbs_source_values():
            deferred_values = self._update_values(src_partners, dst_partner)

        self.env.add_to_compute(dst_partner._fields["partner_share"], dst_partner)

        self._log_merge_operation(src_partners, dst_partner)

        src_partners.sudo().unlink()

        # Only now: a value under a uniqueness constraint cannot be adopted
        # while the record it came from still holds it.
        if deferred_values:
            dst_partner.write(deferred_values)

    def _log_merge_operation(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> None:
        _logger.info(
            "(uid = %s) merged the partners %r with %s",
            self.env.uid,
            src_partners.ids,
            dst_partner.id,
        )

    def _merge_duplicate_group(self, partner_ids: list[int]) -> None:
        dst_partner = self._get_ordered_partner(partner_ids)[-1]
        src_partners = [pid for pid in partner_ids if pid != dst_partner.id]
        chunk = self._MERGE_SIZE_LIMIT - 1
        for start in range(0, len(src_partners), chunk):
            self._merge(
                src_partners[start : start + chunk] + [dst_partner.id],
                dst_partner=dst_partner,
            )

    _GROUPBY_ALLOWED_FIELDS = frozenset(
        {"email", "name", "vat", "is_company", "parent_id"}
    )

    @api.model
    def _generate_query(self, fields: list[str], maximum_group: int = 100) -> SQL:
        sql_fields = []
        for field in fields:
            if field not in self._GROUPBY_ALLOWED_FIELDS:
                raise ValueError(f"Field {field!r} is not allowed in merge grouping")
            col = SQL.identifier(field)
            if field in ("email", "name"):
                sql_fields.append(SQL("lower(%s)", col))
            elif field == "vat":
                sql_fields.append(SQL("replace(%s, ' ', '')", col))
            else:
                sql_fields.append(col)
        group_fields = SQL(", ").join(sql_fields)

        filters = [
            SQL("%s IS NOT NULL", SQL.identifier(field))
            for field in fields
            if field in ("email", "name", "vat")
        ]

        parts = [
            SQL("SELECT min(id), array_agg(id)"),
            SQL("FROM res_partner"),
        ]
        if filters:
            parts.append(SQL("WHERE %s", SQL(" AND ").join(filters)))
        parts.extend(
            [
                SQL("GROUP BY %s", group_fields),
                SQL("HAVING COUNT(*) >= 2"),
                SQL("ORDER BY min(id)"),
            ]
        )
        if maximum_group:
            parts.append(SQL("LIMIT %s", maximum_group))

        return SQL(" ").join(parts)

    @api.model
    def _compute_selected_groupby(self) -> list[str]:
        groups = []
        group_by_prefix = "group_by_"

        for field_name in self._fields:
            if field_name.startswith(group_by_prefix):
                if self[field_name]:
                    groups.append(field_name.removeprefix(group_by_prefix))

        if not groups:
            raise UserError(
                self.env._("You have to specify a filter for your selection.")
            )

        if not self._IDENTIFYING_GROUPBY_FIELDS.intersection(groups):
            raise UserError(
                self.env._(
                    "Grouping on %(fields)s alone puts every contact sharing an "
                    "empty value in one group. Add Email, Name or VAT.",
                    fields=", ".join(sorted(groups)),
                )
            )

        return groups

    @api.model
    def _partner_use_in(self, aggr_ids: list[int], models: dict[str, str]) -> bool:
        return any(
            self.env[model].search_count([(field, "in", aggr_ids)])
            for model, field in models.items()
        )

    @api.model
    def _get_ordered_partner(self, partner_ids: list[int]) -> models.BaseModel:
        return (
            self.env["res.partner"]
            .browse(partner_ids)
            .sorted(
                key=lambda p: (
                    not p.active,
                    (p.create_date or datetime.datetime(1970, 1, 1)),
                ),
                reverse=True,
            )
        )

    def _compute_models(self) -> dict[str, str]:
        model_mapping = {}
        if self.exclude_contact:
            model_mapping["res.users"] = "partner_id"
        if "account.move.line" in self.env and self.exclude_journal_item:
            model_mapping["account.move.line"] = "partner_id"
        return model_mapping

    def action_skip(self) -> dict[str, Any]:
        if self.current_line_id:
            self.current_line_id.unlink()
        return self._action_next_screen()

    def _action_next_screen(self) -> dict[str, Any]:
        self.env.invalidate_all()
        values = {}
        if self.line_ids:
            current_line = self.line_ids[0]
            current_partner_ids = literal_eval(current_line.aggr_ids)
            values.update(
                {
                    "current_line_id": current_line.id,
                    "partner_ids": [Command.set(current_partner_ids)],
                    "dst_partner_id": self._get_ordered_partner(current_partner_ids)[
                        -1
                    ].id,
                    "state": "selection",
                }
            )
        else:
            values.update(
                {
                    "current_line_id": False,
                    "partner_ids": [],
                    "state": "finished",
                }
            )

        self.write(values)

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _process_query(self, query: SQL | str) -> None:
        self.ensure_one()
        model_mapping = self._compute_models()

        self.env.cr.execute(query if isinstance(query, SQL) else SQL(query))

        groups = self.env.cr.fetchall()
        all_ids = [pid for _, aggr_ids in groups for pid in aggr_ids]
        accessible = self.env["res.partner"].search([("id", "in", all_ids)])
        accessible_set = set(accessible.ids)

        counter = 0
        for min_id, aggr_ids in groups:
            partner_ids = [pid for pid in aggr_ids if pid in accessible_set]
            if len(partner_ids) < 2:
                continue

            if model_mapping and self._partner_use_in(partner_ids, model_mapping):
                continue

            self.env["base.partner.merge.line"].create(
                {
                    "wizard_id": self.id,
                    "min_id": min_id,
                    "aggr_ids": partner_ids,
                }
            )
            counter += 1

        self.write(
            {
                "state": "selection",
                "number_group": counter,
            }
        )

        _logger.info("counter: %s", counter)

    def action_start_manual_process(self) -> dict[str, Any]:
        self.ensure_one()
        groups = self._compute_selected_groupby()
        query = self._generate_query(groups, self.maximum_group)
        self._process_query(query)
        return self._action_next_screen()

    def action_start_automatic_process(self) -> dict[str, Any]:
        self.ensure_one()
        self.action_start_manual_process()
        self.env.invalidate_all()

        for line in self.line_ids:
            self._merge_duplicate_group(literal_eval(line.aggr_ids))
            line.unlink()
            self.env.cr.commit()

        self.write({"state": "finished"})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def parent_migration_process_cb(self) -> dict[str, Any]:
        self.ensure_one()

        query = """
            SELECT
                min(p1.id),
                array_agg(DISTINCT p1.id)
            FROM
                res_partner as p1
            INNER join
                res_partner as p2
            ON
                p1.email = p2.email AND
                p1.name = p2.name AND
                (p1.parent_id = p2.id OR p1.id = p2.parent_id)
            WHERE
                p2.id IS NOT NULL
            GROUP BY
                p1.email,
                p1.name,
                CASE WHEN p1.parent_id = p2.id THEN p2.id
                    ELSE p1.id
                END
            HAVING COUNT(*) >= 2
            ORDER BY
                min(p1.id)
        """

        self._process_query(query)

        for line in self.line_ids:
            self._merge_duplicate_group(literal_eval(line.aggr_ids))
            line.unlink()
            self.env.cr.commit()

        self.write({"state": "finished"})

        self.env.cr.execute("""
            UPDATE
                res_partner
            SET
                is_company = NULL,
                parent_id = NULL
            WHERE
                parent_id = id
        """)

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_update_all_process(self) -> dict[str, Any]:
        self.ensure_one()
        self.parent_migration_process_cb()

        wizard = self.create(
            {
                "group_by_vat": True,
                "group_by_email": True,
                "group_by_name": True,
            }
        )
        wizard.action_start_automatic_process()

        self.env.cr.execute("""
            UPDATE
                res_partner
            SET
                is_company = NULL
            WHERE
                parent_id IS NOT NULL AND
                is_company IS NOT NULL
        """)

        return self._action_next_screen()

    def action_merge(self) -> dict[str, Any]:
        if len(self.partner_ids) > self._MERGE_SIZE_LIMIT:
            raise UserError(
                self.env._(
                    "For safety reasons, you cannot merge more than %(limit)s contacts "
                    "together. You can re-open the wizard several times if needed.",
                    limit=self._MERGE_SIZE_LIMIT,
                )
            )
        if not self.partner_ids:
            self.write({"state": "finished"})
            return {
                "type": "ir.actions.act_window",
                "res_model": self._name,
                "res_id": self.id,
                "view_mode": "form",
                "target": "new",
            }

        self._merge(self.partner_ids.ids, self.dst_partner_id)

        if self.current_line_id:
            self.current_line_id.unlink()

        return self._action_next_screen()
