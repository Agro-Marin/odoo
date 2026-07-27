"""Install Odoo's outgoing-mail folding policy as the process-wide
``email.policy.SMTP``.

Python's default SMTP policy folds every long header at 78 columns. Two classes
of header must not be folded that aggressively:

- **Identification headers** (``Message-Id``, ``References``, ...) carry opaque
  tokens. A number of MTAs and mail clients fail to re-join a folded identifier,
  which breaks threading and bounce correlation, so they are never folded.
- **User-defined headers** (``To``, ``Subject``, ...) may legitimately be long;
  they are folded only at the RFC 5322 hard limit of 998 characters.

This lives here rather than in ``ir_mail_server`` so the substitution happens
once, at startup, before any addon can capture the stdlib object -- a module
that ran ``from email.policy import SMTP`` before the addon was imported would
otherwise keep the unpatched policy.
"""

import email.policy

RFC5322_IDENTIFICATION_HEADERS = {
    "message-id",
    "in-reply-to",
    "references",
    "resent-msg-id",
}
USER_DEFINED_HEADERS = {"bcc", "cc", "from", "reply-to", "subject", "to"}


class IdentificationFieldsNoFoldPolicy(email.policy.EmailPolicy):
    _no_fold_policy: email.policy.EmailPolicy
    _max_fold_policy: email.policy.EmailPolicy

    def _fold(self, name: str, value: str, *args, **kwargs) -> str:
        lname = name.lower()
        if lname in RFC5322_IDENTIFICATION_HEADERS:
            return self._no_fold_policy._fold(name, value, *args, **kwargs)
        if lname in USER_DEFINED_HEADERS:
            return self._max_fold_policy._fold(name, value, *args, **kwargs)
        return super()._fold(name, value, *args, **kwargs)


def patch_module() -> None:
    if isinstance(email.policy.SMTP, IdentificationFieldsNoFoldPolicy):
        return

    # Clone from the stdlib policy while it is still unpatched, otherwise the
    # delegate policies would be instances of this class and _fold would recurse.
    stdlib_smtp = email.policy.SMTP
    IdentificationFieldsNoFoldPolicy._no_fold_policy = stdlib_smtp.clone(
        max_line_length=None
    )
    IdentificationFieldsNoFoldPolicy._max_fold_policy = stdlib_smtp.clone(
        max_line_length=998
    )
    email.policy.SMTP = IdentificationFieldsNoFoldPolicy(linesep=stdlib_smtp.linesep)
