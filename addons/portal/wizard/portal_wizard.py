from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize
from odoo.tools.translate import _


class PortalWizard(models.TransientModel):
    """Wizard for granting or revoking portal access on a set of partners."""

    _name = "portal.wizard"
    _description = "Grant Portal Access"

    def _default_partner_ids(self):
        partner_ids = self.env.context.get(
            "default_partner_ids", []
        ) or self.env.context.get("active_ids", [])
        # Dict used as ordered set: preserves browse order so wizard rows render
        # predictably (Python sets iterate in hash order, not insertion order).
        contact_ids = {}
        for partner in self.env["res.partner"].sudo().browse(partner_ids):
            contact_partners = (
                partner.child_ids.filtered(lambda p: p.type in ("contact", "other"))
                | partner
            )
            for contact_id in contact_partners.ids:
                contact_ids.setdefault(contact_id)

        return [Command.link(contact_id) for contact_id in contact_ids]

    partner_ids = fields.Many2many(
        "res.partner", string="Partners", default=_default_partner_ids
    )
    user_ids = fields.One2many(
        "portal.wizard.user",
        "wizard_id",
        string="Users",
        compute="_compute_user_ids",
        store=True,
        readonly=False,
    )
    welcome_message = fields.Text(
        "Invitation Message",
        help="This text is included in the email sent to new users of the portal.",
    )

    @api.depends("partner_ids")
    def _compute_user_ids(self):
        for portal_wizard in self:
            portal_wizard.user_ids = [
                Command.create(
                    {
                        "partner_id": partner.id,
                        "email": partner.email,
                    }
                )
                for partner in portal_wizard.partner_ids
            ]

    @api.model
    def action_open_wizard(self):
        """Create a ``portal.wizard`` and open its form modal.

        The wizard form embeds a one2many on ``portal.wizard.user``; per-row
        action buttons require persisted ids, so we create the wizard first
        and only then return the act_window descriptor.
        """
        portal_wizard = self.create({})
        return portal_wizard._action_open_modal()

    def _action_open_modal(self):
        """Return the act_window descriptor that re-opens this wizard's form modal."""
        return {
            "name": _("Portal Access Management"),
            "type": "ir.actions.act_window",
            "res_model": "portal.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }


class PortalWizardUser(models.TransientModel):
    """One row per partner inside the portal wizard's user list."""

    _name = "portal.wizard.user"
    _description = "Portal User Config"

    wizard_id = fields.Many2one(
        "portal.wizard", string="Wizard", required=True, ondelete="cascade"
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Contact",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    email = fields.Char("Email")

    user_id = fields.Many2one(
        "res.users", string="User", compute="_compute_user_id", compute_sudo=True
    )
    login_date = fields.Datetime(
        related="user_id.login_date", string="Latest Authentication"
    )
    is_portal = fields.Boolean("Is Portal", compute="_compute_group_details")
    is_internal = fields.Boolean("Is Internal", compute="_compute_group_details")
    email_state = fields.Selection(
        [("ok", "Valid"), ("ko", "Invalid"), ("exist", "Already Registered")],
        string="Status",
        compute="_compute_email_state",
    )

    @api.depends("email")
    def _compute_email_state(self):
        portal_users_with_email = self.filtered(
            lambda user: email_normalize(user.email)
        )
        (self - portal_users_with_email).email_state = "ko"

        existing_users = (
            self.env["res.users"]
            .with_context(active_test=False)
            .sudo()
            .search_read(
                self._get_similar_users_domain(portal_users_with_email),
                self._get_similar_users_fields(),
            )
        )
        for portal_user in portal_users_with_email:
            if any(
                self._is_portal_similar_than_user(user, portal_user)
                for user in existing_users
            ):
                portal_user.email_state = "exist"
            else:
                portal_user.email_state = "ok"

    @api.depends("partner_id")
    def _compute_user_id(self):
        for portal_wizard_user in self:
            user = portal_wizard_user.partner_id.with_context(
                active_test=False
            ).user_ids
            portal_wizard_user.user_id = user[0] if user else False

    @api.depends("user_id", "user_id.active", "user_id.group_ids")
    def _compute_group_details(self):
        for portal_wizard_user in self:
            user = portal_wizard_user.user_id

            # If a user was internal when archived, reusing
            # their user for portal should be done via settings
            if user and user._is_internal():
                portal_wizard_user.is_internal = True
                portal_wizard_user.is_portal = False
            elif user and user.active and user._is_portal():
                portal_wizard_user.is_internal = False
                portal_wizard_user.is_portal = True
            else:
                portal_wizard_user.is_internal = False
                portal_wizard_user.is_portal = False

    def action_grant_access(self):
        """Grant portal access to the partner.

        Creates a user (in the partner's company or the current company) if none
        exists, activates the user, and adds them to ``base.group_portal`` while
        removing ``base.group_public``. An invitation email is sent at the end.
        """
        self.ensure_one()
        self._assert_user_email_uniqueness()

        if self.is_portal or self.is_internal:
            raise UserError(
                _(
                    'The partner "%s" already has the portal access.',
                    self.partner_id.name,
                )
            )

        group_portal = self.env.ref("base.group_portal")
        group_public = self.env.ref("base.group_public")

        self._update_partner_email()
        user_sudo = self.user_id.sudo()

        if not user_sudo:
            # create a user if necessary and make sure it is in the portal group
            company = self.partner_id.company_id or self.env.company
            user_sudo = self.sudo().with_company(company.id)._create_user()

        # Users whose access was revoked are archived but kept in the portal
        # group, so re-granting only needs to reactivate them.
        user_sudo.write(
            {
                "active": True,
                "group_ids": [
                    Command.link(group_portal.id),
                    Command.unlink(group_public.id),
                ],
            }
        )
        # prepare for the signup process
        user_sudo.partner_id.signup_prepare()

        self.with_context(active_test=True)._send_email()

        return self.action_refresh_modal()

    def action_revoke_access(self):
        """Archive the portal user of the partner.

        The user is kept in ``group_portal``: ``group_public`` should only be
        used for automated tasks and guest interactions, never for a revoked
        portal user (which could otherwise be picked as a website's default
        public user).
        """
        self.ensure_one()
        if not self.is_portal:
            raise UserError(
                _(
                    'The partner "%s" has no portal access or is internal.',
                    self.partner_id.name,
                )
            )

        self._update_partner_email()

        # Remove the sign up token, so it can not be used
        self.partner_id.sudo().signup_type = None

        user_sudo = self.user_id.sudo()

        if user_sudo and user_sudo._is_portal():
            user_sudo.write({"active": False})

        return self.action_refresh_modal()

    def action_invite_again(self):
        """Re-send the invitation email to a partner that already has portal access."""
        self.ensure_one()
        self._assert_user_email_uniqueness()

        if not self.is_portal:
            raise UserError(
                _(
                    'You should first grant the portal access to the partner "%s".',
                    self.partner_id.name,
                )
            )

        self._update_partner_email()
        self.with_context(active_test=True)._send_email()

        return self.action_refresh_modal()

    def action_refresh_modal(self):
        """Re-open the wizard modal so users can chain actions.

        Used as the fallback action of email-state icon buttons — these must be
        non-disabled to fire mouse events for tooltips.
        """
        return self.wizard_id._action_open_modal()

    def _create_user(self):
        """Create a new ``res.users`` from the row's email + partner.

        :return: the new user record (in sudo)
        :rtype: res.users
        """
        return (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            ._create_user_from_template(
                {
                    "email": email_normalize(self.email),
                    "login": email_normalize(self.email),
                    "partner_id": self.partner_id.id,
                    "company_id": self.env.company.id,
                    "company_ids": [Command.set(self.env.company.ids)],
                }
            )
        )

    def _send_email(self):
        """Send the ``auth_signup.portal_set_password_email`` template to the new portal user."""
        self.ensure_one()

        template = self.env.ref(
            "auth_signup.portal_set_password_email", raise_if_not_found=False
        )
        if not template:
            raise UserError(
                _(
                    'The template "Portal: new user" not found for sending email to the portal user.'
                )
            )

        lang = self.user_id.sudo().lang
        partner = self.user_id.sudo().partner_id
        partner.signup_prepare()

        template.with_context(
            dbname=self.env.cr.dbname,
            lang=lang,
            welcome_message=self.wizard_id.welcome_message,
            medium="portalinvite",
        ).send_mail(self.user_id.id, force_send=True)

        return True

    def _assert_user_email_uniqueness(self):
        """Refuse to grant portal access when the email is invalid or already taken."""
        self.ensure_one()
        if self.email_state == "ko":
            raise UserError(
                _('The contact "%s" does not have a valid email.', self.partner_id.name)
            )
        if self.email_state == "exist":
            raise UserError(
                _(
                    'The contact "%s" has the same email as an existing user',
                    self.partner_id.name,
                )
            )

    def _update_partner_email(self):
        """Sync the partner's email with the wizard row when the row's email is valid and changed."""
        email_normalized = email_normalize(self.email)
        if (
            self.email_state == "ok"
            and email_normalize(self.partner_id.email) != email_normalized
        ):
            self.partner_id.write({"email": email_normalized})

    def _get_similar_users_domain(self, portal_users_with_email):
        """Return the domain finding users whose login matches one of the wizard rows' emails."""
        normalized_emails = [
            email_normalize(portal_user.email)
            for portal_user in portal_users_with_email
        ]
        return [("login", "in", normalized_emails)]

    def _get_similar_users_fields(self):
        """Field list ``search_read``-fetched by ``_compute_email_state``."""
        return ["id", "login"]

    def _is_portal_similar_than_user(self, user, portal_user):
        """Whether ``user`` (search_read dict) duplicates ``portal_user`` (recordset row)."""
        return (
            user["login"] == email_normalize(portal_user.email)
            and user["id"] != portal_user.user_id.id
        )
