import itertools
import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import psycopg

from odoo import api, models
from odoo.db import schema as sql_tools
from odoo.tools import SQL, mute_logger

_logger = logging.getLogger("odoo.addons.base.merge")


class MixinMerge(models.AbstractModel):
    _name = "mixin.merge"
    _description = "Record Merge Engine"

    def _merge_absorbs_source_values(self) -> bool:
        return True

    def _get_excluded_merge_tables(self, model: str) -> set[str]:
        tables = {self._table}
        for field in self._fields.values():
            if field.type == "many2many" and field.relation:
                tables.add(field.relation)
        if not self._merge_absorbs_source_values():
            for field in self.env[model]._fields.values():
                if field.type == "many2many" and field.store and field.relation:
                    tables.add(field.relation)
        return tables

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

    def _get_relations_to_repoint(self, model: str) -> list[tuple[str, str]]:
        skipped_tables = self._get_excluded_merge_tables(model)
        return [
            (table, column)
            for table, column in self._get_fk_on(self.env[model]._table)
            if table not in skipped_tables
        ]

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

        relations = self._get_relations_to_repoint(model)

        self.env.invalidate_all()

        for table, column in relations:
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
                        except psycopg.Error as error:
                            _logger.warning(
                                "Merging %s into %s: re-pointing %s.%s failed (%s), "
                                "deleting the %s rows of %s to keep the merge going",
                                src_records.ids,
                                dst_record.id,
                                table,
                                column,
                                error.__class__.__name__,
                                table,
                                record.id,
                            )
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

    @api.model
    def _update_company_dependent_values_generic(
        self,
        src_records: models.BaseModel,
        dst_record: models.BaseModel,
    ) -> None:
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
        self.env.invalidate_all()

    @api.model
    def _update_values_generic(
        self,
        src_records: models.BaseModel,
        dst_record: models.BaseModel,
        summable_fields: Iterable[str] = (),
        deferred_fields: Iterable[str] = (),
        excluded_fields: Iterable[str] = (),
    ) -> dict[str, Any]:
        _logger.debug(
            "_update_values_generic for dst_record: %s for src_records: %r",
            dst_record.id,
            src_records.ids,
        )

        self._update_company_dependent_values_generic(src_records, dst_record)

        model_fields = dst_record.fields_get().keys()
        summable_fields = set(summable_fields)

        def write_serializer(item: Any) -> Any:
            if isinstance(item, models.BaseModel):
                return item.id
            else:
                return item

        values = {}
        values_by_company = defaultdict(dict)
        for column in model_fields:
            field = dst_record._fields[column]
            if field.type not in ("many2many", "one2many") and field.compute is None:
                for item in itertools.chain(src_records, [dst_record]):
                    if item[column]:
                        if field.type == "reference":
                            values[column] = item[column]
                        elif column in summable_fields and values.get(column):
                            values[column] += write_serializer(item[column])
                        else:
                            values[column] = write_serializer(item[column])
            elif field.company_dependent and column in summable_fields:
                records = (src_records + dst_record).sudo()
                for company in self.env["res.company"].sudo().search([]):
                    values_by_company[company][column] = sum(
                        records.with_company(company).mapped(column)
                    )

        values.pop("id", None)
        for name in excluded_fields:
            values.pop(name, None)
        deferred_values = {
            name: values.pop(name) for name in deferred_fields if name in values
        }
        dst_record.write(values)
        for company, vals in values_by_company.items():
            dst_record.with_company(company).sudo().write(vals)
        return deferred_values
