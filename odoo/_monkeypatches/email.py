import email.policy

RFC5322_IDENTIFICATION_HEADERS = {
    "message-id",
    "in-reply-to",
    "references",
    "resent-message-id",
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
    """Stop the stdlib from folding headers that must not be folded.

    `email.policy.SMTP` wraps every header at 78 columns. For the RFC 5322
    identification headers that is destructive: a folded `Message-Id` or
    `References` no longer matches the value the recipient echoes back, which
    breaks mail threading. Those are emitted unfolded.

    User-facing headers (`To`, `Cc`, `Subject`, ...) still fold, but at 998
    characters -- the line-length ceiling RFC 5322 actually imposes -- rather
    than at 78. Everything else keeps the stdlib's behaviour by falling through
    to `super()._fold`.

    Replacing the policy is idempotent: a second call sees its own class and
    returns, so the two clones are never rebuilt from an already-patched base.
    """
    if isinstance(email.policy.SMTP, IdentificationFieldsNoFoldPolicy):
        return

    stdlib_smtp = email.policy.SMTP
    IdentificationFieldsNoFoldPolicy._no_fold_policy = stdlib_smtp.clone(
        max_line_length=None
    )
    IdentificationFieldsNoFoldPolicy._max_fold_policy = stdlib_smtp.clone(
        max_line_length=998
    )
    email.policy.SMTP = IdentificationFieldsNoFoldPolicy(linesep=stdlib_smtp.linesep)
