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

    stdlib_smtp = email.policy.SMTP
    IdentificationFieldsNoFoldPolicy._no_fold_policy = stdlib_smtp.clone(
        max_line_length=None
    )
    IdentificationFieldsNoFoldPolicy._max_fold_policy = stdlib_smtp.clone(
        max_line_length=998
    )
    email.policy.SMTP = IdentificationFieldsNoFoldPolicy(linesep=stdlib_smtp.linesep)
