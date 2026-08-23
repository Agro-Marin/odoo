import logging
from email.message import EmailMessage
from typing import NamedTuple

from odoo.tools.mail import append_content_to_html, html_sanitize

# Relative, because `html_body` is the module next to this one. Spelling it
# `odoo.addons.mail.tools.html_body` asked the *addons* machinery to resolve a sibling,
# and that machinery is not running under Tier-1 pytest: the import raised
# `ModuleNotFoundError: No module named 'odoo.addons.mail'` at collection and took the
# whole DB-free suite down with it -- 3900 tests collected, none run. A sibling import
# resolves through this package whatever loaded it.
from .html_body import (
    iter_fragment_elements,
    parse_body_fragments,
    render_body_fragments,
)

_logger = logging.getLogger(__name__)


class Attachment(NamedTuple):
    fname: str
    content: str | bytes | EmailMessage | None
    info: dict


class Payload(NamedTuple):
    body: str
    attachments: list[Attachment]


BAD_CONTENT_TYPES = (
    "binary/octet-stream",
    "*/*",
    "bin/plain",
)


def _alternative_rank(content_type: str) -> int:
    if content_type.startswith("multipart/") or content_type == "text/html":
        return 2
    if content_type == "text/plain":
        return 1
    return 0


def part_content(part: EmailMessage) -> str | bytes | EmailMessage | None:
    try:
        return part.get_content()
    except LookupError, UnicodeDecodeError, ValueError:
        _logger.warning(
            "Unresolvable charset %r on inbound mail part; decoding as utf-8 "
            "with replacement.",
            part.get_content_charset(),
        )
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def repair_part_headers(part: EmailMessage) -> None:
    if part.get_content_type().startswith("text/") and not part.get_param("charset"):
        part.set_charset("utf-8")
    content_type = part.get("Content-Type", "")
    if content_type.startswith("pdf;"):
        part.replace_header("Content-Type", "application/pdf" + content_type[3:])
    elif (bad_content_type := part.get_content_type()) in BAD_CONTENT_TYPES:
        _logger.warning(
            "Message containing an unexpected Content-Type %r, assuming "
            "'application/octet-stream'",
            bad_content_type,
        )
        part.replace_header("Content-Type", "application/octet-stream")


def _children(part: EmailMessage) -> list[EmailMessage]:
    payload = part.get_payload()
    return payload if isinstance(payload, list) else []


def _is_attachment(part: EmailMessage, filename: str | None) -> bool:
    if filename:
        return True
    if part.get("content-disposition", "").strip().startswith("attachment"):
        return True
    return part.get_content_maintype() != "text"


class _Fragment(NamedTuple):
    body: str
    attachments: list[Attachment]
    html: bool


def _attachment_from(part: EmailMessage, filename: str | None, content) -> Attachment:
    """Name a part and carry its ``content`` as an :class:`Attachment`.

    *filename* is passed in rather than read here: `repair_part_headers` may
    replace an unusable ``Content-Type`` outright, and the replacement carries
    no ``name=`` parameter, so a filename read after the repair is lost.
    """
    info = {"encoding": part.get_content_charset()}
    if content_id := part.get("content-id"):
        info["cid"] = content_id.strip("><")
    return Attachment(filename or "attachment", content, info)


def _part_attachment(part: EmailMessage) -> Attachment:
    """Read a part that has been judged an attachment, repairing it first."""
    filename = part.get_filename()
    repair_part_headers(part)
    return _attachment_from(part, filename, part_content(part))


def _is_carried_file(part: EmailMessage) -> bool:
    """Whether a part *inside an embedded message* is a file someone sent.

    Stricter than :func:`_is_attachment`, which answers "not body text" and so
    also claims every non-``text`` part. Inside an embedded message that is the
    wrong question: the embedded message's own ``text/plain`` and ``text/html``
    parts are its *body*, not files, and treating them as attachments is what
    the pre-2026-08 parser did -- it filed the quoted body of a forwarded mail
    as an attachment literally named "attachment". A real carried file names
    itself, either through ``filename=`` or an explicit attachment disposition.
    """
    return bool(part.get_filename()) or part.get(
        "content-disposition", ""
    ).strip().startswith("attachment")


def _embedded_attachments(part: EmailMessage) -> list[Attachment]:
    """Files carried *inside* an embedded ``message/rfc822`` part.

    Forwarding a mail as ``.eml`` is how people send an invoice on to a
    Documents folder alias or an expense to its inbox, and the file they mean is
    the one inside. Handing back only the ``.eml`` -- which is what treating the
    part as a single opaque leaf does -- files the envelope and drops the
    letter.

    The envelope is still returned by the caller, so the bytes are kept twice.
    That is deliberate: the ``.eml`` is the record of what arrived, and the
    extracted file is the thing anyone actually opens.

    Only genuine carried files are taken (see :func:`_is_carried_file`), and
    nothing here touches the outer body -- the two ways the old walk-based
    parser got this wrong.
    """
    payload = part.get_payload()
    inner = payload[0] if isinstance(payload, list) and payload else None
    if not isinstance(inner, EmailMessage):
        return []
    return [
        _part_attachment(sub)
        # `inner.walk()` yields `inner` first, then descends; skipping it drops
        # the embedded message itself, whose body is not a carried file. The
        # walk is recursive, so a file inside a forward of a forward is found
        # too, and a nested `.eml` is returned alongside its own contents.
        for sub in inner.walk()
        if sub is not inner
        and sub.get_content_maintype() != "multipart"
        and _is_carried_file(sub)
    ]


def _leaf(part: EmailMessage, stop_at_first_body: bool = False) -> _Fragment:
    filename = part.get_filename()
    repair_part_headers(part)
    content = part_content(part)

    if _is_attachment(part, filename):
        attachments = [_attachment_from(part, filename, content)]
        # Not for a bounce: there the embedded message is the mail that failed
        # to arrive, and its files belong to that mail, not to the delivery
        # report being parsed.
        if not stop_at_first_body and part.get_content_type() == "message/rfc822":
            attachments += _embedded_attachments(part)
        return _Fragment("", attachments, False)
    if part.get_content_type() == "text/html":
        return _Fragment(content, [], True)
    return _Fragment(append_content_to_html("", content, preserve=True), [], False)


def _alternative(part: EmailMessage, stop_at_first_body: bool) -> _Fragment:
    children = _children(part)
    if not children:
        return _Fragment("", [], False)
    fragments = [_assemble(child, stop_at_first_body) for child in children]
    best = max(
        enumerate(children),
        key=lambda pair: (_alternative_rank(pair[1].get_content_type()), pair[0]),
    )[0]
    return _Fragment(
        fragments[best].body,
        [a for fragment in fragments for a in fragment.attachments],
        fragments[best].html,
    )


def _sequence(parts: list[EmailMessage], stop_at_first_body: bool) -> _Fragment:
    body = ""
    attachments: list[Attachment] = []
    html = False
    for child in parts:
        if stop_at_first_body and body:
            break
        fragment = _assemble(child, stop_at_first_body)
        if fragment.body:
            body = append_content_to_html(body, fragment.body, plaintext=False)
        attachments.extend(fragment.attachments)
        html = html or fragment.html
    return _Fragment(body, attachments, html)


def _assemble(part: EmailMessage, stop_at_first_body: bool) -> _Fragment:
    if part.get_content_maintype() != "multipart":
        return _leaf(part, stop_at_first_body)
    if part.get_content_type() == "multipart/alternative":
        return _alternative(part, stop_at_first_body)
    return _sequence(_children(part), stop_at_first_body)


def extract_payload(
    message: EmailMessage,
    *,
    is_bounce: bool = False,
    save_original: bool = False,
) -> Payload:
    attachments = []
    if save_original:
        attachments.append(Attachment("original_email.eml", message.as_bytes(), {}))
    fragment = _assemble(message, stop_at_first_body=is_bounce)
    body = fragment.body
    if fragment.html:
        body = html_sanitize(body, sanitize_tags=False, strip_classes=True)
    return Payload(body, attachments + fragment.attachments)


def postprocess_payload(payload: Payload) -> Payload:
    body, attachments = payload
    if not body.strip():
        return payload
    fragments = parse_body_fragments(body)

    postprocessed = False
    to_remove = []
    for node in iter_fragment_elements(fragments):
        if "o_mail_notification" in (node.get("class") or "") or (
            "o_mail_notification" in (node.get("summary") or "")
        ):
            postprocessed = True
            if node.getparent() is not None:
                to_remove.append(node)
        if node.tag == "img" and node.get("src", "").startswith("cid:"):
            cid = node.get("src").split(":", 1)[1]
            named = next(
                (a for a in attachments if a.info and a.info.get("cid") == cid), None
            )
            if named:
                node.set("data-filename", named.fname)
                postprocessed = True

    for node in to_remove:
        node.getparent().remove(node)
    if postprocessed:
        body = render_body_fragments(fragments)
    return Payload(body, attachments)


def find_part(
    message: EmailMessage, content_types: tuple[str, ...]
) -> EmailMessage | None:
    return next(
        (part for part in message.walk() if part.get_content_type() in content_types),
        None,
    )
