import logging

from odoo.http import request

from odoo.addons.mail_plugin.controllers import mail_plugin

_logger = logging.getLogger(__name__)


class MailPluginController(mail_plugin.MailPluginController):
    def _get_contact_data(self, partner):
        contact_values = super()._get_contact_data(partner)

        if not request.env["project.task"].has_access("create"):
            return contact_values

        if not partner:
            contact_values["tasks"] = []
        else:
            partner_tasks = request.env["project.task"].search(
                [("partner_id", "=", partner.id)], offset=0, limit=5
            )

            accessible_projects = partner_tasks.project_id._filtered_access("read").ids

            tasks_values = [
                {
                    "task_id": task.id,
                    "name": task.name,
                    "project_name": task.project_id.name,
                }
                for task in partner_tasks
                if task.project_id.id in accessible_projects
            ]

            contact_values["tasks"] = tasks_values
            contact_values["can_create_project"] = request.env[
                "project.project"
            ].has_access("create")

        return contact_values

    def _mail_content_logging_models_whitelist(self):
        models_whitelist = super()._mail_content_logging_models_whitelist()
        if not request.env["project.task"].has_access("create"):
            return models_whitelist
        return models_whitelist + ["project.task"]

    def _translation_modules_whitelist(self):
        modules_whitelist = super()._translation_modules_whitelist()
        if not request.env["project.task"].has_access("create"):
            return modules_whitelist
        return modules_whitelist + ["project_mail_plugin"]
