import logging
from typing import Any

from odoo import api, models, tools
from odoo.api import DomainType
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.http import request

_logger = logging.getLogger(__name__)

SKIP_CAPTCHA_LOGIN = object()


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def name_search(
        self,
        name: str = "",
        domain: DomainType | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        """Move the current user to the front of the result list."""
        domain = Domain(domain or Domain.TRUE)
        user_list = super().name_search(name, domain, operator, limit)
        uid = self.env.uid
        # Index 0 is a valid match but falsy, so check "is not None" explicitly
        # rather than relying on the walrus value's truthiness.
        if (
            index := next(
                (i for i, (user_id, _name) in enumerate(user_list) if user_id == uid),
                None,
            )
        ) is not None:
            user_tuple = user_list.pop(index)
            user_list.insert(0, user_tuple)
        elif limit is not None and len(user_list) == limit:
            # The current user may exist beyond the truncated results; search
            # for it explicitly instead of missing it.
            if user_tuple := super().name_search(
                name, domain & Domain("id", "=", uid), operator, limit=1
            ):
                user_list = [user_tuple[0], *user_list[:-1]]
        return user_list

    def _on_webclient_bootstrap(self) -> None:
        self.ensure_one()

    def _should_captcha_login(self, credential: dict[str, Any]) -> bool:
        if (
            request
            and request.env.context.get("skip_captcha_login") is SKIP_CAPTCHA_LOGIN
        ):
            return False
        return credential["type"] == "password"

    @api.model
    def web_create_users(self, emails: list[str]) -> bool:
        """Batch-create users from a list of email addresses.

        Reactivates deactivated accounts when the email matches an existing
        inactive user. Already-active users are skipped (not duplicated).
        Requires the Discuss application for the ``email_normalized`` field.
        """
        emails_normalized = [
            tools.mail.parse_contact_from_email(email)[1] for email in emails
        ]

        if "email_normalized" not in self._fields:
            raise UserError(
                self.env._(
                    "You have to install the Discuss application to use this feature."
                )
            )

        # active_test=False: also match deactivated users so they get
        # reactivated below. A search limited to active users would miss
        # them, and create() would then hit the unique constraint on login.
        all_matching = self.with_context(active_test=False).search(
            [
                "|",
                ("login", "in", emails + emails_normalized),
                ("email_normalized", "in", emails_normalized),
            ]
        )
        deactivated_users = all_matching.filtered(lambda u: not u.active)
        for user in deactivated_users:
            _logger.info(
                "Reactivating previously deactivated user %r (id=%d)",
                user.login,
                user.id,
            )
            user.active = True
        # Dedup against both normalised emails AND logins: a user matched only by
        # login above may have an empty or different ``email_normalized``, and
        # since ``create`` below sets ``login=email_normalized`` we must also skip
        # any input whose normalised form already exists as a login -- otherwise
        # the create hits the unique constraint on ``login``.
        done = set(all_matching.mapped("email_normalized")) | set(
            all_matching.mapped("login")
        )

        new_emails = [
            e for e, n in zip(emails, emails_normalized, strict=True) if n not in done
        ]
        for email in new_emails:
            name, email_normalized = tools.mail.parse_contact_from_email(email)
            self.with_context(signup_valid=True).create(
                {
                    "login": email_normalized,
                    "name": name or email_normalized,
                    "email": email_normalized,
                    "active": True,
                }
            )

        return True
