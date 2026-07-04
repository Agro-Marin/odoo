import collections
import logging
from collections.abc import Iterator  # runtime import required (PEP 649)
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


def _is_local_url(url: str | None) -> bool:
    """Return True if *url* is a safe local redirect target.

    Rejects absolute URLs, protocol-relative URLs, and empty strings
    to prevent open-redirect vulnerabilities.
    """
    if not url or not isinstance(url, str):
        return False
    # Browsers normalize a leading "\" or "\\" to "//", turning it into a
    # protocol-relative open redirect; urlsplit (RFC 3986) does not perform
    # that normalization, so backslashes must be rejected explicitly here.
    if "\\" in url or url.startswith("//"):
        return False
    parsed = urlsplit(url)
    return not parsed.scheme and not parsed.netloc


def clean_action(action: dict, env: Any) -> dict:
    action_type = action.setdefault("type", "ir.actions.act_window_close")
    if action_type == "ir.actions.act_window" and not action.get("views"):
        generate_views(action)

    # Keep only fields readable on this action's type, plus any custom
    # (non-model) properties — drop unreadable model fields.
    readable_fields = env[action["type"]]._get_readable_fields()
    action_type_fields = env[action["type"]]._fields.keys()

    cleaned_action = {
        field: value
        for field, value in action.items()
        if field in readable_fields or field not in action_type_fields
    }

    action_name = action.get("name") or action
    custom_properties = action.keys() - readable_fields - action_type_fields
    # Custom properties work but are discouraged in favor of `params`/`context`.
    if custom_properties:
        _logger.warning(
            "Action %r contains custom properties %s. Passing them "
            "via the `params` or `context` properties is recommended instead",
            action_name,
            ", ".join(map(repr, custom_properties)),
        )

    return cleaned_action


def ensure_db(redirect: str = "/web/database/selector", db: str | None = None) -> None:
    """Ensure a valid database is selected for the current request.

    Used in ``auth="none"`` routes that still need a database.  Applies
    heuristics in order: explicit ``db`` param > session > monodb.
    Redirects to *redirect* (default: database selector) when no database
    can be resolved.  Validates against ``http.db_filter()`` to prevent
    database forgery / XSS.

    :param redirect: URL to redirect to when no database is found
    :param db: explicit database name to use (skips heuristics)
    :raises werkzeug.exceptions.HTTPException: via redirect, both when no db
        can be resolved and whenever the session's db cookie needs to be
        (re)set for a db that *was* resolved
    """
    if db is None:
        db = (raw_db := request.params.get("db")) and raw_db.strip()

    if db and db not in http.db_filter([db]):
        db = None

    if db and not request.session.db:
        # An explicit db on a session with none set means the nodb router
        # resolved this route, but page rendering may depend on data injected
        # by the db-aware router. Redirect to the same URL with the session
        # cookie set so the next request goes through that router instead.
        r = request.httprequest
        url_redirect = urlsplit(r.base_url)
        if r.query_string:
            # query_string is bytes, the rest is text — decode before joining
            query_string = iri_to_uri(r.query_string.decode())
            url_redirect = url_redirect._replace(query=query_string)
        request.session.db = db
        werkzeug.exceptions.abort(request.redirect(urlunsplit(url_redirect), 302))

    if not db and request.session.db and http.db_filter([request.session.db]):
        db = request.session.db

    if not db:
        # Single-database install: no need to ask, there is only one choice.
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
    """Fill in the ``views`` key of a custom action dictionary that lacks one.

    ``ir.actions.act_window`` records get ``views`` from the database, but a
    button or server action can build an action dict on the fly without it.
    The web client relies on ``action['views']``, so derive it here from
    ``view_mode`` and ``view_id``.

    Handles two cases: no view_id with multiple view_mode, or a single
    view_id with a single view_mode.

    :param dict action: action descriptor dictionary to generate a views key for
    """
    view_id = action.get("view_id") or False
    if isinstance(view_id, (list, tuple)):
        view_id = view_id[0]

    # No default: a missing view_mode is a caller bug, let it raise KeyError.
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
    """Resolve an action from a URL path segment.

    Accepted formats:
    * ``action-<id>`` — record id
    * ``action-<xmlid>`` — XML id
    * ``m-<model>`` — model name (act_window's res_model)
    * ``<dotted.model>`` — model name
    * ``<path>`` — ir.actions path
    """
    Actions = env["ir.actions.actions"]

    if path_part.startswith("action-"):
        someid = path_part.removeprefix("action-")
        if someid.isdigit():  # record id
            action = Actions.sudo().browse(int(someid)).exists()
        elif "." in someid:  # xml id
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
        action = Actions.sudo().search([("path", "=", path_part)])

    if action and action._name == "ir.actions.actions":
        action_type = action.read(["type"])[0]["type"]
        action = env[action_type].browse(action.id)

    return action


def get_action_triples(
    env: Any, path: str, *, start_pos: int = 0
) -> Iterator[tuple[int | None, Any, int | None]]:
    """
    Extract the triples (active_id, action, record_id) from a "/odoo"-like path.

    >>> env = ...
    >>> list(get_action_triples(env, "/all-tasks/5/project.project/1/tasks"))
    [
        # active_id, action,                     record_id
        ( None,      ir.actions.act_window(...), 5         ), # all-tasks
        ( 5,         ir.actions.act_window(...), 1         ), # project.project
        ( 1,         ir.actions.act_window(...), None      ), # tasks
    ]
    """
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

        if len(parts) > 1 and parts[0].isdigit():  # new active id
            active_id = int(parts.popleft())
        elif record_id:
            active_id = record_id


def _get_login_redirect_url(uid: int, redirect: str | None = None) -> str:
    """Return the post-login redirect URL, accounting for a partial (MFA) session."""
    if request.session.uid:  # fully logged
        if redirect and _is_local_url(redirect):
            return redirect
        return (
            "/odoo"
            if is_user_internal(request.session.uid)
            else "/web/login_successful"
        )

    # partial session (MFA)
    url = request.env(user=uid)["res.users"].browse(uid)._mfa_url()
    if not redirect or not _is_local_url(redirect):
        return url

    parsed = urlsplit(url)
    qs = dict(parse_qsl(parsed.query))
    qs["redirect"] = redirect
    return urlunsplit(parsed._replace(query=urlencode(qs)))


def is_user_internal(uid: int) -> bool:
    """Check if a user is an internal (employee) user."""
    return request.env["res.users"].browse(uid)._is_internal()


def _local_web_translations(trans_file: str) -> list[dict[str, str]] | None:
    """Parse a .po file and extract JavaScript translation entries."""
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
