SEND_FAILURE_TYPES: list[tuple[str, str]] = [
    ("unknown", "Unknown error"),
    ("mail_spam", "Detected As Spam"),
    ("mail_email_invalid", "Invalid email address"),
    ("mail_email_missing", "Missing email address"),
    ("mail_from_invalid", "Invalid from address"),
    ("mail_from_missing", "Missing from address"),
    ("mail_smtp", "Connection failed (outgoing mail server problem)"),
    ("mail_server_unauthorized", "Outgoing mail server not available to this email"),
]

BOUNCE_FAILURE_TYPES: list[tuple[str, str]] = [
    ("mail_bounce", "Bounce"),
]

MASS_MAILING_FAILURE_TYPES: list[tuple[str, str]] = [
    ("mail_bl", "Blacklisted Address"),
    ("mail_optout", "Opted Out"),
    ("mail_dup", "Duplicated Email"),
]

DELIVERY_FAILURE_TYPES: list[tuple[str, str]] = [
    *SEND_FAILURE_TYPES,
    *BOUNCE_FAILURE_TYPES,
    *MASS_MAILING_FAILURE_TYPES,
]

OUTGOING_FAILURE_TYPES: list[tuple[str, str]] = [
    *SEND_FAILURE_TYPES,
    *MASS_MAILING_FAILURE_TYPES,
]
