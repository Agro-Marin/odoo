import contextlib
import json

from odoo import Command, _, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.tools import SQL, Query


class MixinCompanySplit(models.AbstractModel):
    """Split a record shared by several companies back into one per company.

    The inverse of a merge, for models whose membership is a ``company_ids``
    many2many. Everything here is generic over ``self._name`` and ``self._table``;
    a model contributes two things of its own -- the values a split copy starts
    from (``_unmerge_copy_defaults``) and the action its confirmation dialog
    offers (``_unmerge_action_xmlid``).
    """

    _name = "mixin.company.split"
    _description = "Per-company record split"

    def _unmerge_action_xmlid(self):
        raise NotImplementedError

    def _unmerge_copy_defaults(self):
        """Values every split copy starts from, beyond its company and the
        ``check_company`` fields the mixin narrows on its own."""
        return {}

    def _unmerge_finalize(self, new_record_by_company):
        """Last step, after every record's ``company_ids`` has settled.

        `_unmerge_copy_defaults` runs while the original still holds all of its
        companies, so a value that must be unique *across* membership -- a tax
        name -- cannot be set there without colliding with the original.
        """
        return

    def _unmerge_split_sidecars(self, new_record_by_company):
        """Repoint references to records the split *copied* rather than shared.

        The remaps below follow references to the record itself. A model whose
        copies carry their own children -- a tax and its distribution lines --
        has to send each company's traffic to its own copy's children here.
        """
        return

    def action_unmerge(self):
        self._check_action_unmerge_possible()
        self._action_unmerge_get_user_confirmation()

        for record in self.with_context(
            {
                "allowed_company_ids": (
                    self.env.company | self.env.user.company_ids
                ).ids,
            }
        ):
            record._action_unmerge()

        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def _check_action_unmerge_possible(self):
        self.check_access("write")

        if forbidden_companies := (self.sudo().company_ids - self.env.user.company_ids):
            raise UserError(
                _(
                    "You do not have the right to perform this operation as "
                    "you do not have access to the following companies: %s.",
                    ", ".join(c.name for c in forbidden_companies),
                )
            )
        for record in self:
            if len(record.company_ids) == 1:
                raise UserError(
                    _(
                        "Account %s cannot be unmerged as it already belongs "
                        "to a single company. The unmerge operation only "
                        "splits a record based on its companies.",
                        record.display_name,
                    )
                )

    def _action_unmerge_get_user_confirmation(self):
        if self.env.context.get("account_unmerge_confirm"):
            return

        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            self._unmerge_action_xmlid(),
        )
        msg = _("Are you sure? This will perform the following operations:\n")
        for record in self:
            msg += _(
                "%(record)s will be split in %(count)s, one for each company:\n",
                record=record.display_name,
                count=len(record.company_ids),
            )
            msg += "".join(
                f"    - {company.name}: {record.with_company(company).display_name}\n"
                for company in record.company_ids
            )
        raise RedirectWarning(
            msg,
            action,
            _("Unmerge"),
            additional_context={
                **self.env.context,
                "account_unmerge_confirm": True,
            },
        )

    def _action_unmerge(self):
        self.ensure_one()

        self._check_action_unmerge_possible()

        base_company = (
            self.env.company
            if self.env.company in self.company_ids
            else self.company_ids[0]
        )
        new_record_by_company = self._unmerge_create_records(base_company)
        new_records = self.browse().union(
            *new_record_by_company.values(),
        )

        self.env.invalidate_all()
        new_id_by_company_id = {
            str(company.id): new_account.id
            for company, new_account in new_record_by_company.items()
        }
        (self | new_records).invalidate_recordset()

        self._unmerge_split_sidecars(new_record_by_company)
        self._unmerge_remap_many2x_fields(new_id_by_company_id)
        self._unmerge_remap_reference_fields(new_id_by_company_id)
        self._unmerge_remap_many2one_reference_fields(new_id_by_company_id)
        self._unmerge_migrate_company_dependent_fields(
            new_records, new_id_by_company_id
        )
        self._unmerge_split_xmlids(base_company, new_id_by_company_id)

        self.env.registry.clear_cache()
        self.env.invalidate_all()

        self._unmerge_reassign_company_fields(base_company)

        # Only now does every record -- the original included -- hold exactly
        # the companies it will keep. A model with a uniqueness rule that spans
        # membership can only set the colliding values here.
        self._unmerge_finalize(new_record_by_company)

        self._unmerge_log_split(new_records, base_company)

        return new_records

    def _unmerge_company_id_subquery(self, model):
        if model == "res.company":
            company_id_field = "id"
        elif "company_id" in self.env[model]:
            company_id_field = "company_id"
        else:
            return None
        with contextlib.suppress(ValueError):
            query = Query(
                self.env,
                self.env[model]._table,
                self.env[model]._table_sql,
            )
            return query.select(
                SQL(
                    "%s AS id",
                    self.env[model]._field_to_sql(query.table, "id"),
                ),
                SQL(
                    "%s AS company_id",
                    self.env[model]._field_to_sql(
                        query.table,
                        company_id_field,
                        query,
                    ),
                ),
            )

    def _unmerge_create_records(self, base_company):
        companies_to_update = self.company_ids - base_company
        check_company_fields = {
            fname
            for fname, field in self._fields.items()
            if field.relational and field.check_company
        }
        new_by_company = {}
        for company in companies_to_update:
            # `company_ids` is written AFTER the copy, never as a copy default.
            # Passing it in `default` fires every compute that depends on it,
            # and on account.tax that includes the ones seeding default
            # distribution lines -- which then land on top of the copied ones.
            new = self.copy(
                default={
                    **self._unmerge_copy_defaults(),
                    **{
                        fname: self[fname].filtered(
                            lambda record, company=company: (
                                company in record.company_ids
                                if "company_ids" in record._fields
                                else record.company_id == company
                            ),
                        )
                        for fname in check_company_fields
                    },
                }
            )
            new.company_ids = [Command.set(company.ids)]
            new_by_company[company] = new
        return new_by_company

    def _unmerge_remap_many2x_fields(self, new_id_by_company_id):
        new_id_by_company_id_json = json.dumps(new_id_by_company_id)
        many2x_fields = self.env["ir.model.fields"].search(
            [
                ("ttype", "in", ("many2one", "many2many")),
                ("relation", "=", self._name),
                ("store", "=", True),
                ("company_dependent", "=", False),
            ]
        )
        for field_to_update in many2x_fields:
            model = field_to_update.model
            if not self.env[model]._auto:
                continue
            if not (query_company_id := self._unmerge_company_id_subquery(model)):
                continue
            if field_to_update.ttype == "many2one":
                table = self.env[model]._table
                target_column = field_to_update.name
                model_column = "id"
            else:
                table = field_to_update.relation_table
                target_column = field_to_update.column2
                model_column = field_to_update.column1
            self.env.cr.execute(
                SQL(
                    """
                 UPDATE %(table)s
                    SET %(target_column)s = (
                            %(json)s::jsonb->>
                            table_with_company_id.company_id::text
                        )::int
                   FROM (%(query_company_id)s) table_with_company_id
                  WHERE table_with_company_id.id = %(model_column)s
                    AND %(table)s.%(target_column)s = %(record_id)s
                    AND table_with_company_id.company_id
                        IN %(company_ids_to_update)s
                """,
                    table=SQL.identifier(table),
                    target_column=SQL.identifier(target_column),
                    json=new_id_by_company_id_json,
                    query_company_id=query_company_id,
                    model_column=SQL.identifier(table, model_column),
                    record_id=self.id,
                    company_ids_to_update=tuple(
                        new_id_by_company_id,
                    ),
                )
            )
        for field in self.env.registry.many2one_company_dependents[self._name]:
            self.env.cr.execute(
                SQL(
                    """
                UPDATE %(table)s
                SET %(column)s = (
                    SELECT jsonb_object_agg(key,
                        CASE
                            WHEN value::int = %(record_id)s
                                AND %(json)s ? key
                            THEN (%(json)s::jsonb->>key)::int
                            ELSE value::int
                        END
                    )
                    FROM jsonb_each_text(%(column)s)
                )
                WHERE %(column)s IS NOT NULL
                """,
                    table=SQL.identifier(
                        self.env[field.model_name]._table,
                    ),
                    column=SQL.identifier(field.name),
                    json=new_id_by_company_id_json,
                    record_id=self.id,
                )
            )

    def _unmerge_remap_reference_fields(self, new_id_by_company_id):
        new_id_by_company_id_json = json.dumps(new_id_by_company_id)
        reference_fields = self.env["ir.model.fields"].search(
            [
                ("ttype", "=", "reference"),
                ("store", "=", True),
            ]
        )
        for field_to_update in reference_fields:
            model = field_to_update.model
            if not self.env[model]._auto:
                continue
            if not (query_company_id := self._unmerge_company_id_subquery(model)):
                continue
            self.env.cr.execute(
                SQL(
                    """
                 UPDATE %(table)s
                    SET %(column)s = %(model_prefix)s || (
                        %(json)s::jsonb->>
                        table_with_company_id.company_id::text)
                   FROM (%(query_company_id)s) table_with_company_id
                  WHERE table_with_company_id.id = %(table)s.id
                    AND %(column)s = %(value_to_update)s
                    AND table_with_company_id.company_id
                        IN %(company_ids_to_update)s
                """,
                    table=SQL.identifier(self.env[model]._table),
                    column=SQL.identifier(field_to_update.name),
                    json=new_id_by_company_id_json,
                    query_company_id=query_company_id,
                    model_prefix=f"{self._name},",
                    value_to_update=f"{self._name},{self.id}",
                    company_ids_to_update=tuple(
                        new_id_by_company_id,
                    ),
                )
            )

    def _unmerge_remap_many2one_reference_fields(self, new_id_by_company_id):
        new_id_by_company_id_json = json.dumps(new_id_by_company_id)
        many2one_reference_fields = self.env["ir.model.fields"].search(
            [
                ("ttype", "=", "many2one_reference"),
                ("store", "=", True),
                "!",
                "&",
                ("model", "=", "studio.approval.request"),
                ("name", "=", "res_id"),
            ]
        )
        for field_to_update in many2one_reference_fields:
            model = field_to_update.model
            model_field = (
                self.env[model]._fields[field_to_update.name]._related_model_field
            )
            if (
                not self.env[model]._auto
                or not self.env[model]._fields[model_field].store
            ):
                continue
            if not (query_company_id := self._unmerge_company_id_subquery(model)):
                continue
            self.env.cr.execute(
                SQL(
                    """
                 UPDATE %(table)s
                    SET %(column)s = (
                        %(json)s::jsonb->>
                        table_with_company_id.company_id::text)::int
                   FROM (%(query_company_id)s) table_with_company_id
                  WHERE table_with_company_id.id = %(table)s.id
                    AND %(column)s = %(record_id)s
                    AND %(model_column)s = %(source_model)s
                    AND table_with_company_id.company_id
                        IN %(company_ids_to_update)s
                """,
                    table=SQL.identifier(self.env[model]._table),
                    column=SQL.identifier(field_to_update.name),
                    json=new_id_by_company_id_json,
                    query_company_id=query_company_id,
                    record_id=self.id,
                    source_model=self._name,
                    model_column=SQL.identifier(model_field),
                    company_ids_to_update=tuple(
                        new_id_by_company_id,
                    ),
                )
            )

    def _unmerge_migrate_company_dependent_fields(
        self, new_records, new_id_by_company_id
    ):
        # A model with no company_dependent field has nothing to carve up, and
        # the statements below would be built with an empty SET clause --
        # `SET  FROM ...`, which Postgres rejects outright. account.account has
        # `code_store`; account.tax has none.
        if not any(field.company_dependent for field in self._fields.values()):
            return
        new_id_by_company_id_json = json.dumps(new_id_by_company_id)
        self.env.cr.execute(
            SQL(
                """
            WITH new_account_company AS (
                SELECT key AS company_id, value::int AS account_id
                FROM json_each_text(%(json)s)
            )
            UPDATE %(table)s new
            SET %(migrate_fields)s
            FROM %(table)s old, new_account_company a2c
            WHERE old.id = %(old_id)s
            AND a2c.account_id = new.id
            AND new.id IN %(new_ids)s
            """,
                json=new_id_by_company_id_json,
                table=SQL.identifier(self._table),
                migrate_fields=SQL(", ").join(
                    SQL(
                        """
                    %(field)s = CASE
                        WHEN old.%(field)s ? a2c.company_id
                        THEN jsonb_build_object(
                            a2c.company_id,
                            old.%(field)s->a2c.company_id)
                        ELSE NULL END
                    """,
                        field=SQL.identifier(field_name),
                    )
                    for field_name, field in self._fields.items()
                    if field.company_dependent
                ),
                old_id=self.id,
                new_ids=tuple(new_records.ids),
            )
        )
        self.env.cr.execute(
            SQL(
                "UPDATE %(table)s SET %(fields_drop)s WHERE id = %(id)s",
                table=SQL.identifier(self._table),
                fields_drop=SQL(", ").join(
                    SQL(
                        "%(field)s = NULLIF(%(field)s - "
                        "%(company_ids)s::text[], '{}'::jsonb)",
                        field=SQL.identifier(field_name),
                        company_ids=list(new_id_by_company_id),
                    )
                    for field_name, field in self._fields.items()
                    if field.company_dependent
                ),
                id=self.id,
            )
        )

    def _unmerge_split_xmlids(self, base_company, new_id_by_company_id):
        self.env["ir.model.data"].invalidate_model()
        id_by_company_id_json = json.dumps(
            {
                **new_id_by_company_id,
                str(base_company.id): self.id,
            }
        )
        self.env.cr.execute(
            SQL(
                """
             UPDATE ir_model_data
                SET res_id = (
                        %(json)s::jsonb->>
                        substring(name, %(xmlid_regex)s)
                    )::int
              WHERE module = 'account'
                AND model = %(model)s
                AND res_id = %(record_id)s
                AND name ~ %(xmlid_regex)s
            """,
                json=id_by_company_id_json,
                model=self._name,
                xmlid_regex=r"([\d]+)_.*",
                record_id=self.id,
            )
        )

    def _unmerge_reassign_company_fields(self, base_company):
        write_vals = {"company_ids": [Command.set(base_company.ids)]}
        check_company_fields = {
            field
            for field in self._fields.values()
            if field.relational and field.check_company
        }
        for field in check_company_fields:
            corecord = self[field.name]
            filtered_corecord = corecord.filtered_domain(
                corecord._check_company_domain(base_company),
            )
            write_vals[field.name] = (
                filtered_corecord.id
                if field.type == "many2one"
                else [Command.set(filtered_corecord.ids)]
            )
        self.write(write_vals)

    def _unmerge_log_split(self, new_records, base_company):
        msg_body = _(
            "This record was split off from %(source)s (%(company_name)s).",
            source=self._get_html_link(title=self.display_name),
            company_name=base_company.name,
        )
        new_records._message_log_batch(
            bodies={a.id: msg_body for a in new_records},
        )
