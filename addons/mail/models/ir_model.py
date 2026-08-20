from typing import Any, Literal

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError


class IrModel(models.Model):
    _inherit = "ir.model"
    _order = "is_mail_thread DESC, name ASC"

    is_mail_thread = fields.Boolean(
        string="Has Mail Thread",
        default=False,
    )
    is_mail_activity = fields.Boolean(
        string="Has Mail Activity",
        default=False,
    )
    is_mail_blacklist = fields.Boolean(
        string="Has Mail Blacklist",
        default=False,
    )

    def unlink(self) -> Literal[True]:
        if not self:
            return True

        mail_models = self.search(
            [
                (
                    "model",
                    "in",
                    (
                        "mail.activity",
                        "mail.activity.type",
                        "mail.followers",
                        "mail.message",
                    ),
                )
            ],
            order="id",
        )

        if not (self & mail_models):
            models = list(self.mapped("model"))
            model_ids = list(self.ids)

            query = "DELETE FROM mail_activity WHERE res_model_id = ANY(%s)"
            self.env.cr.execute(query, [model_ids])

            query = "DELETE FROM mail_activity_type WHERE res_model = ANY(%s)"
            self.env.cr.execute(query, [models])

            query = "DELETE FROM mail_followers WHERE res_model = ANY(%s)"
            self.env.cr.execute(query, [models])

            query = "DELETE FROM mail_message WHERE model = ANY(%s)"
            self.env.cr.execute(query, [models])

        models = list(self.mapped("model"))
        query = """
            SELECT DISTINCT store_fname
            FROM ir_attachment
            WHERE res_model = ANY(%s)
            EXCEPT
            SELECT store_fname
            FROM ir_attachment
            WHERE res_model != ALL(%s);
        """
        self.env.cr.execute(query, [models, models])
        fnames = self.env.cr.fetchall()

        query = """DELETE FROM ir_attachment WHERE res_model = ANY(%s)"""
        self.env.cr.execute(query, [models])

        for (fname,) in fnames:
            self.env["ir.attachment"]._storage_delete(fname)

        return super().unlink()

    def write(self, vals: ValuesType) -> Literal[True]:
        if self and (
            "is_mail_thread" in vals
            or "is_mail_activity" in vals
            or "is_mail_blacklist" in vals
        ):
            if any(rec.state != "manual" for rec in self):
                raise UserError(_("Only custom models can be modified."))
            if "is_mail_thread" in vals and any(
                rec.is_mail_thread > vals["is_mail_thread"] for rec in self
            ):
                raise UserError(_('Field "Mail Thread" cannot be changed to "False".'))
            if "is_mail_activity" in vals and any(
                rec.is_mail_activity > vals["is_mail_activity"] for rec in self
            ):
                raise UserError(
                    _('Field "Mail Activity" cannot be changed to "False".')
                )
            if "is_mail_blacklist" in vals and any(
                rec.is_mail_blacklist > vals["is_mail_blacklist"] for rec in self
            ):
                raise UserError(
                    _('Field "Mail Blacklist" cannot be changed to "False".')
                )
            res = super().write(vals)
            self.env.flush_all()
            model_names = self.mapped("model")
            self.pool._setup_models__(self.env.cr, model_names)
            model_names = self.pool.descendants(model_names, "_inherits")
            self.pool.init_models(
                self.env.cr,
                model_names,
                dict(self.env.context, update_custom_fields=True),
            )
        else:
            res = super().write(vals)
        return res

    def _reflect_model_params(self, model: models.BaseModel) -> dict[str, Any]:
        vals = super()._reflect_model_params(model)
        vals["is_mail_thread"] = isinstance(model, self.pool["mixin.mail.thread"])
        vals["is_mail_activity"] = isinstance(model, self.pool["mixin.mail.activity"])
        vals["is_mail_blacklist"] = isinstance(
            model, self.pool["mixin.mail.thread.blacklist"]
        )
        return vals

    @api.model
    def _instantiate_attrs(self, model_data: dict) -> dict:
        attrs = super()._instantiate_attrs(model_data)
        if (
            model_data.get("is_mail_blacklist")
            and attrs["_name"] != "mixin.mail.thread.blacklist"
        ):
            parents = attrs.get("_inherit") or []
            parents = [parents] if isinstance(parents, str) else parents
            attrs["_inherit"] = parents + ["mixin.mail.thread.blacklist"]
            if attrs["_custom"]:
                attrs["_primary_email"] = "x_email"
        elif model_data.get("is_mail_thread") and attrs["_name"] != "mixin.mail.thread":
            parents = attrs.get("_inherit") or []
            parents = [parents] if isinstance(parents, str) else parents
            attrs["_inherit"] = parents + ["mixin.mail.thread"]
        if (
            model_data.get("is_mail_activity")
            and attrs["_name"] != "mixin.mail.activity"
        ):
            parents = attrs.get("_inherit") or []
            parents = [parents] if isinstance(parents, str) else parents
            attrs["_inherit"] = parents + ["mixin.mail.activity"]
        return attrs

    def _get_definitions(self, model_names: list[str]) -> dict:
        model_definitions = super()._get_definitions(model_names)
        for model_name, model_definition in model_definitions.items():
            model = self.env[model_name]
            tracked_field_names = (
                model._track_get_fields()
                if "mixin.mail.thread" in model._inherit
                else []
            )
            for fname in tracked_field_names:
                if fname in model_definition["fields"]:
                    model_definition["fields"][fname]["tracking"] = True
            if isinstance(
                self.env[model_name], self.env.registry["mixin.mail.activity"]
            ):
                model_definition["has_activities"] = True
        return model_definitions

    def _get_model_definitions(self, model_names_to_fetch: list[str]) -> dict:
        model_definitions = super()._get_model_definitions(model_names_to_fetch)
        for model_name, model_definition in model_definitions.items():
            model = self.env[model_name]
            tracked_field_names = (
                model._track_get_fields()
                if "mixin.mail.thread" in model._inherit
                else []
            )
            for fname, field in model_definition["fields"].items():
                if fname in tracked_field_names:
                    field["tracking"] = True
            if isinstance(
                self.env[model_name], self.env.registry["mixin.mail.activity"]
            ):
                model_definition["has_activities"] = True
        return model_definitions
