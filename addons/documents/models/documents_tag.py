from random import randint

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DocumentsTag(models.Model):
    """Tag used to classify documents."""

    _name = "documents.tag"
    _description = "Tag"
    _order = "sequence, name"

    @api.model
    def _get_default_color(self) -> int:
        return randint(1, 11)

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer("Sequence", default=10)
    color = fields.Integer("Color", default=_get_default_color)
    tooltip = fields.Char(
        help="Text shown when hovering on this tag", string="Tooltip"
    )  # Deprecated
    document_ids = fields.Many2many("documents.document", "document_tag_rel")

    @api.constrains("name")
    def _check_name_unique(self) -> None:
        """Enforce tag-name uniqueness in the *current* language.

        `name` is translated, i.e. stored as a jsonb document, so a SQL
        ``unique (name)`` constrained the whole JSON blob: two tags with the
        same English name but a different French one compared as distinct and
        both were accepted.
        """
        names = [name for name in self.mapped("name") if name]
        if not names:
            return
        duplicates = self.sudo().search(
            [("name", "in", names), ("id", "not in", self.ids)], limit=1
        )
        if duplicates or len(names) != len(set(names)):
            raise UserError(_("Tag name already used"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used_in_server_action(self) -> None:
        # Every tag is protected (not only data-file ones): build the references
        # straight from the ids rather than round-tripping through
        # ``_get_external_ids`` (an extra ir.model.data search whose keys are just
        # the record ids anyway).
        resource_refs = [f"documents.tag,{tag_id}" for tag_id in self.ids]
        if resource_refs and self.env["ir.actions.server"].search_count(
            [("resource_ref", "in", resource_refs)], limit=1
        ):
            raise UserError(_("You cannot delete tags used in server actions."))
