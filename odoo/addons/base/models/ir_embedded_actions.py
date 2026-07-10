from ast import literal_eval
from typing import Self

from odoo import api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError


class IrEmbeddedActions(models.Model):
    _name = "ir.embedded.actions"
    _description = "Embedded Actions"
    _order = "sequence, id"

    name = fields.Char(translate=True)
    sequence = fields.Integer()
    parent_action_id = fields.Many2one(
        "ir.actions.act_window",
        string="Parent Action",
        required=True,
        ondelete="cascade",
    )
    parent_res_id = fields.Integer(string="Active Parent Id")
    parent_res_model = fields.Char(string="Active Parent Model", required=True)
    # It is required to have either action_id or python_method
    action_id = fields.Many2one(
        "ir.actions.actions",
        string="Action",
        ondelete="cascade",
    )
    python_method = fields.Char(help="Python method returning an action")
    user_id = fields.Many2one(
        "res.users",
        string="User",
        ondelete="cascade",
        help="User specific embedded action. If empty, shared embedded action",
    )
    is_deletable = fields.Boolean(compute="_compute_is_deletable")
    default_view_mode = fields.Char(
        string="Default View",
        help="Default view (if none, default view of the action is taken)",
    )
    filter_ids = fields.One2many(
        "ir.filters",
        "embedded_action_id",
        help="Default filter of the embedded action (if none, no filters)",
    )
    is_visible = fields.Boolean(
        string="Embedded visibility",
        compute="_compute_is_visible",
        help="Computed field to check if the record should be visible according to the domain",
    )
    domain = fields.Char(
        default="[]",
        help="Domain applied to the active id of the parent model",
    )
    context = fields.Char(
        default="{}",
        help="Context dictionary as Python expression, empty by default (Default: {})",
    )
    group_ids = fields.Many2many(
        "res.groups",
        help="Groups that can execute the embedded action. Leave empty to allow everybody.",
    )

    _check_only_one_action_defined = models.Constraint(
        """CHECK(
            (action_id IS NOT NULL AND python_method IS NULL)
            OR (action_id IS NULL AND python_method IS NOT NULL)
        )""",
        "Constraint to ensure that either an XML action or a python_method is defined, but not both.",
    )
    _check_python_method_requires_name = models.Constraint(
        "CHECK(NOT (python_method IS NOT NULL AND name IS NULL))",
        "Constraint to ensure that if a python_method is defined, then the name must also be defined.",
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create embedded actions, deriving a name and coercing the action XOR.

        An omitted ``name`` defaults to the linked ``action_id`` name. When a
        vals dict has both ``action_id`` and ``python_method``, the pair is
        silently coerced (not rejected) to satisfy the SQL CHECK: a truthy
        ``python_method`` wins, otherwise the falsy ``python_method`` is dropped.
        """
        # Default the name from the triggered action when action_id is given.
        action_ids = [
            v["action_id"] for v in vals_list if "name" not in v and "action_id" in v
        ]
        if action_ids:
            actions = self.env["ir.actions.actions"].browse(action_ids)
            action_names = {a.id: a.name for a in actions}
        else:
            action_names = {}
        for vals in vals_list:
            if "name" not in vals:
                vals["name"] = action_names.get(vals.get("action_id"), "")
            if "python_method" in vals and "action_id" in vals:
                if vals.get("python_method"):
                    # python_method supplies the action, so drop action_id.
                    del vals["action_id"]
                else:  # falsy python_method: drop it.
                    del vals["python_method"]
        return super().create(vals_list)

    def _compute_is_deletable(self) -> None:
        """Mark records not seeded from a data file as user-deletable."""
        # A record is deletable only if it has no external id, or all of its
        # external ids are __export__/__custom__ (i.e. not a seeded default).
        external_ids = self._get_external_ids()
        for record in self:
            record_external_ids = external_ids[record.id]
            record.is_deletable = all(
                ex_id.startswith(("__export__", "__custom__"))
                for ex_id in record_external_ids
            )

    @api.depends(
        "domain",
        "group_ids",
        "parent_res_model",
        "parent_res_id",
        "python_method",
        "user_id",
    )
    @api.depends_context("active_id", "active_model", "uid")
    def _compute_is_visible(self) -> None:
        """Compute per-user read-time visibility of each embedded action.

        Gated by the parent record matching the domain on the active id, by the
        user belonging to one of group_ids (if any), and by owner-or-shared
        scoping on user_id.
        """
        active_id = self.env.context.get("active_id", False)
        if not active_id:
            self.is_visible = False
            return
        # active_id identifies a record of the context's active_model: when
        # active_model is present, hide actions on any other parent_res_model to
        # avoid a cross-model id collision. Without active_model, match by id
        # alone (flows passing only active_id).
        active_model = self.env.context.get("active_model")
        domain_id = [("id", "=", active_id)]
        for parent_res_model, records in self.grouped("parent_res_model").items():
            if parent_res_model not in self.env or (
                active_model and parent_res_model != active_model
            ):
                records.is_visible = False
                continue
            parent_model = self.env[parent_res_model]
            active_model_record = parent_model.search(  # noqa: E8507 — bounded: one per distinct parent_res_model
                domain_id, order="id"
            )
            for record in records:
                action_groups = record.group_ids
                is_valid_method = not record.python_method or hasattr(
                    parent_model, record.python_method
                )
                if is_valid_method and (
                    not action_groups or (action_groups & self.env.user.all_group_ids)
                ):
                    try:
                        domain_model = literal_eval(record.domain or "[]")
                    except ValueError, SyntaxError:
                        record.is_visible = False
                        continue
                    # bool(): the last operand is a recordset — don't assign a
                    # recordset to the Boolean field via truthiness.
                    record.is_visible = bool(
                        record.parent_res_id in (False, active_id)
                        and record.user_id.id in (False, self.env.uid)
                        and active_model_record.filtered_domain(domain_model)
                    )
                else:
                    record.is_visible = False

    @api.ondelete(at_uninstall=False)
    def _unlink_if_action_deletable(self) -> None:
        """Prevent unlinking seeded (non-deletable) default embedded actions."""
        for record in self:
            if not record.is_deletable:
                raise UserError(
                    self.env._("You cannot delete a default embedded action")
                )

    def _get_readable_fields(self) -> set[str]:
        """Return the set of fields safe to read."""
        return {
            "name",
            "parent_action_id",
            "parent_res_id",
            "parent_res_model",
            "action_id",
            "python_method",
            "user_id",
            "is_deletable",
            "default_view_mode",
            "filter_ids",
            "domain",
            "context",
            "group_ids",
        }
