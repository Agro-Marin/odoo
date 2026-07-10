import json
from datetime import date
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import SUPERUSER_ID, ValuesType
from odoo.exceptions import ValidationError
from odoo.fields import Domain

# PostgreSQL ``int4`` range. Both entry points (``set`` and the
# ``_check_json_format`` constraint) reject out-of-range values up front via
# ``_fits_column`` rather than failing later against the real column (IDEF-C1).
INT4_MIN = -(2**31)
INT4_MAX = 2**31 - 1


class IrDefault(models.Model):
    """User-defined default values for fields."""

    _name = "ir.default"
    _description = "Default Values"
    _rec_name = "field_id"
    _allow_sudo_commands = False

    field_id = fields.Many2one(
        "ir.model.fields",
        string="Field",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        ondelete="cascade",
        index=True,
        help="If set, action binding only applies for this user.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        ondelete="cascade",
        index=True,
        help="If set, action binding only applies for this company",
    )
    condition = fields.Char(
        "Condition",
        help="If set, applies the default upon condition.",
    )
    json_value = fields.Char("Default Value (JSON format)", required=True)

    # One default per scope.  NULL user_id/company_id/condition are folded via
    # COALESCE so the all-NULL scope is unique too; otherwise a concurrent
    # ``set()`` race leaves permanent shadow rows the read path silently ignores.
    # See migrations/1.5/pre-migration.py for the one-time dedupe.
    _unique_scope = models.UniqueIndex(
        "(field_id, COALESCE(user_id, 0), COALESCE(company_id, 0),"
        " COALESCE(condition, ''))"
    )

    # ------------------------------------------------------------------
    # Value validation (shared by set() and the create/write constraint)
    # ------------------------------------------------------------------

    @staticmethod
    def _fits_column(field, parsed: Any) -> bool:
        """Whether a ``convert_to_cache`` result fits the field's storage column.

        Only the ``int4`` range is enforced; both value-validation paths funnel
        through this single guard.
        """
        if field.type == "integer":
            return INT4_MIN <= parsed <= INT4_MAX
        return True

    @api.constrains("json_value", "field_id")
    def _check_json_format(self) -> None:
        for record in self:
            field_rec = record.sudo().field_id
            model_name = field_rec.model_id.model
            model = self.env[model_name]
            field = model._fields[field_rec.name]
            try:
                value = json.loads(record.json_value)
            except json.JSONDecodeError:
                raise ValidationError(
                    self.env._("Invalid JSON format in Default Value field.")
                ) from None
            try:
                parsed = field.convert_to_cache(value, model)
            except ValueError, TypeError:
                raise ValidationError(
                    self.env._(
                        "Invalid value in Default Value field. Expected type '%(field_type)s' for '%(model_name)s.%(field_name)s'.",
                        field_type=field_rec.ttype,
                        model_name=model_name,
                        field_name=field_rec.name,
                    )
                ) from None
            if not self._fits_column(field, parsed):
                raise ValidationError(
                    self.env._(
                        "Invalid value in Default Value field. %(value)s is out of bounds for '%(model_name)s.%(field_name)s' (integers should be between -2,147,483,648 and 2,147,483,647).",
                        value=value,
                        model_name=model_name,
                        field_name=field_rec.name,
                    )
                )

    def _check_accessible_field_id(self) -> None:
        # a user may only set a default for a field they can write; called
        # after record-level access has been checked
        if self.env.su:
            return
        for record in self:
            if field := record.field_id:
                model = self.env[field.model]
                model._check_field_access(model._fields[field.name], "write")

    # ------------------------------------------------------------------
    # Cache invalidation on any change to the stored defaults
    # ------------------------------------------------------------------

    def _invalidate_defaults_cache(self) -> None:
        """Drop the caches derived from the stored defaults.

        Company-dependent fields cache a per-company fallback computed from
        these defaults, so a change must invalidate both the record cache and
        the ormcaches built on it (``_get_model_defaults``,
        ``_get_field_column_fallbacks``).
        """
        self.env.invalidate_all()
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        new_defaults = super().create(vals_list)
        new_defaults._check_accessible_field_id()
        if new_defaults:
            new_defaults._invalidate_defaults_cache()
        return new_defaults

    def write(self, vals: dict[str, Any]) -> bool:
        result = super().write(vals)
        self._check_accessible_field_id()
        if self:
            self._invalidate_defaults_cache()
        return result

    def unlink(self) -> bool:
        result = super().unlink()
        if self:
            self._invalidate_defaults_cache()
        return result

    # ------------------------------------------------------------------
    # Scope helpers (shared by set() and _get())
    # ------------------------------------------------------------------

    def _resolve_scope(
        self, user_id: int | bool, company_id: int | bool
    ) -> tuple[int | bool, int | bool]:
        """Resolve the ``True`` sentinels to the current user / company ids."""
        if user_id is True:
            user_id = self.env.uid
        if company_id is True:
            company_id = self.env.company.id
        return user_id, company_id

    def _get_default_record(
        self,
        field_id: int,
        user_id: int | bool,
        company_id: int | bool,
        condition: str | bool,
    ) -> Self:
        """Return the single default row for an exact (field, user, company,
        condition) scope, or an empty recordset.
        """
        return self.search(
            [
                ("field_id", "=", field_id),
                ("user_id", "=", user_id),
                ("company_id", "=", company_id),
                ("condition", "=", condition),
            ],
            limit=1,
        )

    @api.model
    def set(
        self,
        model_name: str,
        field_name: str,
        value: Any,
        user_id: int | bool = False,
        company_id: int | bool = False,
        condition: str | bool = False,
    ) -> bool:
        """Set the default value for a field, replacing any entry for the same
        (field, user, company) scope. Stored JSON-encoded.

        :param model_name: technical name of the model owning the field
        :param field_name: name of the field to set a default for
        :param value: the default value (JSON-encoded for storage)
        :param user_id: ``False`` for all users, ``True`` for the current user,
                        or a user id
        :param company_id: ``False`` for all companies, ``True`` for the current
                           user's company, or a company id
        :param condition: optional opaque condition restricting applicability;
                          the client typically uses ``'key=val'`` form.
        """
        user_id, company_id = self._resolve_scope(user_id, company_id)

        # resolve the model and field, distinguishing an unknown field (KeyError)
        # from an unconvertible value (ValueError/TypeError) for a precise message
        try:
            model = self.env[model_name]
            orm_field = model._fields[field_name]
        except KeyError:
            raise ValidationError(
                self.env._(
                    "Invalid field %(model)s.%(field)s",
                    model=model_name,
                    field=field_name,
                )
            ) from None
        try:
            parsed = orm_field.convert_to_cache(value, model)
            stored_value = (
                orm_field.to_string(value)
                if orm_field.type in ("date", "datetime") and isinstance(value, date)
                else value
            )
            json_value = json.dumps(stored_value, ensure_ascii=False)
        except ValueError, TypeError:
            raise ValidationError(
                self.env._(
                    "Invalid value for %(model)s.%(field)s: %(value)s",
                    model=model_name,
                    field=field_name,
                    value=value,
                )
            ) from None
        if not self._fits_column(orm_field, parsed):
            raise ValidationError(
                self.env._(
                    "Invalid value for %(model)s.%(field)s: %(value)s is out of bounds (integers should be between -2,147,483,648 and 2,147,483,647)",
                    model=model_name,
                    field=field_name,
                    value=value,
                )
            )

        field = self.env["ir.model.fields"]._get(model_name, field_name)
        default = self._get_default_record(field.id, user_id, company_id, condition)
        if default:
            # avoid busting the cache when nothing actually changes
            if default.json_value != json_value:
                default.write({"json_value": json_value})
        else:
            self.create(
                {
                    "field_id": field.id,
                    "user_id": user_id,
                    "company_id": company_id,
                    "condition": condition,
                    "json_value": json_value,
                }
            )
        return True

    @api.model
    def _get(
        self,
        model_name: str,
        field_name: str,
        user_id: int | bool = False,
        company_id: int | bool = False,
        condition: str | bool = False,
    ) -> Any:
        """Return the default value for the given field, user and company, or
        ``None`` if no default is available.

        :param model_name: technical name of the model owning the field
        :param field_name: name of the field to read the default for
        :param user_id: ``False`` for all users, ``True`` for the current user,
                        or a user id
        :param company_id: ``False`` for all companies, ``True`` for the current
                           user's company, or a company id
        :param condition: optional opaque condition restricting applicability;
                          the client typically uses ``'key=val'`` form.
        """
        user_id, company_id = self._resolve_scope(user_id, company_id)
        field = self.env["ir.model.fields"]._get(model_name, field_name)
        default = self._get_default_record(field.id, user_id, company_id, condition)
        return json.loads(default.json_value) if default else None

    @api.model
    @tools.ormcache("self.env.uid", "self.env.company.id", "model_name", "condition")
    # ormcache invalidation is not needed when deleting a field, user or company
    # (those defaults will no longer be requested); only when a user's company
    # changes.
    def _get_model_defaults(
        self, model_name: str, condition: str | bool = False
    ) -> dict[str, Any]:
        """Return the available default values for the given model (for the
        current user), as a dict mapping field names to values.
        """
        cr = self.env.cr
        self.flush_model()
        # self.env.company is empty when there is no user (controllers with auth=None)
        company_id = self.env.company.id or None
        condition_clause = (
            tools.SQL("d.condition = %s", condition)
            if condition
            else tools.SQL("d.condition IS NULL")
        )
        # Priority: user-and-company specific > user > company > global. The
        # ``IS NOT NULL`` sort keys put the most specific row first explicitly,
        # not relying on PostgreSQL's default NULLS ordering.
        query = tools.SQL(
            """ SELECT f.name, d.json_value
                FROM ir_default d
                JOIN ir_model_fields f ON d.field_id=f.id
                WHERE f.model = %s
                    AND (d.user_id IS NULL OR d.user_id = %s)
                    AND (d.company_id IS NULL OR d.company_id = %s)
                    AND %s
                ORDER BY (d.user_id IS NOT NULL) DESC,
                         (d.company_id IS NOT NULL) DESC,
                         d.id
            """,
            model_name,
            self.env.uid,
            company_id,
            condition_clause,
        )
        cr.execute(query)
        result = {}
        for row in cr.fetchall():
            # keep the highest priority default for each field (first seen wins)
            if row[0] not in result:
                result[row[0]] = json.loads(row[1])
        return result

    @api.model
    def discard_records(self, records: Self) -> bool:
        """Discard all the defaults of many2one fields using any of the given
        records.
        """
        json_vals = [json.dumps(id) for id in records.ids]
        domain = [
            ("field_id.ttype", "=", "many2one"),
            ("field_id.relation", "=", records._name),
            ("json_value", "in", json_vals),
        ]
        return self.search(domain).unlink()

    @api.model
    def discard_values(self, model_name: str, field_name: str, values: list) -> bool:
        """Discard all the defaults for any of the given values."""
        field = self.env["ir.model.fields"]._get(model_name, field_name)
        json_vals = [json.dumps(value, ensure_ascii=False) for value in values]
        domain = [("field_id", "=", field.id), ("json_value", "in", json_vals)]
        return self.search(domain).unlink()

    @tools.ormcache("model_name", "field_name")
    def _get_field_column_fallbacks(self, model_name: str, field_name: str) -> str:
        # Use cr.execute directly instead of execute_query to avoid the
        # flush_query → _flush → _execute_update → _get_field_column_fallbacks
        # re-entrancy path that can leave cursor.description=None with psycopg3.
        cr = self.env.cr
        cr.execute("SELECT ARRAY_AGG(id) FROM res_company")
        company_ids = cr.fetchone()[0] or []
        field = self.env[model_name]._fields[field_name]
        self_super = self.with_user(SUPERUSER_ID)
        return json.dumps(
            {
                id_: field._to_json_value(
                    field.convert_to_column(
                        self_super.with_company(id_)
                        ._get_model_defaults(model_name)
                        .get(field_name),
                        self_super.with_company(id_),
                    )
                )
                for id_ in company_ids
            }
        )

    def _evaluate_condition_with_fallback(
        self, model_name: str, field_expr: str, operator: str, value: Any
    ) -> bool | None:
        """Evaluate whether a company-dependent field's fallback value satisfies the condition.

        :return: True if satisfied, False if not, None if unknown.
        :rtype: bool | None
        """
        field_name, _property_name = fields.parse_field_expr(field_expr)
        model = self.env[model_name]
        field = model._fields[field_name]
        fallback = field.get_company_dependent_fallback(model)
        try:
            record = model.new({field_name: field.convert_to_write(fallback, model)})
            return bool(record.filtered_domain(Domain(field_expr, operator, value)))
        except ValueError:
            return None
