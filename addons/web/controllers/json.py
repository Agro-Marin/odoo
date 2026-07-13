"""HTTP controller for the /json API route.

View/domain resolution helpers live in ``json_helpers.py``.
"""

import ast
import logging
from datetime import date
from http import HTTPStatus
from urllib.parse import urlencode

import psycopg.errors
from lxml import etree
from werkzeug.exceptions import BadRequest, NotFound

from odoo import http
from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.http import request
from odoo.tools.safe_eval import safe_eval

from .json_helpers import (
    get_date_domain,
    get_default_domain,
    get_groupby,
    get_view_id_and_type,
)
from .utils import get_action_triples

_logger = logging.getLogger(__name__)


class WebJsonController(http.Controller):
    # for /json, the route should work in a browser, therefore type=http
    @http.route("/json/<path:subpath>", auth="user", type="http", readonly=True)
    def web_json(self, subpath, **kwargs):
        self._check_json_route_active()
        return request.redirect(
            f"/json/1/{subpath}?{urlencode(kwargs)}",
            HTTPStatus.TEMPORARY_REDIRECT,
        )

    @http.route("/json/1/<path:subpath>", auth="bearer", type="http", readonly=True)
    def web_json_1(self, subpath, **kwargs):
        """Get the JSON representation of the action/view for the same /odoo `subpath`.

        Behaviour:
        - If the path resolves to a record (a record id is present), use the
          `form` view_type; otherwise use the given view_type or the action's
          preferred one.
        - A form view reads through `web_read`.
        - A groupby (explicit or from a pivot/graph view) reads through
          `web_read_group`; otherwise falls back to a search read.
        - Whenever a parameter gets a resolved default that wasn't in the
          original URL (groupby, dates, domain, ...), redirect to the
          canonical URL with that parameter made explicit.

        :param subpath: Path to the (window) action to execute
        :param view_type: Requested view type
        :param domain: The domain for searches
        :param offset: Result offset
        :param limit: Result limit; falls back to the action's limit when
                      unset or 0
        :param groupby: Comma-separated string; when set, executes a `web_read_group`
                        and groups by the given fields
        :param fields: Comma-separated field list; aggregated fields when
                      grouping, extra fields added to the read spec otherwise
        :param start_date: When applicable, minimum date (inclusive bound)
        :param end_date: When applicable, maximum date (exclusive bound)
        """
        self._check_json_route_active()
        if not request.env.user.has_group("base.group_allow_export"):
            raise AccessError(
                request.env._("You need export permissions to use the /json route")
            )

        # kwargs below may gain resolved defaults (domain, dates, groupby...);
        # redirect once at the end to a canonical URL with everything explicit.
        param_list = set(kwargs)

        def check_redirect():
            if param_list == set(kwargs):
                return None
            # for domains, make chars as safe
            encoded_kwargs = urlencode(kwargs, safe="()[], '\"")
            return request.redirect(
                f"/json/1/{subpath}?{encoded_kwargs}",
                HTTPStatus.TEMPORARY_REDIRECT,
            )

        env = request.env
        action, context, eval_context, record_id = self._get_action(subpath)
        model = env[action.res_model].with_context(context)

        view_type = kwargs.get("view_type")
        if not view_type and record_id:
            view_type = "form"
        view_id, view_type = get_view_id_and_type(action, view_type)
        view = model.get_view(view_id, view_type)
        spec = model._get_fields_spec(view)

        if view_type == "form" or record_id:
            if redirect := check_redirect():
                return redirect
            if not record_id:
                raise BadRequest(env._("Missing record id"))
            record = model.browse(int(record_id))
            # ``record_id`` is attacker-controlled from the URL path: a
            # well-formed but non-existent/inaccessible id makes ``web_read``
            # return ``[]``. Surface a 404 instead of an IndexError-driven 500.
            res = record.web_read(spec)
            if not res:
                raise NotFound
            return request.make_json_response(res[0])

        domains = [safe_eval(action.domain or "[]", eval_context)]
        if "domain" in kwargs:
            # User-supplied domain: literal_eval only, never safe_eval, since
            # it comes from the URL and must not be able to run arbitrary code.
            user_domain = ast.literal_eval(kwargs.get("domain") or "[]")
            domains.append(user_domain)
        else:
            default_domain = get_default_domain(model, action, context, eval_context)
            if default_domain and not Domain(default_domain).is_true():
                kwargs["domain"] = repr(list(default_domain))
            domains.append(default_domain)
        try:
            limit = int(kwargs.get("limit", 0)) or action.limit
            offset = int(kwargs.get("offset", 0))
        except ValueError as exc:
            raise BadRequest(exc.args[0]) from exc
        if "offset" not in kwargs:
            kwargs["offset"] = offset
        if "limit" not in kwargs:
            kwargs["limit"] = limit

        view_tree = etree.fromstring(view["arch"])

        if view_type in ("calendar", "gantt", "cohort"):
            try:
                start_date = date.fromisoformat(kwargs["start_date"])
                end_date = date.fromisoformat(kwargs["end_date"])
            except ValueError as exc:
                raise BadRequest(exc.args[0]) from exc
            except KeyError:
                start_date = end_date = None
            try:
                date_domain = get_date_domain(start_date, end_date, view_tree)
            except ValueError as exc:
                raise BadRequest(exc.args[0]) from exc
            domains.append(date_domain)
            if "start_date" not in kwargs or "end_date" not in kwargs:
                kwargs.update(
                    {
                        "start_date": date_domain[0][2].isoformat(),
                        "end_date": date_domain[1][2].isoformat(),
                    }
                )

        if view_type == "activity":
            domains.append([("activity_ids", "!=", False)])
            for field_name, field in model._fields.items():
                if (
                    field_name.startswith("activity_")
                    and field_name not in spec
                    and model._has_field_access(field, "read")
                ):
                    spec[field_name] = {}

        groupby, fields = get_groupby(
            view_tree, kwargs.get("groupby"), kwargs.get("fields")
        )
        if fields:
            invalid = [f for f in fields if ":" not in f and f not in model._fields]
            if invalid:
                raise BadRequest(
                    env._(
                        "Unknown fields for %(model)s: %(fields)s",
                        model=model._name,
                        fields=", ".join(invalid),
                    )
                )
            aggregates = [
                (
                    f"{fname}:{model._fields[fname].aggregator}"
                    if ":" not in fname
                    else fname
                )
                for fname in fields
            ]
        else:
            aggregates = ["__count"]

        if groupby is not None and not kwargs.get("groupby"):
            kwargs["groupby"] = ",".join(groupby)
            if "fields" not in kwargs and fields:
                kwargs["fields"] = ",".join(fields)
        if groupby is None and fields:
            for field in fields:
                spec.setdefault(field, {})

        if redirect := check_redirect():
            return redirect
        domain = Domain.AND(domains)
        if groupby:
            res = model.web_read_group(
                domain,
                aggregates=aggregates,
                groupby=groupby,
                limit=limit,
                offset=offset,
            )
            # __extra_domain is for the JS client's own subgroup queries, not
            # for /json API consumers — drop it from each group.
            for value in res["groups"]:
                del value["__extra_domain"]
        else:
            res = model.web_search_read(
                domain,
                spec,
                limit=limit,
                offset=offset,
            )
        # web_read_group/web_search_read are @versioned (odoo.tools.cache_version):
        # they stamp an internal __version sha256 hash for the web client's JS
        # rpc cache. Not part of the public /json contract — strip it here too.
        res.pop("__version", None)
        return request.make_json_response(res)

    def _check_json_route_active(self):
        """Verify the /json route is enabled (demo mode or config param)."""
        # su=True: reading base.module_base (ir.module.module) may be denied
        # to the current user, but this check must run regardless.
        sudo_env = request.env(su=True)
        if not (
            sudo_env.ref("base.module_base").demo
            or sudo_env["ir.config_parameter"].get_param("web.json.enabled")
        ):
            raise NotFound

    def _get_action(self, subpath):
        """Resolve the action from the URL *subpath*."""

        def get_action_triples_():
            try:
                yield from get_action_triples(request.env, subpath, start_pos=1)
            except ValueError as exc:
                raise BadRequest(exc.args[0]) from exc

        context = dict(request.env.context)
        active_id, action, record_id = list(get_action_triples_())[-1]
        action = action.sudo()
        if action.usage == "ir_actions_server" and action.path:
            # force read-only evaluation of action_data
            try:
                with action.pool.cursor(readonly=True) as ro_cr:
                    if not ro_cr.readonly:
                        ro_cr.connection.read_only = True
                    if not ro_cr.readonly:
                        msg = "Failed to obtain a read-only cursor for server action evaluation"
                        raise RuntimeError(msg)
                    action_data = action.with_env(action.env(cr=ro_cr, su=False)).run()
            except psycopg.errors.ReadOnlySqlTransaction as e:
                # The server action tried to write. Reject instead of letting
                # this escape: since /json is a readonly=True route, an
                # uncaught ReadOnlySqlTransaction here would trigger the
                # dispatcher's normal RO->RW retry and let the action write.
                raise AccessError(action.env._("Unsupported server action")) from e
            except ValueError as e:
                # safe_eval wraps any non-bubbled exception (ReadOnlySqlTransaction
                # included) into a ValueError whose message embeds repr(exc).
                if "ReadOnlySqlTransaction" not in e.args[0]:
                    raise
                raise AccessError(action.env._("Unsupported server action")) from e
            action = action.env[action_data["type"]]
            action = action.new(
                action_data, origin=action.browse(action_data.pop("id"))
            )
        if action._name != "ir.actions.act_window":
            e = f"{action._name} are not supported server-side"
            raise BadRequest(e)
        eval_context = dict(
            action._get_eval_context(action),
            active_id=active_id,
            context=context,
            allowed_company_ids=request.env.user.company_ids.ids,
        )
        context.update(safe_eval(action.context, eval_context))
        return action, context, eval_context, record_id
