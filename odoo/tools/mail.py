import random
import socket
import time

from odoo.libs.email import (
    email_addr_escapes_re,
    email_anonymize,
    email_domain_extract,
    email_domain_normalize,
    email_escape_char,
    email_normalize,
    email_normalize_all,
    email_re,
    email_split,
    email_split_and_format,
    email_split_and_format_normalize,
    email_split_and_normalize,
    email_split_tuples,
    encapsulate_email,
    formataddr,
    getaddresses,
    mail_header_msgid_re,
    parse_contact_from_email,
    single_email_re,
    unfold_references,
    url_domain_extract,
)
from odoo.libs.email.parsing import _normalize_email
from odoo.libs.text import (
    HTML_NEWLINES_REGEX,
    HTML_TAG_URL_REGEX,
    HTML_TAGS_REGEX,
    SANITIZE_TAGS,
    TEXT_URL_REGEX,
    URL_REGEX,
    URL_SKIP_PROTOCOL_REGEX,
    append_content_to_html,
    create_link,
    fromstring,
    html2plaintext,
    html_escape,
    html_keep_url,
    html_normalize,
    html_sanitize,
    html_to_inner_content,
    is_html_empty,
    plaintext2html,
    prepend_html_content,
    safe_attrs,
    tag_quote,
    validate_url,
)

__all__ = [
    "email_domain_extract",
    "email_domain_normalize",
    "email_normalize",
    "email_normalize_all",
    "email_split",
    "encapsulate_email",
    "formataddr",
    "html2plaintext",
    "html_escape",
    "html_normalize",
    "html_sanitize",
    "is_html_empty",
    "parse_contact_from_email",
    "plaintext2html",
    "single_email_re",
]


def generate_tracking_message_id(res_id: int | str) -> str:
    try:
        rnd = random.SystemRandom().random()
    except NotImplementedError:
        rnd = random.random()
    rndstr = ("%.15f" % rnd)[2:]
    return "<%s.%.15f-odoo-%s@%s>" % (
        rndstr,
        time.time(),
        res_id,
        socket.gethostname(),
    )


def decode_message_header(message: object, header: str, separator: str = " ") -> str:
    return separator.join(h for h in message.get_all(header, []) if h)
