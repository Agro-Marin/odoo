import uuid
from ast import literal_eval
from urllib.parse import urlencode

from odoo import api, fields, models
from odoo.exceptions import AccessError


class PortalMixin(models.AbstractModel):
    """Mixin exposing a record to portal users via a tokenised access URL."""

    _name = "portal.mixin"
    _description = "Portal Mixin"

    access_url = fields.Char(
        "Portal Access URL",
        compute="_compute_access_url",
        help="Portal URL for this record (overridden by concrete models).",
    )
    access_token = fields.Char("Security Token", copy=False)

    # Surfaces access caveats from concrete models (e.g. expired link,
    # archived record). Subclasses override `_compute_access_warning`.
    access_warning = fields.Text("Access warning", compute="_compute_access_warning")

    def _compute_access_warning(self):
        for record in self:
            record.access_warning = ""

    def _compute_access_url(self):
        for record in self:
            record.access_url = "#"

    def _portal_ensure_token(self) -> str:
        """Return this record's access token, minting and persisting one on demand.

        The intermediate ``write`` is required: ``self.sudo()`` returns a recordset
        bound to a different env, so reading ``self.access_token`` (in the caller's
        env) would still serve the cached ``False`` until invalidation. Writing
        forces ORM cache invalidation across envs.

        :return: the persisted UUID4 token
        :rtype: str
        """
        self.ensure_one()
        if not self.access_token:
            self.sudo().write({"access_token": str(uuid.uuid4())})
        return self.access_token

    def _get_share_url(
        self, redirect=False, signup_partner=False, pid=None, share_token=True
    ):
        """Build a shareable URL for this record, with auth-bypass parameters.

        :param bool redirect: when True, return ``/mail/view?model=...&res_id=...``
                              so the recipient is routed through the access-check
                              redirector. When False, return the direct portal URL.
        :param bool signup_partner: include sign-up auth params so the recipient
                                    can create an account with pre-filled fields.
        :param pid: ``res.partner`` id to be authenticated against the portal
                    chatter (paired with a generated HMAC ``hash``). Requires a
                    record that also inherits ``mail.thread`` (provides
                    ``_sign_token``).
        :param bool share_token: include the record's ``access_token`` in the URL
        :return: URL ready to be sent by mail
        :rtype: str
        """
        self.ensure_one()
        params = {"model": self._name, "res_id": self.id} if redirect else {}
        if share_token:
            self.check_access("read")
            params["access_token"] = self._portal_ensure_token()
        if pid:
            params["pid"] = pid
            params["hash"] = self._sign_token(pid)
        if signup_partner and hasattr(self, "partner_id") and self.partner_id:
            params.update(self.partner_id.signup_get_auth_param()[self.partner_id.id])

        url_base = "/mail/view" if redirect else self.access_url
        qs = urlencode(params)
        return f"{url_base}?{qs}" if qs else url_base

    def _get_access_action(self, access_uid=None, force_website=False):
        """Redirect portal users (or any user when ``force_website``) to the public document.

        :param int access_uid: act on behalf of this user (must have read access)
        :param bool force_website: bypass user-share check and always return a URL
        :return: ir.actions.act_url descriptor, or ``super()`` for backend redirect
        """
        self.ensure_one()

        user, record = self.env.user, self
        if access_uid:
            try:
                record.check_access("read")
            except AccessError:
                return super()._get_access_action(
                    access_uid=access_uid, force_website=force_website
                )
            user = self.env["res.users"].sudo().browse(access_uid)
            record = self.with_user(user)
        if user.share or force_website:
            try:
                record.check_access("read")
            except AccessError:
                # No read access: only force_website still produces a URL (the
                # portal page itself will handle the unauthenticated fallback).
                if force_website:
                    return {
                        "type": "ir.actions.act_url",
                        "url": record.access_url,
                        "target": "self",
                        "res_id": record.id,
                    }
            else:
                return {
                    "type": "ir.actions.act_url",
                    "url": record._get_share_url(),
                    "target": "self",
                    "res_id": record.id,
                }
        return super()._get_access_action(
            access_uid=access_uid, force_website=force_website
        )

    @api.model
    def action_share(self):
        """Open the portal-share wizard pre-bound to the active record."""
        action = self.env["ir.actions.actions"]._for_xml_id(
            "portal.portal_share_action"
        )
        action["context"] = {
            "active_id": self.env.context.get("active_id"),
            "active_model": self.env.context.get("active_model"),
            **literal_eval(action["context"]),
        }
        return action

    def get_portal_url(
        self,
        suffix=None,
        report_type=None,
        download=None,
        query_string=None,
        anchor=None,
    ) -> str:
        """Build a token-bearing portal URL for this record.

        The associated portal route is responsible for honoring each flag.

        :param str suffix: path fragment appended to ``access_url`` before the query string
        :param str report_type: usually one of ``html``, ``pdf``, ``text``
        :param bool download: when truthy, adds ``&download=true``
        :param str query_string: extra ``&k=v&...`` already URL-encoded by caller
                                 (appended verbatim — not re-encoded)
        :param str anchor: fragment appended after ``#``
        :return: full URL ready for use in a mail body or redirect
        :rtype: str
        """
        self.ensure_one()
        params = {"access_token": self._portal_ensure_token()}
        if report_type:
            params["report_type"] = report_type
        if download:
            params["download"] = "true"
        qs = urlencode(params)
        if query_string:
            qs = f"{qs}{query_string}"
        fragment = f"#{anchor}" if anchor else ""
        return f"{self.access_url}{suffix or ''}?{qs}{fragment}"
