from typing import Literal

from odoo.tools.mail import (
    email_normalize,
    email_split_and_format,
    parse_contact_from_email,
)


def email_comparison_key(email: str | Literal[False] | None) -> str:
    if not email:
        return ""
    return email_normalize(email, strict=False) or email.strip()


def dedupe_emails_by_key(
    email_inputs: list[str], skip_keys: set[str] | frozenset[str]
) -> list[str]:
    by_key: dict[str, str] = {}
    for email_input in email_inputs:
        for email in email_split_and_format(email_input):
            if not (email and email.strip()):
                continue
            key = email_comparison_key(email)
            if key in skip_keys:
                continue
            current = by_key.get(key)
            if current is None or (
                not parse_contact_from_email(current)[0]
                and parse_contact_from_email(email)[0]
            ):
                by_key[key] = email
    return list(by_key.values())
