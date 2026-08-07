import json
from datetime import date
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import SUPERUSER_ID, ValuesType
from odoo.exceptions import ValidationError
from odoo.fields import Domain

INT4_MIN = -(2**31)
INT4_MAX = 2**31 - 1


class IrDefault(models.Model):
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
        help="If set, this default only applies for this user.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        ondelete="cascade",
        index=True,
        help="If set, this default only applies for this company",
    )
    condition = fields.Char(
        "Condition",
        help="If set, applies the default upon condition.",
    )
    json_value = fields.Char("Default Value (JSON format)", required=True)

    _unique_scope = models.UniqueIndex(
        "(field_id, COALESCE(user_id, 0), COALESCE(company_id, 0),"
        " COALESCE(condition, ''))"
    )

    @staticmethod
    def _fits_column(field, parsed: Any) -> bool:
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
        if self.env.su:
            return
        for record in self:
            if field := record.field_id:
                model = self.env[field.model]
                model._check_field_access(model._fields[field.name], "write")

    def _invalidate_defaults_cache(self) -> None:
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

    def _resolve_scope(
        self, user_id: int | bool, company_id: int | bool
    ) -> tuple[int | bool, int | bool]:
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
        user_id, company_id = self._resolve_scope(user_id, company_id)

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
        user_id, company_id = self._resolve_scope(user_id, company_id)
        field = self.env["ir.model.fields"]._get(model_name, field_name)
        default = self._get_default_record(field.id, user_id, company_id, condition)
        return json.loads(default.json_value) if default else None

    @api.model
    @tools.ormcache("self.env.uid", "self.env.company.id", "model_name", "condition")
    def _get_model_defaults(
        self, model_name: str, condition: str | bool = False
    ) -> dict[str, Any]:
        cr = self.env.cr
        self.flush_model()
        company_id = self.env.company.id or None
        condition_clause = (
            tools.SQL("d.condition = %s", condition)
            if condition
            else tools.SQL("d.condition IS NULL")
        )
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
            if row[0] not in result:
                result[row[0]] = json.loads(row[1])
        return result

    @api.model
    def discard_records(self, records: Self) -> bool:
        json_vals = [json.dumps(id) for id in records.ids]
        domain = [
            ("field_id.ttype", "=", "many2one"),
            ("field_id.relation", "=", records._name),
            ("json_value", "in", json_vals),
        ]
        return self.search(domain).unlink()

    @api.model
    def discard_values(self, model_name: str, field_name: str, values: list) -> bool:
        field = self.env["ir.model.fields"]._get(model_name, field_name)
        json_vals = [json.dumps(value, ensure_ascii=False) for value in values]
        domain = [("field_id", "=", field.id), ("json_value", "in", json_vals)]
        return self.search(domain).unlink()

    @tools.ormcache("model_name", "field_name")
    def _get_field_column_fallbacks(self, model_name: str, field_name: str) -> str:
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
        field_name, _property_name = fields.parse_field_expr(field_expr)
        model = self.env[model_name]
        field = model._fields[field_name]
        fallback = field.get_company_dependent_fallback(model)
        try:
            record = model.new({field_name: field.convert_to_write(fallback, model)})
            return bool(record.filtered_domain(Domain(field_expr, operator, value)))
        except ValueError:
            return None
