from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BaseModuleInstallRequest(models.Model):
    _name = "base.module.install.request"
    _inherit = ["mixin.mail.thread", "mixin.approval"]
    _description = "Module Activation Request"
    _rec_name = "module_id"
    _order = "create_date desc, id desc"

    module_id = fields.Many2one(
        "ir.module.module",
        string="Module",
        required=True,
        domain=[("state", "=", "uninstalled")],
        ondelete="cascade",
        readonly=True,
    )
    user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )
    user_ids = fields.Many2many(
        "res.users",
        string="Send to:",
        compute="_compute_user_ids",
    )
    body_html = fields.Html("Body")

    @api.depends("module_id")
    def _compute_user_ids(self):
        users = self.env.ref("base.group_system").all_user_ids
        self.user_ids = [(6, 0, users.ids)]

    def action_send_request(self):
        """Ask the system administrators through an approval request.

        This used to render a mail template to each of them and keep nothing:
        not who asked, not whether anybody answered, not what they said. The
        request is now the record of all three, and the engine's activities are
        what reach the administrators.
        """
        self.check_singleton()
        self.action_create_approval_request()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("Your request has been successfully sent"),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_open_install_review(self):
        """Open the dependency review that ends in the install.

        Installing is not done from the approval decision itself: it commits and
        replaces the registry, which would pull the rest of the decision out from
        under the request that is still being written. It stays one explicit
        click, as it was when the administrator followed the e-mail's link.
        """
        self.check_singleton()
        if self.approval_state != "approved":
            raise UserError(_("This activation request has not been approved."))
        return {
            **self.env["ir.actions.act_window"]._get_action_dict_by_xml_id(
                "base_install_request.action_base_module_install_review"
            ),
            "context": {"default_module_id": self.module_id.id},
        }

    def _get_domain_approval_category(self):
        category = self.env.ref(
            "base_install_request.approval_category_module_activation",
            raise_if_not_found=False,
        )
        return [("id", "=", category.id)] if category else []

    def _get_approval_request_name(self):
        return _('Activation of "%s"', self.module_id.shortdesc)

    def _get_approval_reason_html(self):
        return self.body_html or ""

    def _filter_approval_step_user_ids(self, step, user_ids):
        user_ids = super()._filter_approval_step_user_ids(step, user_ids)
        return user_ids - {self.user_id.id}

    def _on_approval_approved(self):
        super()._on_approval_approved()
        for request in self:
            request.message_post(
                body=_(
                    "Activation of %(module)s was approved. An administrator "
                    "installs it from this request.",
                    module=request.module_id.shortdesc,
                ),
                partner_ids=request.user_id.partner_id.ids,
                message_type="notification",
            )


class BaseModuleInstallReview(models.TransientModel):
    _name = "base.module.install.review"
    _description = "Module Activation Review"
    _rec_name = "module_id"

    module_id = fields.Many2one(
        "ir.module.module",
        string="Module",
        required=True,
        domain=[("state", "=", "uninstalled")],
        ondelete="cascade",
        readonly=True,
    )
    module_ids = fields.Many2many(
        "ir.module.module",
        string="Depending Apps",
        compute="_compute_module_ids",
    )
    modules_description = fields.Html(
        compute="_compute_modules_description",
    )

    @api.depends("module_id")
    def _compute_module_ids(self):
        for wizard in self:
            wizard.module_ids = wizard._get_depending_apps(wizard.module_id)

    @api.depends("module_ids")
    def _compute_modules_description(self):
        for wizard in self:
            wizard.modules_description = self.env["ir.qweb"]._render(
                "base_install_request.base_module_install_review_description",
                {"apps": wizard.module_ids},
            )

    @api.model
    def _get_depending_apps(self, module):
        if not module:
            raise UserError(_("No module selected."))
        if module.state == "installed":
            raise UserError(_("The module is already installed."))
        deps = module.upstream_dependencies()
        apps = module | deps.filtered(lambda d: d.application)
        for dep in deps:
            apps |= dep.upstream_dependencies()
        return apps

    def action_install_module(self):
        self.check_singleton()
        self.module_id.button_immediate_install()
        return {
            "type": "ir.actions.client",
            "tag": "home",
        }
