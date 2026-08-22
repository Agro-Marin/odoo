import collections
import logging
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import babel.messages.pofile
import werkzeug.exceptions
from werkzeug.urls import iri_to_uri

from odoo import http
from odoo.http import request
from odoo.tools.misc import file_open
from odoo.tools.translate import JAVASCRIPT_TRANSLATION_COMMENT

_logger = logging.getLogger(__name__)


_URL_IGNORED_CHARS = ("\t", "\r", "\n")


def _is_local_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return False
    for char in _URL_IGNORED_CHARS:
        url = url.replace(char, "")
    if not url:
        return False
    if "\\" in url or url.startswith("//"):
        return False
    parsed = urlsplit(url)
    return not parsed.scheme and not parsed.netloc


def clean_action(action: dict, env: Any) -> dict:
    action_type = action.setdefault("type", "ir.actions.act_window_close")
    if action_type == "ir.actions.act_window" and not action.get("views"):
        generate_views(action)

    action_model = env[action["type"]]
    readable_fields = (
        action_model._get_fields_readable() | action_model._get_keys_client_only()
    )
    action_type_fields = action_model._fields.keys()

    cleaned_action = {
        field: value
        for field, value in action.items()
        if field in readable_fields or field not in action_type_fields
    }

    action_name = action.get("name") or action
    custom_properties = action.keys() - readable_fields - action_type_fields
    if custom_properties:
        _logger.warning(
            "Action %r contains custom properties %s. Passing them "
            "via the `params` or `context` properties is recommended instead",
            action_name,
            ", ".join(map(repr, custom_properties)),
        )

    return cleaned_action


def ensure_db(redirect: str = "/web/database/selector", db: str | None = None) -> None:
    if db is None:
        db = (raw_db := request.params.get("db")) and raw_db.strip()

    if db and db not in http.db_filter([db]):
        db = None

    if db and not request.session.db:
        r = request.httprequest
        url_redirect = urlsplit(r.base_url)
        if r.query_string:
            query_string = iri_to_uri(r.query_string.decode())
            url_redirect = url_redirect._replace(query=query_string)
        request.session.db = db
        werkzeug.exceptions.abort(request.redirect(urlunsplit(url_redirect), 302))

    if not db and request.session.db and http.db_filter([request.session.db]):
        db = request.session.db

    if not db:
        all_dbs = http.db_list(force=True)
        if len(all_dbs) == 1:
            db = all_dbs[0]

    if not db:
        werkzeug.exceptions.abort(request.redirect(redirect, 303))

    if db != request.session.db:
        request.session = http.root.session_store.new()
        request.session.update(http.get_default_session(), db=db)
        request.session.context["lang"] = request.default_lang()
        werkzeug.exceptions.abort(request.redirect(request.httprequest.url, 302))


def generate_views(action: dict) -> None:
    view_id = action.get("view_id") or False
    if isinstance(view_id, (list, tuple)):
        view_id = view_id[0]

    view_modes = action["view_mode"].split(",")

    if len(view_modes) > 1:
        if view_id:
            raise ValueError(
                f"Non-db action dictionaries should provide "
                f"either multiple view modes or a single view "
                f"mode and an optional view id.\n\n Got view "
                f"modes {view_modes!r} and view id {view_id!r} for action {action!r}"
            )
        action["views"] = [(False, mode) for mode in view_modes]
        return
    action["views"] = [(view_id, view_modes[0])]


def get_action(env: Any, path_part: str) -> Any:
    Actions = env["ir.actions.actions"]

    if path_part.startswith("action-"):
        someid = path_part.removeprefix("action-")
        if someid.isdigit():
            action = Actions.sudo().browse(int(someid)).exists()
        elif "." in someid:
            action = env.ref(someid, False)
            if not action or not action._name.startswith("ir.actions"):
                action = Actions
        else:
            action = Actions
    elif path_part.startswith("m-") or "." in path_part:
        model = path_part.removeprefix("m-")
        if model in env and not env[model]._abstract:
            action = (
                env["ir.actions.act_window"]
                .sudo()
                .search([("res_model", "=", model)], limit=1)
            )
            if not action:
                action = env["ir.actions.act_window"].new(
                    env[model].get_formview_action()
                )
        else:
            action = Actions
    else:
        action = (
            env["ir.actions.path"]
            .sudo()
            .search([("path", "=", path_part)], limit=1)
            .action_id
        )

    if action and action._name == "ir.actions.actions":
        action = action._get_action_concrete()

    return action


def get_action_triples(
    env: Any, path: str, *, start_pos: int = 0
) -> Iterator[tuple[int | None, Any, int | None]]:
    parts = collections.deque(path.strip("/").split("/"))
    active_id = None
    record_id = None

    while parts:
        action_name = parts.popleft()
        action = get_action(env, action_name)
        if not action:
            raise ValueError(
                f"expected action at word {path.count('/') - len(parts) + start_pos} but found “{action_name}”"
            )

        record_id = None
        if parts:
            if parts[0] == "new":
                parts.popleft()
                record_id = None
            elif parts[0].isdigit():
                record_id = int(parts.popleft())

        yield (active_id, action, record_id)

        if len(parts) > 1 and parts[0].isdigit():
            active_id = int(parts.popleft())
        elif record_id:
            active_id = record_id


def _get_login_redirect_url(uid: int, redirect: str | None = None) -> str:
    if request.session.uid:
        if redirect and _is_local_url(redirect):
            return redirect
        return (
            "/odoo"
            if is_user_internal(request.session.uid)
            else "/web/login_successful"
        )

    url = request.env(user=uid)["res.users"].browse(uid)._mfa_url()
    if not redirect or not _is_local_url(redirect):
        return url

    parsed = urlsplit(url)
    qs = dict(parse_qsl(parsed.query))
    qs["redirect"] = redirect
    return urlunsplit(parsed._replace(query=urlencode(qs)))


def is_user_internal(uid: int) -> bool:
    return request.env["res.users"].browse(uid)._is_internal()


def _local_web_translations(trans_file: str) -> list[dict[str, str]] | None:
    try:
        with file_open(trans_file, filter_ext=(".po")) as t_file:
            po = babel.messages.pofile.read_po(t_file)
    except Exception:
        return None
    return [
        {"id": x.id, "string": x.string}
        for x in po
        if x.id and x.string and JAVASCRIPT_TRANSLATION_COMMENT in x.auto_comments
    ]
