# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import SUPERUSER_ID, api, models, modules
from odoo.tools import clean_context

TODO_SUBKEY = "todo"


class ResUsers(models.Model):
    _name = 'res.users'
    _inherit = 'res.users'

    @api.model
    def _activity_bucket_subkeys(self, model_name, res_ids):
        """Split the systray's ``project.task`` entry into "Task" and "To-Do".

        A to-do *is* a ``project.task`` with no project, so the base's one
        group per model would count both together.
        """
        if model_name != 'project.task':
            return super()._activity_bucket_subkeys(model_name, res_ids)
        tasks = self.env['project.task'].browse(res_ids).with_context(active_test=False)
        return {task.id: TODO_SUBKEY for task in tasks if not task.project_id}

    @api.model
    def _apply_activity_bucket_subkey(self, group, model_name, subkey, res_ids):
        group = super()._apply_activity_bucket_subkey(group, model_name, subkey, res_ids)
        if model_name != 'project.task':
            return group
        is_todo = subkey == TODO_SUBKEY
        group['name'] = self.env._("To-Do") if is_todo else self.env._("Task")
        group['is_todo'] = is_todo
        group['icon'] = modules.Manifest.for_addon(
            'project_todo' if is_todo else 'project'
        ).icon
        # Plain id membership, like the base's own group domain, but narrowed:
        # both halves share project.task's domain and would otherwise open the
        # same list. A traversal through ``activity_ids`` would re-apply that
        # comodel's active test and silently drop records the badge counted.
        group['domain'] = [
            ('active', 'in', [True, False]),
            ('id', 'in', res_ids),
        ]
        return group

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
