# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import SUPERUSER_ID, api, fields, models, modules
from odoo.tools import clean_context

# One row per task, so the caller can drop the ones the user may not read
# before any counting happens. The earliest deadline decides the bucket, which
# reproduces the base implementation's "overdue beats today beats planned"
# precedence over a record's activities.
_TASK_ACTIVITY_QUERY = """
    SELECT t.project_id IS NOT NULL AS is_task,
           act.res_id AS res_id,
           CASE
               WHEN MIN(act.date_deadline) < %(today)s THEN 'overdue'
               WHEN MIN(act.date_deadline) = %(today)s THEN 'today'
               ELSE 'planned'
           END AS state
      FROM mail_activity AS act
      JOIN project_task AS t ON t.id = act.res_id
     WHERE act.res_model = 'project.task'
       AND act.user_id = %(user_id)s
       AND act.active
     GROUP BY is_task, act.res_id
     ORDER BY act.res_id DESC
     LIMIT %(limit)s
"""


class ResUsers(models.Model):
    _name = 'res.users'
    _inherit = 'res.users'

    @api.model
    def _get_activity_groups(self):
        """Split the systray's ``project.task`` entry into "Task" and "To-Do".

        The base implementation emits one group per model, but a to-do *is* a
        ``project.task`` with no project, so both would be counted together.
        Drop the base group and rebuild the two halves from a single query.

        The base guarantees three things this override has to reproduce rather
        than inherit, because it no longer goes through ``search``: the
        ``mail.activity.systray.limit`` cap, ``exists()`` against rows lost to
        a database cascade, and record-rule filtering. A group whose badge
        counts a record the user cannot read is a badge that opens an empty
        list.
        """
        activity_groups = [
            group for group in super()._get_activity_groups()
            if group.get('model') != 'project.task'
        ]

        limit = self.env['ir.config_parameter']._get_int_param(
            'mail.activity.systray.limit', 1000
        )
        self.env.cr.execute(_TASK_ACTIVITY_QUERY, {
            'today': fields.Date.context_today(self),
            'user_id': self.env.uid,
            'limit': limit,
        })
        state_by_res_id = {
            row['res_id']: (row['is_task'], row['state'])
            for row in self.env.cr.dictfetchall()
        }
        if not state_by_res_id:
            return activity_groups

        Task = self.env['project.task']
        if Task.has_access('read'):
            # exists() also drops rows the database cascaded away under us.
            readable = Task.browse(state_by_res_id).exists()._filtered_access('read')
        else:
            readable = Task

        buckets = {}
        for task_id in readable._ids:
            is_task, state = state_by_res_id[task_id]
            bucket = buckets.setdefault(is_task, {
                'res_ids': [],
                'overdue_count': 0, 'today_count': 0, 'planned_count': 0, 'due_count': 0,
            })
            bucket['res_ids'].append(task_id)
            bucket[f'{state}_count'] += 1
            if state in ('overdue', 'today'):
                bucket['due_count'] += 1

        model_id = self.env['ir.model']._get('project.task').id
        view_type = Task._systray_view
        # Emit in a fixed order: both groups carry the same ``id`` (the
        # project.task ir.model), so the client's sort-by-id is a tie and would
        # otherwise inherit whatever order the query happened to return.
        for is_task, module_name, name in (
            (True, 'project', self.env._("Task")),
            (False, 'project_todo', self.env._("To-Do")),
        ):
            bucket = buckets.get(is_task)
            if not bucket:
                continue
            activity_groups.append({
                'id': model_id,
                'name': name,
                'is_todo': not is_task,
                'model': 'project.task',
                'type': 'activity',
                'icon': modules.Manifest.for_addon(module_name).icon,
                # Plain id membership, like every other systray group: a
                # traversal through ``activity_ids`` would re-apply that
                # comodel's own active test and silently drop records the
                # badge just counted.
                'domain': [
                    ('active', 'in', [True, False]),
                    ('id', 'in', bucket['res_ids']),
                ],
                'due_count': bucket['due_count'],
                'today_count': bucket['today_count'],
                'overdue_count': bucket['overdue_count'],
                'planned_count': bucket['planned_count'],
                'view_type': view_type,
            })

        return activity_groups

    def _onboard_users_into_project(self, users):
        res = super()._onboard_users_into_project(users)
        if res:
            res._generate_onboarding_todo()
        return res

    def _generate_onboarding_todo(self):
        create_vals = []
        for user in self:
            self_lang = self.with_context(lang=user.lang or self.env.user.lang)
            body = self_lang.env["ir.qweb"]._render(
                "project_todo.todo_user_onboarding",
                {"object": user},
                minimal_qcontext=True,
                raise_if_not_found=False
            )
            if not body:
                continue
            title = self_lang.env._("Welcome %s!", user.name)
            create_vals.append({
                "user_ids": user.ids,
                "description": body,
                "name": title,
            })
        if create_vals:
            # clean_context, not a bare dict: the onboarding to-do must not
            # inherit a ``default_project_id`` from whatever created the user,
            # but it does want the environment's language and company scope.
            self.env["project.task"].with_user(SUPERUSER_ID).with_context(
                clean_context(self.env.context),
                mail_auto_subscribe_no_notify=True,
            ).create(create_vals)
