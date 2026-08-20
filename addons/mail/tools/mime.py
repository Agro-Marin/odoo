import itertools
import logging
from email.message import EmailMessage
from typing import NamedTuple

import lxml.html
from lxml import etree
from markupsafe import Markup, escape

from odoo.tools.mail import append_content_to_html, html_sanitize

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


def _leaf(part: EmailMessage) -> _Fragment:
    filename = part.get_filename()
    repair_part_headers(part)
    content = part_content(part)
    info = {"encoding": part.get_content_charset()}

    if content_id := part.get("content-id"):
        info["cid"] = content_id.strip("><")

    if _is_attachment(part, filename):
        return _Fragment(
            "", [Attachment(filename or "attachment", content, info)], False
        )
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
        return _leaf(part)
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
    try:
        fragments = lxml.html.fragments_fromstring(body)
    except ValueError:
        fragments = lxml.html.fragments_fromstring(body.encode("utf-8"))
    nodes = [f for f in fragments if not isinstance(f, str)]

    postprocessed = False
    to_remove = []
    for node in itertools.chain.from_iterable(n.iter() for n in nodes):
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
        rendered = [
            str(escape(fragment))
            if isinstance(fragment, str)
            else etree.tostring(
                fragment, pretty_print=False, encoding="unicode", with_tail=True
            )
            for fragment in fragments
        ]
        body = Markup("".join(rendered))
    return Payload(body, attachments)


def find_part(
    message: EmailMessage, content_types: tuple[str, ...]
) -> EmailMessage | None:
    return next(
        (part for part in message.walk() if part.get_content_type() in content_types),
        None,
    )
