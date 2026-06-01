from odoo import _, api, fields, models


class PortalShare(models.TransientModel):
    """Wizard for sharing a portal-exposed record with one or more partners by email."""

    _name = "portal.share"
    _description = "Portal Sharing"

    @api.model
    def default_get(self, fields):
        """Pre-fill ``res_model`` / ``res_id`` from the active record context.

        ``share_link`` is recomputed on read via ``_compute_share_link`` — no
        need to seed it here.
        """
        result = super().default_get(fields)
        result["res_model"] = self.env.context.get("active_model", False)
        result["res_id"] = self.env.context.get("active_id", False)
        return result

    @api.model
    def _selection_target_model(self):
        """Selection limited to concrete models that inherit ``portal.mixin``.

        Models outside that hierarchy have no ``access_url`` / ``access_token``,
        so the wizard's ``share_link`` would always come back empty for them.
        """
        portal_mixin_cls = self.pool["portal.mixin"]
        return [
            (model.model, model.name)
            for model in self.env["ir.model"].sudo().search([])
            if model.model in self.env
            and isinstance(self.env[model.model], portal_mixin_cls)
            and not self.env[model.model]._abstract
        ]

    res_model = fields.Char("Related Document Model", required=True)
    res_id = fields.Integer("Related Document ID", required=True)
    resource_ref = fields.Reference(
        "_selection_target_model", "Related Document", compute="_compute_resource_ref"
    )
    partner_ids = fields.Many2many("res.partner", string="Recipients", required=True)
    note = fields.Text(help="Add extra content to display in the email")
    share_link = fields.Char(string="Link", compute="_compute_share_link")
    access_warning = fields.Text("Access warning", compute="_compute_access_warning")

    @api.depends("res_model", "res_id")
    def _compute_resource_ref(self):
        for wizard in self:
            if wizard.res_model and wizard.res_id and wizard.res_model in self.env:
                wizard.resource_ref = f"{wizard.res_model},{wizard.res_id}"
            else:
                wizard.resource_ref = None

    def _get_portal_record(self):
        """Return the active record if it is a ``portal.mixin`` instance, else an empty recordset.

        Shared helper for ``_compute_share_link`` and ``_compute_access_warning``.
        """
        self.ensure_one()
        if not self.res_model or self.res_model not in self.env:
            return None
        res_model = self.env[self.res_model]
        if isinstance(res_model, self.pool["portal.mixin"]) and self.res_id:
            return res_model.browse(self.res_id)
        return None

    @api.depends("res_model", "res_id")
    def _compute_share_link(self):
        for rec in self:
            record = rec._get_portal_record()
            rec.share_link = (
                record.get_base_url() + record._get_share_url(redirect=True)
                if record
                else False
            )

    @api.depends("res_model", "res_id")
    def _compute_access_warning(self):
        for rec in self:
            record = rec._get_portal_record()
            rec.access_warning = record.access_warning if record else False

    def _post_share_email(self, partner, share_link):
        """Post the portal share template to ``partner`` in their preferred language.

        Single source of truth for the share-mail payload — ``_send_public_link``
        and ``_send_signup_link`` differ only in how they compute ``share_link``.
        """
        self.resource_ref.with_context(lang=partner.lang).message_post_with_source(
            "portal.portal_share_template",
            render_values={
                "partner": partner,
                "note": self.note,
                "record": self.resource_ref,
                "share_link": share_link,
                "model_description": self.env["ir.model"]
                ._get(self.resource_ref._name)
                .display_name.lower(),
            },
            subject=_("Invitation to access %s", self.resource_ref.display_name),
            subtype_xmlid="mail.mt_note",
            email_layout_xmlid="mail.mail_notification_light",
            partner_ids=partner.ids,
        )

    def _send_public_link(self, partners=None):
        """Send the per-record share link with an HMAC-signed pid to each partner.

        Used when the recipient already has portal access or the record carries
        an ``access_token`` — no signup involved.
        """
        if partners is None:
            partners = self.partner_ids
        for partner in partners:
            share_link = (
                self.resource_ref.get_base_url()
                + self.resource_ref._get_share_url(redirect=True, pid=partner.id)
            )
            self._post_share_email(partner, share_link)

    def _send_signup_link(self, partners=None):
        """Send a signup-bearing share link to partners who do not yet have a user.

        After clicking, the recipient lands on the signup page pre-bound to the
        target record (model + res_id) so they continue into the portal seamlessly.
        """
        if partners is None:
            partners = self.partner_ids.filtered(lambda partner: not partner.user_ids)
        for partner in partners:
            # Prepare partner for signup and build the signup URL with redirect.
            partner.signup_get_auth_param()
            share_link = partner._get_signup_url_for_action(
                action="/mail/view", res_id=self.res_id, model=self.res_model
            )[partner.id]
            self._post_share_email(partner, share_link)

    def action_send_mail(self):
        """Dispatch each recipient to either the public link or the signup link.

        Partners that already have a user — or any partner when the record itself
        has an ``access_token`` — get the public share link in a batch. The rest
        receive a signup link if invitation scope is set to ``b2c``.
        """
        signup_enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("auth_signup.invitation_scope")
            == "b2c"
        )

        if getattr(self.resource_ref, "access_token", False) or not signup_enabled:
            partner_ids = self.partner_ids
        else:
            partner_ids = self.partner_ids.filtered(lambda x: x.user_ids)
        # if partner already user or record has access token send common link in batch to all user
        self._send_public_link(partner_ids)
        # when partner not user send individual mail with signup token
        self._send_signup_link(self.partner_ids - partner_ids)

        return {"type": "ir.actions.act_window_close"}
