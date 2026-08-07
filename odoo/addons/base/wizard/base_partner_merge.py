import datetime
import itertools
import logging
from ast import literal_eval
from collections import defaultdict
from typing import Any

import psycopg

from odoo import api, fields, models
from odoo.db import schema as sql_tools
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import SQL, mute_logger

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

    def _get_fk_on(self, table: str) -> list[tuple[str, str]]:
        query = """
            SELECT cl1.relname as table, att1.attname as column
            FROM pg_constraint as con, pg_class as cl1, pg_class as cl2, pg_attribute as att1, pg_attribute as att2
            WHERE con.conrelid = cl1.oid
                AND con.confrelid = cl2.oid
                AND array_lower(con.conkey, 1) = 1
                AND con.conkey[1] = att1.attnum
                AND att1.attrelid = cl1.oid
                AND cl2.relname = %s
                AND cl2.relnamespace = current_schema::regnamespace
                AND att2.attname = 'id'
                AND array_lower(con.confkey, 1) = 1
                AND con.confkey[1] = att2.attnum
                AND att2.attrelid = cl2.oid
                AND con.contype = 'f'
        """
        self.env.cr.execute(query, (table,))
        return self.env.cr.fetchall()

    def _has_check_or_unique_constraint(self, table: str, column: str) -> bool:
        self.env.cr.execute(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class r ON (c.conrelid = r.oid)
            CROSS JOIN LATERAL unnest(c.conkey) AS cattr(attnum)
            JOIN pg_attribute a ON (a.attrelid = c.conrelid AND a.attnum = cattr.attnum)
            WHERE c.contype IN ('c', 'u')
                AND r.relname = %s
                AND r.relnamespace = current_schema::regnamespace
                AND a.attname = %s
            LIMIT 1
        """,
            (table, column),
        )
        return bool(self.env.cr.fetchone())

    @api.model
    def _update_foreign_keys_generic(
        self,
        model: str,
        src_records: models.BaseModel,
        dst_record: models.BaseModel,
    ) -> None:
        _logger.debug(
            "_update_foreign_keys_generic for dst_record: %s for src_records: %s",
            dst_record.id,
            src_records.ids,
        )

        relations = self._get_fk_on(self.env[model]._table)

        self.env.invalidate_all()

        for table, column in relations:
            if "base_partner_merge_" in table:
                continue

            tbl = SQL.identifier(table)
            col = SQL.identifier(column)

            columns = [
                col
                for col in sql_tools.table_columns(self.env.cr, table)
                if col != column
            ]

            self.env.cr.execute(
                SQL(
                    "SELECT FROM %s WHERE %s = ANY(%s) LIMIT 1",
                    tbl,
                    col,
                    list(src_records.ids),
                )
            )
            if self.env.cr.fetchone() is None:
                continue

            if len(columns) <= 1:
                if not columns:
                    continue
                val = SQL.identifier(columns[0])
                for record in src_records:
                    self.env.cr.execute(
                        SQL(
                            """
                        UPDATE %s as ___tu
                        SET %s = %s
                        WHERE
                            %s = %s AND
                            NOT EXISTS (
                                SELECT 1
                                FROM %s as ___tw
                                WHERE
                                    %s = %s AND
                                    ___tu.%s = ___tw.%s
                            )""",
                            tbl,
                            col,
                            dst_record.id,
                            col,
                            record.id,
                            tbl,
                            col,
                            dst_record.id,
                            val,
                            val,
                        )
                    )
            elif not self._has_check_or_unique_constraint(table, column):
                self.env.cr.execute(
                    SQL(
                        "UPDATE %s SET %s = %s WHERE %s = ANY(%s)",
                        tbl,
                        col,
                        dst_record.id,
                        col,
                        list(src_records.ids),
                    )
                )
            else:
                try:
                    with mute_logger("odoo.db"), self.env.cr.savepoint():
                        self.env.cr.execute(
                            SQL(
                                "UPDATE %s SET %s = %s WHERE %s = ANY(%s)",
                                tbl,
                                col,
                                dst_record.id,
                                col,
                                list(src_records.ids),
                            )
                        )
                except psycopg.Error:
                    for record in src_records:
                        try:
                            with mute_logger("odoo.db"), self.env.cr.savepoint():
                                self.env.cr.execute(
                                    SQL(
                                        "UPDATE %s SET %s = %s WHERE %s = ANY(%s)",
                                        tbl,
                                        col,
                                        dst_record.id,
                                        col,
                                        [record.id],
                                    )
                                )
                        except psycopg.Error:
                            self.env.cr.execute(
                                SQL(
                                    "DELETE FROM %s WHERE %s = ANY(%s)",
                                    tbl,
                                    col,
                                    [record.id],
                                )
                            )

    @api.model
    def _update_reference_fields_generic(
        self,
        referenced_model: str,
        src_records: models.BaseModel,
        dst_record: models.BaseModel,
        additional_update_records: list[dict[str, str]] | None = None,
    ) -> None:
        _logger.debug(
            "_update_reference_fields_generic for dst_record: %s for src_records: %r",
            dst_record.id,
            src_records.ids,
        )

        def update_records(
            model: str,
            src: models.BaseModel,
            field_model: str = "model",
            field_id: str = "res_id",
        ) -> None:
            Model = self.env.get(model, None)
            if Model is None:
                return
            records = Model.sudo().search(
                [(field_model, "=", referenced_model), (field_id, "=", src.id)]
            )
            if not records:
                return
            if not self._has_check_or_unique_constraint(records._table, field_id):
                records.sudo().write({field_id: dst_record.id})
                records.env.flush_all()
                return
            try:
                with mute_logger("odoo.db"), self.env.cr.savepoint():
                    records.sudo().write({field_id: dst_record.id})
                    records.env.flush_all()
            except psycopg.Error:
                records.sudo().unlink()

        additional_update_records = additional_update_records or []
        for record in src_records:
            update_records("ir.attachment", src=record, field_model="res_model")
            update_records("mail.followers", src=record, field_model="res_model")
            update_records("mail.activity", src=record, field_model="res_model")
            update_records("mail.message", src=record)
            update_records("ir.model.data", src=record)
            for update_record in additional_update_records:
                update_records(
                    update_record["model"],
                    src=record,
                    field_model=update_record["field_model"],
                )

        records = (
            self.env["ir.model.fields"]
            .sudo()
            .search([("ttype", "=", "reference"), ("store", "=", True)])
        )
        for record in records:
            try:
                Model = self.env[record.model]
                field = Model._fields[record.name]
            except KeyError:
                continue

            if Model._abstract or field.compute is not None:
                continue

            src_values = [f"{referenced_model},{src.id}" for src in src_records]
            records_ref = Model.sudo().search([(record.name, "in", src_values)])
            if not records_ref:
                continue
            new_value = f"{referenced_model},{dst_record.id}"
            try:
                with mute_logger("odoo.db"), self.env.cr.savepoint():
                    records_ref.sudo().write({record.name: new_value})
                    records_ref.env.flush_all()
            except psycopg.Error:
                for rec in records_ref:
                    try:
                        with mute_logger("odoo.db"), self.env.cr.savepoint():
                            rec.sudo().write({record.name: new_value})
                            rec.env.flush_all()
                    except psycopg.Error as error:
                        _logger.warning(
                            "Merging %s into %s: re-pointing %s.%s failed (%s), "
                            "deleting %s#%s to keep the reference consistent",
                            src_records.ids,
                            dst_record.id,
                            record.model,
                            record.name,
                            error.__class__.__name__,
                            rec._name,
                            rec.id,
                        )
                        rec.sudo().unlink()
        for field in self.env.registry.many2one_company_dependents[dst_record._name]:
            self.env.cr.execute(
                SQL(
                    """
                UPDATE %(table)s
                SET %(field)s = (
                    SELECT jsonb_object_agg(key,
                        CASE
                            WHEN value::int IN %(src_record_ids)s
                            THEN %(dest_record_id)s
                            ELSE value::int
                        END
                    )
                    FROM jsonb_each_text(%(field)s)
                )
                WHERE %(field)s IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM jsonb_each_text(%(field)s) AS each_val(k, v)
                    WHERE v::int IN %(src_record_ids)s
                )
                """,
                    table=SQL.identifier(self.env[field.model_name]._table),
                    field=SQL.identifier(field.name),
                    src_record_ids=tuple(src_records.ids),
                    dest_record_id=dst_record.id,
                )
            )

        self.env.cr.execute(
            SQL(
                """
            UPDATE ir_default
            SET json_value =
                CASE
                    WHEN json_value::int IN %(src_record_ids)s
                    THEN %(dest_record_id)s
                    ELSE json_value
                END
            FROM ir_model_fields f
            WHERE f.id = ir_default.field_id
            AND f.company_dependent
            AND f.relation = %(model_name)s
            AND f.ttype = 'many2one'
            AND json_value ~ '^[0-9]+$';
            """,
                src_record_ids=tuple(src_records.ids),
                dest_record_id=str(dst_record.id),
                model_name=dst_record._name,
            )
        )

        self.env.flush_all()

        for fname, field in dst_record._fields.items():
            if not field.company_dependent:
                continue
            self.env.execute_query(
                SQL(
                    """
                WITH source AS (
                    SELECT %(field)s
                    FROM  %(table)s
                    WHERE id IN %(source_ids)s
                    ORDER BY id
                ), source_agg AS (
                    SELECT jsonb_object_agg(key, value) AS value
                    FROM  source, jsonb_each(%(field)s)
                )
                UPDATE %(table)s
                SET %(field)s = source_agg.value || COALESCE(%(table)s.%(field)s, '{}'::jsonb)
                FROM source_agg
                WHERE id = %(destination_id)s AND source_agg.value IS NOT NULL
                """,
                    table=SQL.identifier(dst_record._table),
                    field=SQL.identifier(fname),
                    destination_id=dst_record.id,
                    source_ids=tuple(src_records.ids),
                )
            )

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

    def _get_summable_fields(self) -> list[str]:
        return []

    @api.model
    def _update_values(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> None:
        _logger.debug(
            "_update_values for dst_partner: %s for src_partners: %r",
            dst_partner.id,
            src_partners.ids,
        )

        model_fields = dst_partner.fields_get().keys()
        summable_fields = self._get_summable_fields()

        def write_serializer(item: Any) -> Any:
            if isinstance(item, models.BaseModel):
                return item.id
            else:
                return item

        values = {}
        values_by_company = defaultdict(dict)
        for column in model_fields:
            field = dst_partner._fields[column]
            if field.type not in ("many2many", "one2many") and field.compute is None:
                for item in itertools.chain(src_partners, [dst_partner]):
                    if item[column]:
                        if field.type == "reference":
                            values[column] = item[column]
                        elif column in summable_fields and values.get(column):
                            values[column] += write_serializer(item[column])
                        else:
                            values[column] = write_serializer(item[column])
            elif field.company_dependent and column in summable_fields:
                partners = (src_partners + dst_partner).sudo()
                for company in self.env["res.company"].sudo().search([]):
                    values_by_company[company][column] = sum(
                        partners.with_company(company).mapped(column)
                    )

        values.pop("id", None)
        parent_id = values.pop("parent_id", None)
        dst_partner.write(values)
        for company, vals in values_by_company.items():
            dst_partner.with_company(company).sudo().write(vals)
        if parent_id and parent_id != dst_partner.id:
            try:
                dst_partner.write({"parent_id": parent_id})
            except ValidationError:
                _logger.info(
                    "Skip recursive partner hierarchies for parent_id %s of partner: %s",
                    parent_id,
                    dst_partner.id,
                )

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

        if len(partner_ids) > 3:
            raise UserError(
                self.env._(
                    "For safety reasons, you cannot merge more than 3 contacts together. You can re-open the wizard several times if needed."
                )
            )

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

        self._merge_bank_accounts(src_partners, dst_partner)

        self._update_foreign_keys(src_partners, dst_partner)
        self._update_reference_fields(src_partners, dst_partner)
        self._update_values(src_partners, dst_partner)

        self.env.add_to_compute(dst_partner._fields["partner_share"], dst_partner)

        self._log_merge_operation(src_partners, dst_partner)

        src_partners.sudo().unlink()

    def _log_merge_operation(
        self, src_partners: models.BaseModel, dst_partner: models.BaseModel
    ) -> None:
        _logger.info(
            "(uid = %s) merged the partners %r with %s",
            self.env.uid,
            src_partners.ids,
            dst_partner.id,
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
            partner_ids = literal_eval(line.aggr_ids)
            self._merge(partner_ids)
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
            partner_ids = literal_eval(line.aggr_ids)
            self._merge(partner_ids)
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
