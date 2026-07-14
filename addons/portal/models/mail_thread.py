import hashlib
import hmac

from odoo import _, api, fields, models
from odoo.fields import Domain

from odoo.addons.mail.tools.discuss import EMPTY_EDIT_MARKER
from odoo.addons.portal.utils import (
    validate_thread_with_hash_pid,
    validate_thread_with_token,
)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    # Token field used to authenticate external posts (defaults to portal.mixin's
    # ``access_token``). Subclasses with a different token field override this.
    _mail_post_token_field = "access_token"

    def _get_portal_message_fetch_domain(self):
        """Domain selecting the messages the portal chatter displays for ``self``.

        Single source of truth for "which messages are visible in the portal
        chatter of these records": the ``website_message_ids`` message types,
        restricted to ``self``, share-visible only (non-internal subtype) and
        non-empty. Used both by the chatter fetch controller and by counters
        that must agree with it (e.g. ``website_slides.comments_count``) so a
        badge never diverges from what the chatter actually shows.
        """
        MailMessage = self.env["mail.message"]
        field = self._fields["website_message_ids"]
        non_empty = Domain("body", "not in", [False, EMPTY_EDIT_MARKER]) | Domain(
            "attachment_ids", "!=", False
        )
        return (
            Domain(field.get_comodel_domain(self))
            & Domain("res_id", "in", self.ids)
            & Domain(MailMessage._get_search_domain_share())
            & non_empty
        )

    website_message_ids = fields.One2many(
        "mail.message",
        "res_id",
        string="Portal Messages",
        domain=lambda self: [
            ("model", "=", self._name),
            (
                "message_type",
                "in",
                ("comment", "email", "email_outgoing", "auto_comment", "out_of_office"),
            ),
        ],
        # Portal users see their own thread messages without mail.message ACL.
        # Access-token / HMAC validation happens upstream in the controller.
        bypass_search_access=True,
        help="Portal communication history for this record.",
    )

    def _notify_get_recipients_groups(self, message, model_description, msg_vals=False):
        """Add a 'portal_customer' notification group with an HMAC-signed access link."""
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if not self:
            return groups

        portal_enabled = isinstance(self, self.env.registry["portal.mixin"])
        if not portal_enabled:
            return groups

        customer = self._mail_get_partners(introspect_fields=False)[self.id]
        if customer:
            # sudo: mail.thread - user posting with read access should be able to create token when
            # notifying other customers that need it
            access_token = self.sudo()._portal_ensure_token()
            local_msg_vals = dict(msg_vals or {})
            local_msg_vals["access_token"] = access_token
            local_msg_vals["pid"] = customer.id
            local_msg_vals["hash"] = self._sign_token(customer.id)
            # sudo: mail.thread - user posting with read access should be able to get/create signup
            # token when notifying other customers that need it
            local_msg_vals.update(customer.sudo().signup_get_auth_param()[customer.id])
            access_link = self._notify_get_action_link("view", **local_msg_vals)

            new_group = [
                (
                    "portal_customer",
                    lambda pdata: pdata["id"] == customer.id,
                    {
                        "active": True,
                        "button_access": {
                            "url": access_link,
                        },
                        "has_button_access": True,
                    },
                )
            ]
        else:
            new_group = []

        # Activate the parent "portal" group so portal users get the access
        # button. Defensive lookup: parent currently guarantees this group exists,
        # but tolerate future refactors that might not.
        portal_group = next((g for g in groups if g[0] == "portal"), None)
        if portal_group is not None:
            portal_group[2]["active"] = True
            portal_group[2]["has_button_access"] = True

        return new_group + groups

    def _sign_token(self, pid) -> str:
        """Generate an HMAC binding this record's token to a partner id.

        :param int pid: ``res.partner`` id authorised to post on this thread
        :return: HMAC-SHA256 hex digest (64 chars)
        :rtype: str
        :raises NotImplementedError: if the model lacks the configured token field

        Implementation note: this signs ``repr((dbname, access_token, pid))``
        rather than delegating to :func:`odoo.tools.security.hmac`, which wraps
        the message as ``repr((scope, message))``. The two formats produce
        different digests, so switching helpers would invalidate every existing
        portal link in production. Kept hand-rolled for backward compatibility.
        """
        self.ensure_one()
        if self._mail_post_token_field not in self._fields:
            raise NotImplementedError(
                _(
                    "Model %(model_name)s does not support token signature, as it does not have %(field_name)s field.",
                    model_name=self._name,
                    field_name=self._mail_post_token_field,
                )
            )
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        token = (self.env.cr.dbname, self[self._mail_post_token_field], pid)
        return hmac.new(
            secret.encode(), repr(token).encode(), hashlib.sha256
        ).hexdigest()

    def _portal_get_parent_hash_token(self, pid):
        """Return a parent record's signed token for shared-portal use cases.

        Overridden in models that have a Many2one ``parent`` field and can be
        shared either individually or indirectly via the parent.

        :param int pid: ``res.partner`` id to sign against
        :return: parent's ``_sign_token(pid)`` or ``False`` if no parent applies
        """
        return False

    @api.model
    def _get_allowed_access_params(self):
        """Allow ``hash``, ``pid``, ``token`` in portal access-validation kwargs."""
        return super()._get_allowed_access_params() | {"hash", "pid", "token"}

    @api.model
    def _get_thread_with_access(
        self, thread_id, *, hash=None, pid=None, token=None, **kwargs
    ):
        """Resolve a thread by id, falling back to HMAC / access-token validation.

        First tries the parent's ACL-based resolution. If the user has no rights
        but provides a valid ``hash+pid`` HMAC pair or a valid ``token``, returns
        the sudo recordset so portal controllers can render the page.
        """
        if thread := super()._get_thread_with_access(
            thread_id, hash=hash, pid=pid, token=token, **kwargs
        ):
            return thread
        thread = self.browse(thread_id).sudo()
        if validate_thread_with_hash_pid(
            thread, hash, pid
        ) or validate_thread_with_token(thread, token):
            return thread
        return self.browse()
