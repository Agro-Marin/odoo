from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
        """Selection limited to concrete models that inherit ``mixin.portal``.

        Models outside that hierarchy have no ``access_url`` / ``access_token``,
        so the wizard's ``share_link`` would always come back empty for them.
        """
        portal_mixin_cls = self.pool["mixin.portal"]
        # Walk the registry, not ir.model: the predicate is purely a registry
        # question ("does this model inherit mixin.portal, and is it concrete"),
        # and reading every ir.model row to answer it meant a full-table search
        # plus a registry lookup per row on each call. ir.model is still needed
        # for the human-readable label, so fetch just the rows that survive.
        # ``self.pool`` is a Mapping[str, type[BaseModel]] -- its values are
        # model *classes*, so this is issubclass, not isinstance.
        portal_model_names = [
            name
            for name, model_cls in self.pool.items()
            if issubclass(model_cls, portal_mixin_cls) and not model_cls._abstract
        ]
        names = dict(
            self.env["ir.model"]
            .sudo()
            .search_fetch([("model", "in", portal_model_names)], ["model", "name"])
            .mapped(lambda m: (m.model, m.name))
        )
        return [(name, names.get(name, name)) for name in portal_model_names]

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
        """Expose the target as a ``Reference``, or nothing when it is not shareable.

        Goes through :meth:`_get_portal_record` like its two sibling computes,
        rather than testing ``res_model in self.env``. "Is a model" is the wrong
        question here: this field's selection is ``_selection_target_model``,
        i.e. *concrete mixin.portal models only*, and ``Reference.convert_to_cache``
        rejects anything outside it with ``ValueError``. ``res_model`` is a plain
        ``Char`` seeded straight from the ``active_model`` context (see
        :meth:`default_get`) and writable by anyone holding the wizard's ACL, so
        a perfectly valid model that simply is not portal-shareable —
        ``res.partner``, say — turned any read of this field into an exception.

        The wizard's own form view does not list ``resource_ref``, so *opening*
        the dialog was never affected: it renders an empty ``share_link`` and
        looks fine. The raise surfaced on **Send**, where ``_send_public_link``
        and ``_post_share_email`` dereference ``resource_ref`` — a raw
        ``ValueError`` (HTTP 500) instead of a message the user can act on.
        Verified over the real ``web_read`` the client issues on open.
        """
        for wizard in self:
            record = wizard._get_portal_record()
            wizard.resource_ref = f"{record._name},{record.id}" if record else False

    def _get_portal_record(self):
        """Return the active record when it is a shareable ``mixin.portal`` one.

        Shared helper for ``_compute_share_link`` and ``_compute_access_warning``.

        :return: the record, or an empty ``mixin.portal`` recordset when there
                 is none to share. Returning an empty recordset rather than
                 ``None`` keeps the result usable with the ORM idioms callers
                 expect (``record.access_warning`` on the empty set yields
                 ``False`` instead of raising ``AttributeError``), while still
                 being falsy for the ``if record`` checks already in place.
        :rtype: mixin.portal
        """
        self.ensure_one()
        empty = self.env["mixin.portal"]
        if not self.res_model or self.res_model not in self.env:
            return empty
        res_model = self.env[self.res_model]
        if isinstance(res_model, self.pool["mixin.portal"]) and self.res_id:
            return res_model.browse(self.res_id)
        return empty

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

    def _get_shared_record(self):
        """Return the record to share, refusing a target that cannot carry a link.

        Sharing needs ``access_url`` / ``access_token``, which only
        ``mixin.portal`` provides. ``_get_portal_record`` already answers
        "is this shareable"; this wraps it for the *acting* paths, which must
        stop with a message the user can act on instead of building a mail
        around a record that has no portal URL.

        :rtype: mixin.portal
        :raise UserError: when ``res_model`` / ``res_id`` name nothing shareable
        """
        self.ensure_one()
        record = self._get_portal_record()
        if not record:
            raise UserError(_("This document cannot be shared: it has no portal page."))
        return record

    def _post_share_email(self, partner, share_link):
        """Post the portal share template to ``partner`` in their preferred language.

        Single source of truth for the share-mail payload — ``_send_public_link``
        and ``_send_signup_link`` differ only in how they compute ``share_link``.
        """
        record = self._get_shared_record()
        record.with_context(lang=partner.lang).message_post_with_source(
            "portal.portal_share_template",
            render_values={
                "partner": partner,
                "note": self.note,
                "record": record,
                "share_link": share_link,
                "model_description": self.env["ir.model"]
                ._get(record._name)
                .display_name.lower(),
            },
            subject=_("Invitation to access %s", record.display_name),
            subtype_xmlid="mail.mt_note",
            email_layout_xmlid="mail.mail_notification_light",
            partner_ids=partner.ids,
        )

    def _send_public_link(self, partners=None):
        """Send the per-record share link with an HMAC-signed pid to each partner.

        Used for recipients who can already log in, and for everyone when
        self-signup is closed. See :meth:`_get_public_link_partners` for the
        split (and for why the record's ``access_token`` plays no part in it).
        """
        if partners is None:
            partners = self.partner_ids
        record = self._get_shared_record()
        for partner in partners:
            share_link = record.get_base_url() + record._get_share_url(
                redirect=True, pid=partner.id
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

    def _get_public_link_partners(self):
        """Split the recipients: who gets a plain share link vs a signup link.

        A partner who already has a user can just follow the tokenised link. A
        partner who has none is better served by a signup link, which lands them
        on the same record *and* lets them create the account they will need for
        any follow-up — but only where self-signup is actually open (``b2c``);
        otherwise the signup link would dead-end and the plain link is all we
        can offer.

        This deliberately does **not** consider the record's ``access_token``.
        That test used to gate the whole split, and it could never fail: the
        wizard's form shows ``share_link``, whose compute calls
        ``_portal_ensure_token()``, so simply *opening* the dialog mints the
        token and pins the branch to "everyone gets the public link" — for this
        share and every later one on the same record. The signup path was
        therefore dead code, and recipients without an account silently stopped
        being invited to create one. Token presence is in any case not a
        property of the recipient: every ``mixin.portal`` record can mint one on
        demand, so it says nothing about who needs signup.

        :return: the subset of ``partner_ids`` to send the public link to
        :rtype: res.partner
        """
        self.ensure_one()
        signup_enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("auth_signup.invitation_scope")
            == "b2c"
        )
        if not signup_enabled:
            return self.partner_ids
        return self.partner_ids.filtered(lambda partner: partner.user_ids)

    def action_send_mail(self):
        """Dispatch each recipient to either the public link or the signup link."""
        self.ensure_one()
        # Resolve up front: refuse an unshareable target before any recipient
        # has been mailed, rather than part-way through the loop below.
        self._get_shared_record()
        public_link_partners = self._get_public_link_partners()
        # Partner already has a user (or signup is closed): common share link.
        self._send_public_link(public_link_partners)
        # Partner has no user yet: individual mail carrying a signup token.
        self._send_signup_link(self.partner_ids - public_link_partners)

        return {"type": "ir.actions.act_window_close"}
