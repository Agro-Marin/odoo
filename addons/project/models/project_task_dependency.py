"""Extended task dependency model supporting all four PMI relationship types.

PMI defines four logical relationships between activities:
- FS (Finish-to-Start): B cannot start until A finishes (most common)
- SS (Start-to-Start): B cannot start until A starts
- FF (Finish-to-Finish): B cannot finish until A finishes
- SF (Start-to-Finish): B cannot finish until A starts (rare)

This model enriches the existing M2M (predecessor_ids/successor_ids) with
dependency_type and lag_hours. The M2M remains the backbone for backward
compatibility; this model adds metadata for advanced scheduling.
"""

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskDependency(models.Model):
    """A typed dependency between two tasks with optional lag."""

    _name = "project.task.dependency"
    _description = "Task Dependency"
    _order = "id"
    _rec_name = "display_name"

    task_id = fields.Many2one(
        "project.task",
        string="Dependent Task",
        required=True,
        ondelete="cascade",
        index=True,
        help="The task that is blocked or constrained.",
    )
    depends_on_id = fields.Many2one(
        "project.task",
        string="Predecessor Task",
        required=True,
        ondelete="cascade",
        index=True,
        help="The task that must complete (or start) first.",
    )
    dependency_type = fields.Selection(
        [
            ("fs", "Finish-to-Start"),
            ("ss", "Start-to-Start"),
            ("ff", "Finish-to-Finish"),
            ("sf", "Start-to-Finish"),
        ],
        string="Type",
        default="fs",
        required=True,
        help=(
            "FS: B waits for A to finish (default). "
            "SS: B waits for A to start. "
            "FF: B cannot finish until A finishes. "
            "SF: B cannot finish until A starts."
        ),
    )
    lag_hours = fields.Float(
        "Lag (hours)",
        default=0.0,
        help="Delay after the dependency condition is met. Negative = lead time.",
    )
    # Denormalized project for domain filtering
    project_id = fields.Many2one(
        related="task_id.project_id",
        store=True,
        index=True,
    )

    _unique_dependency = models.Constraint(
        "UNIQUE(task_id, depends_on_id)",
        "A dependency between these two tasks already exists.",
    )
    _no_self_dependency = models.Constraint(
        "CHECK(task_id != depends_on_id)",
        "A task cannot depend on itself.",
    )

    @api.depends("task_id", "depends_on_id", "dependency_type")
    def _compute_display_name(self) -> None:
        type_labels = dict(self._fields["dependency_type"].selection)
        for dep in self:
            dep.display_name = (
                f"{dep.depends_on_id.display_name} -> "
                f"{dep.task_id.display_name} "
                f"({type_labels.get(dep.dependency_type, 'FS')})"
            )

    @api.constrains("task_id", "depends_on_id")
    def _check_no_cycle(self) -> None:
        """Prevent circular dependencies via the typed dependency model.

        Builds the predecessor→successor adjacency once (single query) and
        traverses it in memory, instead of issuing one ``search`` per graph
        node per dependency (a query storm on deep/wide graphs).
        """
        # depends_on_id -> [task_id, ...]: "tasks that depend on this one".
        # Raw read bypasses ORM auto-flush, so flush the endpoints first.
        self.flush_model(["task_id", "depends_on_id"])
        self.env.cr.execute("SELECT depends_on_id, task_id FROM project_task_dependency")
        downstream: dict[int, list[int]] = defaultdict(list)
        for depends_on_id, task_id in self.env.cr.fetchall():
            downstream[depends_on_id].append(task_id)
        for dep in self:
            target = dep.depends_on_id.id
            visited: set[int] = set()
            stack = [dep.task_id.id]
            while stack:
                current = stack.pop()
                if current == target:
                    # Reached depends_on_id by following successors of task_id —
                    # this dependency closes a cycle.
                    raise ValidationError(
                        _("Adding this dependency would create a circular reference.")
                    )
                if current in visited:
                    continue
                visited.add(current)
                stack.extend(downstream.get(current, ()))

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> ProjectTaskDependency:
        """Sync new typed dependencies to the M2M predecessor_ids."""
        records = super().create(vals_list)
        records._sync_to_m2m()
        return records

    def write(self, vals: dict) -> bool:
        """Keep the backing M2M in sync when a dependency's endpoints move.

        ``create``/``unlink`` cover their own cases; without this, editing an
        existing dependency's ``task_id``/``depends_on_id`` would leave the old
        ``predecessor_ids`` link in place and never add the new one, so the
        blocked-state computation would track the wrong predecessor.
        """
        remap = "task_id" in vals or "depends_on_id" in vals
        old_pairs = (
            [(dep.task_id, dep.depends_on_id) for dep in self] if remap else []
        )
        res = super().write(vals)
        if remap:
            for (old_task, old_pred), dep in zip(old_pairs, self, strict=True):
                if dep.task_id == old_task and dep.depends_on_id == old_pred:
                    continue
                if old_pred in old_task.predecessor_ids:
                    old_task.write(
                        {"predecessor_ids": [fields.Command.unlink(old_pred.id)]}
                    )
                dep._sync_to_m2m()
        return res

    def unlink(self) -> bool:
        """Remove from M2M when typed dependency is deleted."""
        for dep in self:
            dep.task_id.write(
                {
                    "predecessor_ids": [fields.Command.unlink(dep.depends_on_id.id)],
                }
            )
        return super().unlink()

    def _sync_to_m2m(self) -> None:
        """Ensure the legacy M2M predecessor_ids reflects typed dependencies."""
        for dep in self:
            if dep.depends_on_id not in dep.task_id.predecessor_ids:
                dep.task_id.write(
                    {
                        "predecessor_ids": [fields.Command.link(dep.depends_on_id.id)],
                    }
                )
