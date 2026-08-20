from typing import Any

from werkzeug.exceptions import NotFound

from odoo import http, models
from odoo.http import request
from odoo.tools import file_open

from odoo.addons.mail.tools.discuss import Store
from odoo.addons.mail.tools.paging import FETCH_LIMIT_MAX, clamp_limit  # noqa: F401

MAX_FETCH_LIMIT = FETCH_LIMIT_MAX


def to_record_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise NotFound
    try:
        return int(value)
    except ValueError:
        raise NotFound from None


def to_record_ids(values: Any) -> list[int]:
    if values is None:
        return []
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise NotFound
    return [to_record_id(value) for value in values]


def get_channel_or_404(channel_id: Any) -> models.Model:
    channel = request.env["discuss.channel"].search(
        [("id", "=", to_record_id(channel_id))]
    )
    if not channel:
        raise NotFound
    return channel


def get_self_member(channel_id: Any) -> models.Model:
    return request.env["discuss.channel.member"].search(
        [("channel_id", "=", to_record_id(channel_id)), ("is_self", "=", True)]
    )


def get_self_member_or_404(channel_id: Any) -> models.Model:
    member = get_self_member(channel_id)
    if not member:
        raise NotFound
    return member


def message_fetch_response(
    *,
    domain: Any = None,
    thread: models.Model | None = None,
    fetch_params: dict | None = None,
    mark_done: bool = False,
    extra_fields: Any = None,
    add_followers: bool = False,
) -> dict:
    res = request.env["mail.message"]._message_fetch(
        domain=domain,
        thread=thread,
        **request.env["mail.message"]._sanitize_fetch_params(fetch_params),
    )
    messages = res.pop("messages")
    if mark_done and not request.env.user._is_public():
        messages.set_message_done()
    store_kwargs = {}
    if extra_fields is not None:
        store_kwargs["extra_fields"] = extra_fields
    if add_followers:
        store_kwargs["add_followers"] = True
    return {
        **res,
        "data": Store().add(messages, **store_kwargs).get_result(),
        "messages": messages.ids,
    }


def javascript_file_response(path: str) -> http.Response:
    with file_open(path, "rb") as file:
        data = file.read()
    return request.make_response(
        data,
        headers=[
            ("Content-Type", "application/javascript"),
            ("X-Content-Type-Options", "nosniff"),
            ("Cache-Control", f"max-age={http.STATIC_CACHE}"),
        ],
    )
