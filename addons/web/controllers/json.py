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
    @http.route("/json/<path:subpath>", auth="user", type="http", readonly=True)
    def web_json(self, subpath, **kwargs):
        self._check_json_route_active()
        return request.redirect(
            f"/json/1/{subpath}?{urlencode(kwargs)}",
            HTTPStatus.TEMPORARY_REDIRECT,
        )

    @http.route("/json/1/<path:subpath>", auth="bearer", type="http", readonly=True)
    def web_json_1(self, subpath, **kwargs):
        self._check_json_route_active()
        if not request.env.user.has_group("base.group_allow_export"):
            raise AccessError(
                request.env._("You need export permissions to use the /json route")
            )

        param_list = set(kwargs)

        def check_redirect():
            if param_list == set(kwargs):
                return None
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
            return self._get_json_record(model, spec, record_id)

        domains = self._get_json_domains(model, action, context, eval_context, kwargs)
        limit, offset = self._get_json_window(action, kwargs)

        view_tree = etree.fromstring(view["arch"])

        if view_type in ("calendar", "gantt", "cohort"):
            domains.append(self._get_json_date_domain(view_tree, kwargs))

        if view_type == "activity":
            domains.append([("activity_ids", "!=", False)])
            self._update_json_activity_spec(model, spec)

        groupby, fields = get_groupby(
            view_tree, kwargs.get("groupby"), kwargs.get("fields")
        )
        aggregates = self._get_json_aggregates(model, fields)

        if groupby is not None and not kwargs.get("groupby"):
            kwargs["groupby"] = ",".join(groupby)
            if "fields" not in kwargs and fields:
                kwargs["fields"] = ",".join(fields)
        if groupby is None and fields:
            for field in fields:
                spec.setdefault(field, {})

        if redirect := check_redirect():
            return redirect
        return self._get_json_listing(
            model, Domain.AND(domains), spec, groupby, aggregates, limit, offset
        )

    def _get_json_record(self, model, spec, record_id):
        """The single record `subpath` addressed, as a JSON response."""
        if not record_id:
            raise BadRequest(request.env._("Missing record id"))
        res = model.browse(int(record_id)).web_read(spec)
        if not res:
            raise NotFound
        return request.make_json_response(res[0])

    def _get_json_listing(
        self, model, domain, spec, groupby, aggregates, limit, offset
    ):
        """The grouped or flat listing `subpath` addressed, as a JSON response."""
        if groupby:
            res = model.web_read_group(
                domain,
                aggregates=aggregates,
                groupby=groupby,
                limit=limit,
                offset=offset,
            )
            for value in res["groups"]:
                del value["__extra_domain"]
        else:
            res = model.web_search_read(
                domain,
                spec,
                limit=limit,
                offset=offset,
            )
        res.pop("__version", None)
        return request.make_json_response(res)

    def _get_json_domains(self, model, action, context, eval_context, kwargs):
        """The action's domain, plus the caller's or the view's default one."""
        domains = [safe_eval(action.domain or "[]", eval_context)]
        if "domain" in kwargs:
            try:
                user_domain = ast.literal_eval(kwargs.get("domain") or "[]")
            except (ValueError, SyntaxError) as exc:
                raise BadRequest(f"Invalid domain: {exc}") from exc
            domains.append(user_domain)
        else:
            default_domain = get_default_domain(model, action, context, eval_context)
            if default_domain and not Domain(default_domain).is_true():
                kwargs["domain"] = repr(list(default_domain))
            domains.append(default_domain)
        return domains

    def _get_json_window(self, action, kwargs):
        """The `(limit, offset)` pair, echoed back into `kwargs` when defaulted."""
        try:
            limit = int(kwargs.get("limit", 0)) or action.limit
            offset = int(kwargs.get("offset", 0))
        except ValueError as exc:
            raise BadRequest(exc.args[0]) from exc
        if "offset" not in kwargs:
            kwargs["offset"] = offset
        if "limit" not in kwargs:
            kwargs["limit"] = limit
        return limit, offset

    def _get_json_date_domain(self, view_tree, kwargs):
        """The date window a calendar/gantt/cohort view reads, defaulted from it."""
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
        if "start_date" not in kwargs or "end_date" not in kwargs:
            kwargs.update(
                {
                    "start_date": date_domain[0][2].isoformat(),
                    "end_date": date_domain[1][2].isoformat(),
                }
            )
        return date_domain

    def _update_json_activity_spec(self, model, spec):
        """Add the readable `activity_*` fields an activity view needs to `spec`."""
        for field_name, field in model._fields.items():
            if (
                field_name.startswith("activity_")
                and field_name not in spec
                and model._has_field_access(field, "read")
            ):
                spec[field_name] = {}

    def _get_json_aggregates(self, model, fields):
        """`fields` as read_group aggregate specs, or `__count` when there are none."""
        if not fields:
            return ["__count"]
        env = request.env
        invalid = [f for f in fields if ":" not in f and f not in model._fields]
        if invalid:
            raise BadRequest(
                env._(
                    "Unknown fields for %(model)s: %(fields)s",
                    model=model._name,
                    fields=", ".join(invalid),
                )
            )
        not_aggregatable = [
            f for f in fields if ":" not in f and model._fields[f].aggregator is None
        ]
        if not_aggregatable:
            raise BadRequest(
                env._(
                    "Fields not aggregatable for %(model)s: %(fields)s",
                    model=model._name,
                    fields=", ".join(not_aggregatable),
                )
            )
        return [
            f"{fname}:{model._fields[fname].aggregator}" if ":" not in fname else fname
            for fname in fields
        ]

    def _check_json_route_active(self):
        sudo_env = request.env(su=True)
        if not (
            sudo_env.ref("base.module_base").demo
            or sudo_env["ir.config_parameter"].get_param("web.json.enabled")
        ):
            raise NotFound

    def _get_action(self, subpath):
        def get_action_triples_():
            try:
                yield from get_action_triples(request.env, subpath, start_pos=1)
            except ValueError as exc:
                raise BadRequest(exc.args[0]) from exc

        context = dict(request.env.context)
        active_id, action, record_id = list(get_action_triples_())[-1]
        action = action.sudo()
        if action.usage == "ir_actions_server" and action.path:
            try:
                with action.pool.cursor(readonly=True) as ro_cr:
                    if not ro_cr.readonly:
                        ro_cr.connection.read_only = True
                    if not ro_cr.readonly:
                        msg = "Failed to obtain a read-only cursor for server action evaluation"
                        raise RuntimeError(msg)
                    action_data = action.with_env(action.env(cr=ro_cr, su=False)).run()
            except psycopg.errors.ReadOnlySqlTransaction as e:
                raise AccessError(action.env._("Unsupported server action")) from e
            except ValueError as e:
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
