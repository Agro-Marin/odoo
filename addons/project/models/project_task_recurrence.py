from typing import Self

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskRecurrence(models.Model):
    _name = "project.task.recurrence"
    _description = "Task Recurrence"
    # `repeat_interval`, `repeat_unit`, `repeat_type` and `_get_recurrence_delta`
    # are the mixin's. A task's recurrence ends on a *day* the user picks, so
    # `repeat_until` stays a Date here and is declared below -- see the mixin
    # for why it does not own that field.
    _inherit = ["recurrence.rule.mixin"]

    task_ids = fields.One2many("project.task", "recurrence_id", copy=False)

    repeat_until = fields.Date(string="End Date")

    @api.constrains("repeat_type", "repeat_until")
    def _check_repeat_until_date(self) -> None:
        """Reject an 'until' recurrence that names no date, or a past one.

        The first half overlaps the mixin's ``_until_required_check`` on
        purpose, and the two are not redundant: the CHECK is the *invariant*,
        held by the database against a raw write or a bad migration, while this
        is the *error quality*. A CHECK surfaces as a ``CheckViolation`` from
        the INSERT, and callers here are entitled to a ``ValidationError``
        naming the field -- which is what
        ``test_recurrence_until_requires_valid_future_date`` pins.

        The second half no CHECK can express at all, because "today" moves.
        """
        today = fields.Date.today()
        if self.filtered(lambda t: t.repeat_type == "until" and not t.repeat_until):
            raise ValidationError(_("The end date is required for 'Until' recurrence."))
        if self.filtered(
            lambda t: (
                t.repeat_type == "until" and t.repeat_until and t.repeat_until < today
            )
        ):
            raise ValidationError(_("The end date should be in the future"))

    @api.model
    def _get_recurring_fields_to_copy(self) -> list[str]:
        return [
            "recurrence_id",
        ]

    @api.model
    def _get_recurring_fields_to_postpone(self) -> list[str]:
        return [
            "date_end",
        ]

    def _get_last_task_id_per_recurrence_id(self) -> dict[int, int]:
        return (
            {}
            if not self
            else {
                recurrence.id: max_task_id
                for recurrence, max_task_id in self.env["project.task"]
                .sudo()
                ._read_group(
                    [("recurrence_id", "in", self.ids)],
                    ["recurrence_id"],
                    ["id:max"],
                )
            }
        )

    @api.model
    def _create_next_occurrences(self, occurrences_from: Self) -> Self:
        tasks_copy = self.env["project.task"]

        def should_create_occurrence(task) -> bool:
            rec = task.recurrence_id.sudo()
            return (
                rec.repeat_type != "until"
                or not task.date_end
                or (
                    rec.repeat_until
                    # repeat_until is a naive user-calendar Date; date_end is a
                    # UTC Datetime. Compare in the user's timezone so a boundary
                    # occurrence isn't dropped (or kept) one day early in a
                    # non-UTC tz.
                    and fields.Datetime.context_timestamp(
                        rec, task.date_end + rec._get_recurrence_delta()
                    ).date()
                    <= rec.repeat_until
                )
            )

        occurrences_from = occurrences_from.filtered(should_create_occurrence)

        if occurrences_from:
            recurrence_by_task = {
                task: task.recurrence_id.sudo() for task in occurrences_from
            }
            tasks_copy = (
                self.env["project.task"]
                .sudo()
                .create(self._create_next_occurrences_values(recurrence_by_task))
                .sudo(False)
            )
            occurrences_from._resolve_copied_dependencies(tasks_copy)
        return tasks_copy

    @api.model
    def _create_next_occurrences_values(self, recurrence_by_task: dict) -> list[dict]:
        tasks = self.env["project.task"].concat(*recurrence_by_task.keys())
        list_create_values = []
        list_copy_data = (
            tasks.with_context(copy_project=True, active_test=False).sudo().copy_data()
        )
        # Read as sudo, like the copy above: a portal collaborator closing a
        # recurring task may write `state` but cannot read `recurrence_id`, and
        # `_read_format` yields False rather than raising -- which silently
        # detached every occurrence they created from its recurrence.
        list_fields_to_copy = tasks.sudo()._read_format(
            self._get_recurring_fields_to_copy()
        )
        list_fields_to_postpone = tasks.sudo()._read_format(
            self._get_recurring_fields_to_postpone()
        )

        for task, copy_data, fields_to_copy, fields_to_postpone in zip(
            tasks,
            list_copy_data,
            list_fields_to_copy,
            list_fields_to_postpone,
            strict=True,
        ):
            recurrence = recurrence_by_task[task]
            # `_read_format` always emits `id`; neither list may leak the source
            # task's id into the create values.
            fields_to_copy.pop("id", None)
            fields_to_postpone.pop("id", None)
            create_values = {
                "priority": "0",
                "step_id": (
                    task.sudo().project_id.workflow_step_ids[0].id
                    if task.sudo().project_id.workflow_step_ids
                    else task.step_id.id
                ),
                "child_ids": [
                    Command.create(vals)
                    for vals in self._create_next_occurrences_values(
                        dict.fromkeys(task.child_ids, recurrence)
                    )
                ],
            }
            create_values.update(
                {
                    field: value[0] if isinstance(value, tuple) else value
                    for field, value in fields_to_copy.items()
                }
            )
            create_values.update(
                {
                    field: value and value + recurrence._get_recurrence_delta()
                    for field, value in fields_to_postpone.items()
                }
            )
            copy_data.update(create_values)
            list_create_values.append(copy_data)

        return list_create_values
