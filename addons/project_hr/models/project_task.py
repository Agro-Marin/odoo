from odoo import api, fields, models
from odoo.tools import LazyTranslate

_lt = LazyTranslate(__name__)


class ProjectTask(models.Model):
    """Extend project.task to use hr.employee as primary assignee identity.

    employee_ids replaces user_ids as the field users interact with.
    user_ids is demoted to a computed stored field derived from
    employee_ids.user_id, so IR security rules and portal machinery
    keep working without modification.
    """

    _name = "project.task"
    _inherit = ["hr.mixin", "project.task"]

    employee_ids = fields.Many2many(
        "hr.employee",
        relation="project_task_employee_rel",
        column1="task_id",
        column2="employee_id",
        string="Assignees",
        tracking=True,
        default=lambda self: self._default_employee_ids(),
        falsy_value_label=_lt("👤 Unassigned"),
    )

    # Derived from employee_ids; stored so IR rules, portal_user_names, and
    # any third-party module that reads user_ids continue to work correctly.
    user_ids = fields.Many2many(
        "res.users",
        relation="project_task_user_rel",
        column1="task_id",
        column2="user_id",
        compute="_compute_user_ids",
        store=True,
        readonly=True,
        # Override parent's tracking=True and default=_default_user_ids.
        tracking=False,
        default=None,
    )

    @api.model
    def _default_employee_ids(self):
        """Default to the current user's employee for personal tasks only.

        Mirrors _default_user_ids logic: only assign a default when creating
        a task with a personal stage context (Inbox, Today, etc.).
        """
        if any(
            key in self.env.context
            for key in (
                "default_triage_ids",
                "default_triage_id",
            )
        ):
            return self.env["hr.employee"].search(
                [
                    ("user_id", "=", self.env.uid),
                    ("company_id", "=", self.env.company.id),
                ],
                limit=1,
            )
        return self.env["hr.employee"]

    @api.depends("employee_ids")
    def _compute_user_ids(self):
        """Sync user_ids from the assigned employees."""
        for task in self:
            task.user_ids = task.employee_ids.user_id

    @api.model_create_multi
    def create(self, vals_list):
        """Set date_assign when employee_ids are provided at creation.

        Core create() sets date_assign based on user_ids in vals. Since
        user_ids is now computed and never present in vals, we set it here.
        """
        tasks = super().create(vals_list)
        now = fields.Datetime.now()
        for task in tasks:
            if task.employee_ids and not task.date_assign:
                task.sudo().date_assign = now
        return tasks

    # ------------------------------------------------------------------
    # Resource reservation contracts (override of core project.task)
    # ------------------------------------------------------------------

    def _get_reservation_vals_list(self):
        """Resolve resources directly from the assigned employees.

        Core ``project.task`` walks ``user_ids → user → employee → resource``
        and rebinds each user to their own company so the lookup works
        cross-company.  Here ``employee_ids`` is the canonical assignee
        field, so the chain collapses to ``employee.resource_id`` —
        already company-scoped, no rebind needed.
        """
        self.ensure_one()
        start_field, end_field = self._get_reservation_date_fields()
        if not start_field or not end_field:
            return []
        date_start = self[start_field]
        date_end = self[end_field]
        if not date_start or not date_end:
            return []

        vals_list = []
        for employee in self.employee_ids:
            resource = employee.resource_id
            if not resource:
                continue
            vals_list.append(
                {
                    "name": self.display_name,
                    "date_start": date_start,
                    "date_end": date_end,
                    "resource_id": resource.id,
                    "allocated_percentage": self.allocated_percentage or 100.0,
                    "enforcement_mode": "soft",
                }
            )
        return vals_list

    def _get_sync_trigger_fields(self):
        """``employee_ids`` is the writeable field; ``user_ids`` is computed."""
        triggers = super()._get_sync_trigger_fields()
        triggers.discard("user_ids")
        triggers.add("employee_ids")
        return triggers

    def write(self, vals):
        """Mirror date_assign and personal stage logic for employee_ids changes.

        Core project.task.write() handles both behaviors for 'user_ids in vals'.
        Since user_ids is now computed, those branches never fire on user
        actions — we replicate them here for employee_ids.
        """
        now = fields.Datetime.now()
        task_ids_without_employee: set[int] = set()
        if "employee_ids" in vals and "date_assign" not in vals:
            task_ids_without_employee = {
                task.id for task in self if not task.employee_ids
            }

        result = super().write(vals)

        if "employee_ids" in vals:
            # Create missing triage buckets (Inbox, Today, etc.) for new assignees.
            self._populate_missing_triages()
            # Update date_assign: clear when unassigned, set when first assigned.
            for task in self.sudo():
                if not task.employee_ids and task.date_assign:
                    task.date_assign = False
                elif task.id in task_ids_without_employee:
                    task.date_assign = now

        return result
