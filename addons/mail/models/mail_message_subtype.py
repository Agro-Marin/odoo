from typing import Literal, Self

from odoo import _, api, exceptions, fields, models, tools
from odoo.api import ValuesType


class MailMessageSubtype(models.Model):
    _name = "mail.message.subtype"
    _description = "Message subtypes"
    _order = "sequence, id"

    name = fields.Char(
        "Message Type",
        required=True,
        translate=True,
        help="Precise message type, mostly for system notifications (e.g. New, "
        "Stage change). Lets users fine-tune which notifications they receive.",
    )
    description = fields.Text(
        "Description",
        translate=True,
        prefetch=True,
        help="Description that will be added in the message posted for this "
        "subtype. If void, the name will be added instead.",
    )
    internal = fields.Boolean(
        "Internal Only",
        help="Messages with internal subtypes will be visible only by employees, aka members of base_user group",
    )
    parent_id: MailMessageSubtype = fields.Many2one(
        "mail.message.subtype",
        string="Parent",
        ondelete="set null",
        help="Parent subtype, used for automatic subscription (e.g. a project "
        "subtype's parent_id points to the related task subtype).",
    )
    relation_field = fields.Char(
        "Relation field",
        help="Field used to link the related model to the subtype model when "
        "using automatic subscription on a related document. The field "
        "is used to compute getattr(related_document.relation_field).",
    )
    res_model = fields.Char(
        "Model",
        help="Model the subtype applies to. If False, this subtype applies to all models.",
    )
    default = fields.Boolean(
        "Default", default=True, help="Activated by default when subscribing."
    )
    sequence = fields.Integer("Sequence", default=1, help="Used to order subtypes.")
    hidden = fields.Boolean("Hidden", help="Hide the subtype in the follower options")
    track_recipients = fields.Boolean(
        "Track Recipients",
        help="Whether to display all the recipients or only the important ones.",
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        self.env.registry.clear_cache()
        return super().create(vals_list)

    def write(self, vals: ValuesType) -> Literal[True]:
        self._check_master_data_config(vals)
        self.env.registry.clear_cache()
        return super().write(vals)

    def unlink(self) -> Literal[True]:
        self.env.registry.clear_cache()
        return super().unlink()

    def _check_master_data_config(self, vals: ValuesType) -> None:
        """Refuse to unpin the configuration the master subtypes are relied on for."""
        model_info = self._get_model_info_by_xmlid()
        pinned_fnames = {fname for pinned in model_info.values() for fname in pinned}
        if not pinned_fnames & vals.keys():
            return
        modified = self.browse()
        for xml_id, pinned in model_info.items():
            subtype = self.env.ref(xml_id, raise_if_not_found=False)
            if not subtype or subtype not in self:
                continue
            if any(
                # beware of '' vs False for a void res_model
                (vals[fname] or False) != (value or False)
                for fname, value in pinned.items()
                if fname in vals
            ):
                modified += subtype
        if modified:
            raise exceptions.UserError(
                _(
                    "You cannot modify %(subtype_names)s as their configuration is required in various apps.",
                    subtype_names=", ".join(subtype.name for subtype in modified),
                )
            )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_master_data(self) -> None:
        master_data = self.browse()
        for xml_id in self._get_model_info_by_xmlid():
            subtype = self.env.ref(xml_id, raise_if_not_found=False)
            if subtype and subtype in self:
                master_data += subtype
        if master_data:
            raise exceptions.UserError(
                _(
                    "You cannot delete %(subtype_names)s as they are required in various apps.",
                    subtype_names=", ".join(subtype.name for subtype in master_data),
                )
            )

    @api.model
    def _get_model_info_by_xmlid(self) -> dict:
        """Configuration the master subtypes must keep: every chatter reads them.

        'comment' backs 'Send a message' and must stay model agnostic and
        readable by portal users; 'note' backs 'Log a note' and must stay model
        agnostic and internal; 'activities' is posted when marking an activity
        as done, where only the model matters.
        """
        return {
            "mail.mt_comment": {"res_model": False, "internal": False},
            "mail.mt_note": {"res_model": False, "internal": True},
            "mail.mt_activities": {"res_model": False},
        }

    @tools.ormcache("model_name")
    def _get_auto_subscription_subtypes(self, model_name: str) -> tuple:
        child_ids, def_ids = [], []
        all_int_ids = []
        parent, relation = {}, {}
        subtypes = self.sudo().search(
            [
                "|",
                "|",
                ("res_model", "=", False),
                ("res_model", "=", model_name),
                ("parent_id.res_model", "=", model_name),
            ]
        )
        for subtype in subtypes:
            if not subtype.res_model or subtype.res_model == model_name:
                child_ids += subtype.ids
                if subtype.default:
                    def_ids += subtype.ids
            if subtype.relation_field:
                parent[subtype.id] = subtype.parent_id.id
                relation.setdefault(subtype.res_model, set()).add(
                    subtype.relation_field
                )
            if subtype.internal:
                all_int_ids += subtype.ids
        return child_ids, def_ids, all_int_ids, parent, relation

    @api.model
    def default_subtypes(self, model_name: str) -> tuple:
        subtype_ids, internal_ids, external_ids = self._default_subtypes(model_name)
        return (
            self.browse(subtype_ids),
            self.browse(internal_ids),
            self.browse(external_ids),
        )

    @tools.ormcache("self.env.uid", "self.env.su", "model_name")
    def _default_subtypes(self, model_name: str) -> tuple:
        domain = [
            ("default", "=", True),
            "|",
            ("res_model", "=", model_name),
            ("res_model", "=", False),
        ]
        subtypes = self.search(domain)
        if not self.env.su and self.env.user.share:
            subtypes = self.sudo().search(domain)
        internal = subtypes.filtered("internal")
        return subtypes.ids, internal.ids, (subtypes - internal).ids
