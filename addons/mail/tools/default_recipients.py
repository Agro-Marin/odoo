from typing import NamedTuple

from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


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
    kept_keys: set[str],
) -> DefaultRecipientChoice:
    if not prioritize_email or not email_to_lst:
        if mailable_ids:
            choice = DefaultRecipientChoice(mailable_ids, "")
            by = "mailable_partners"
        elif kept_ids and set(to_keys) == kept_keys:
            choice = DefaultRecipientChoice(kept_ids, "")
            by = "kept_partners_match_to"
        elif email_to_lst:
            choice = DefaultRecipientChoice([], ",".join(email_to_lst))
            by = "email_to"
        else:
            choice = DefaultRecipientChoice(kept_ids, "")
            by = "kept_partners"
    elif set(to_keys) == mailable_keys:
        choice = DefaultRecipientChoice(mailable_ids, "")
        by = "mailable_partners_match_to"
    else:
        choice = DefaultRecipientChoice([], ",".join(email_to_lst))
        by = "email_to_prioritized"
    _debug.logic(
        "default_recipients_chosen",
        by=by,
        partners=len(choice.partner_ids),
        emails=len(email_to_lst) if choice.email_to else 0,
        prioritize_email=prioritize_email,
    )
    return choice
