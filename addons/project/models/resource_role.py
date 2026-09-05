from odoo import fields, models


class ResourceRole(models.Model):
    _inherit = "resource.role"

    # The role model lives in `resource` (it is shared with the reservation
    # side), but only `project` knows what a project user is, so the team it
    # dispatches to is declared here.
    user_ids = fields.Many2many(
        "res.users",
        "resource_role_res_users_rel",
        "role_id",
        "user_id",
        string="Team Members",
        domain=lambda self: [
            ("all_group_ids", "=", self.env.ref("project.group_project_user").id)
        ],
        help="Users who normally take this role.  Creating a project from a "
        "template proposes them for the tasks that carry the role.",
    )
