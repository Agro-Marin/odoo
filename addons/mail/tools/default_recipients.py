from typing import NamedTuple


class DefaultRecipientChoice(NamedTuple):
    partner_ids: list[int]
    email_to: str


def choose_default_recipients(
    *,
    prioritize_email: bool,
    email_to_lst: list[str],
    to_keys: list[str],
    mailable_ids: list[int],
    mailable_keys: set[str],
    kept_ids: list[int],
    kept_emails: set[str],
) -> DefaultRecipientChoice:
    if not prioritize_email or not email_to_lst:
        if mailable_ids:
            return DefaultRecipientChoice(mailable_ids, "")
        if kept_ids and set(email_to_lst) == kept_emails:
            return DefaultRecipientChoice(kept_ids, "")
        if email_to_lst:
            return DefaultRecipientChoice([], ",".join(email_to_lst))
        return DefaultRecipientChoice(kept_ids, "")

    if set(to_keys) == mailable_keys:
        return DefaultRecipientChoice(mailable_ids, "")
    return DefaultRecipientChoice([], ",".join(email_to_lst))
