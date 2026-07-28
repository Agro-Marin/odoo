from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import consteq


class DocumentsAccess(models.Model):
    """Link a `documents.document` to a partner granting a view or edit role."""

    _name = "documents.access"
    _description = "Document / Partner"
    _log_access = False

    document_id = fields.Many2one(
        "documents.document",
        required=True,
        bypass_search_access=True,
        index=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade", index=True
    )
    role = fields.Selection(
        [("view", "Viewer"), ("edit", "Editor")],
        string="Role",
        required=False,
        index=True,
    )
    last_access_date = fields.Datetime("Last Accessed On", required=False)
    expiration_date = fields.Datetime("Expiration", index=True)

    _unique_document_access_partner = models.Constraint(
        "unique(document_id, partner_id)",
        "This partner is already set on this document.",
    )
    _role_or_last_access_date = models.Constraint(
        "check (role IS NOT NULL or last_access_date IS NOT NULL)",
        "NULL roles must have a set last_access_date",
    )

    @api.constrains("partner_id", "role")
    def _check_partner_id(self) -> None:
        """Forbid granting a membership role to the public user.

        Anonymous sharing goes through ``access_via_link``; a role-bearing
        ``documents.access`` for the public partner is bad data. Role-less rows
        (access-date logging) and the (inactive) root user - the default actor
        for many internal flows - are intentionally left untouched.

        The former check read ``partner_id.user_ids`` with the default
        ``active_test=True``; the public/root users are inactive, so ``user_ids``
        was empty and the constraint never fired.
        """
        public_partner = self.env.ref("base.public_user").partner_id
        for access in self:
            if access.role and access.partner_id == public_partner:
                raise ValidationError(_("This user can not be member."))

    def _prepare_create_values(self, vals_list: list[dict]) -> list[dict]:
        vals_list = super()._prepare_create_values(vals_list)
        documents = self.env["documents.document"].browse(
            [vals["document_id"] for vals in vals_list]
        )
        documents.check_access("write")
        return vals_list

    def write(self, vals: dict) -> bool:
        """Write the given values, forbidding changes to partner and document."""
        if "partner_id" in vals or "document_id" in vals:
            raise AccessError(_("Access documents and partners cannot be changed."))

        self.document_id.check_access("write")
        return super().write(vals)

    @api.autovacuum
    def _gc_expired(self) -> None:
        """Retire expired memberships without discarding access history.

        A row carries two independent things: the membership (``role`` +
        ``expiration_date``) and the access log (``last_access_date``, which
        backs the "Recent" virtual folder and the last-accessed grouping).
        Unlinking the whole row on expiry threw the second away, so a document
        someone had actually opened silently dropped out of their "Recent" the
        moment their *share* expired. Expire the membership instead, and only
        delete rows that hold nothing else (the ``_role_or_last_access_date``
        constraint means a row must keep at least one of the two).

        Reports ``(done, maybe more)`` so a backlog larger than one batch is
        drained across the vacuum's re-queue instead of over as many days.
        """
        limit = 1000
        expired = self.search(
            [("expiration_date", "<=", fields.Datetime.now())], limit=limit
        )
        if not expired:
            return 0, False
        visited = expired.filtered("last_access_date")
        visited.write({"role": False, "expiration_date": False})
        (expired - visited).unlink()
        return len(expired), len(expired) == limit

    ######################
    # Partner invitation #
    ######################

    def _is_signup_available(self) -> bool:
        return (
            self.env["res.users"].sudo()._get_signup_invitation_scope() == "b2c"
            and self.role
            and (
                not self.expiration_date or self.expiration_date > fields.Datetime.now()
            )
            and not self.partner_id.with_context(active_test=False).user_ids
        )

    def _get_member_signup_token(self) -> str:
        """Token used to invite a member to create a user.

        The token is built using the ID of the access, so we can remove
        the member to invalidate the invitation, or use the expiration
        date.
        """
        self.ensure_one()
        if not self._is_signup_available():
            raise UserError(_("Cannot invite this member."))

        return tools.hmac(
            self.env(su=True),
            "documents-member-signup-token",
            (self.id, self.partner_id.id),
        )

    @api.model
    def _get_member_from_token(
        self, member_id: int, token: str
    ) -> DocumentsAccess | bool:
        member_sudo = self.browse(member_id).sudo().exists()
        if not member_sudo or not member_sudo._is_signup_available():
            return False
        if not consteq(member_sudo._get_member_signup_token(), token):
            return False
        return member_sudo

    @api.model
    def _get_signup_url(
        self,
        member_id: int,
        member_signup_token: str,
        access_token: str,
        redirect_url: str,
    ) -> str:
        """Build the signup URL for the current public user.

        :param member_id: ID of the `documents.access`
        :param member_signup_token: Token of the `documents.access`
        :param access_token: Token of the document (used to redirect
            the user after he signed-up)
        :param redirect_url: The URL where to redirect after the sign-up
        """
        if not member_id or not member_signup_token or not access_token:
            return ""

        # need to get the document from the member, because `_from_access_token`
        # won't return the document if it's in `access_via_link == 'none'`
        member_sudo = self._get_member_from_token(member_id, member_signup_token)
        if not member_sudo:
            return ""

        member_sudo.partner_id.signup_get_auth_param()
        return member_sudo.partner_id._get_signup_url_for_action(url=redirect_url)[
            member_sudo.partner_id.id
        ]
