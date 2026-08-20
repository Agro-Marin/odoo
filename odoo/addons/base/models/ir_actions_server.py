import contextlib
import ipaddress
import json
import logging
import socket
from functools import partial, reduce
from operator import getitem
from typing import Any, Self
from urllib.parse import urlparse

import babel

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.datetime import utc
from odoo.libs.json import OPT_SORT_KEYS
from odoo.libs.json import dumps as json_dumps
from odoo.tools import _, get_lang
from odoo.tools.misc import unquote
from odoo.tools.safe_eval import safe_eval, test_python_expr

_logger = logging.getLogger(__name__)
_server_action_logger = logging.getLogger(
    "odoo.addons.base.models.ir_actions.server_action_safe_eval"
)


def _webhook_url_blocked_reason(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "malformed URL"
    if parsed.scheme not in ("http", "https"):
        return f"unsupported scheme {parsed.scheme!r}"
    hostname = parsed.hostname
    if not hostname:
        return "missing host"

    candidates: list[ipaddress._BaseAddress] = []
    try:
        candidates.append(ipaddress.ip_address(hostname.strip("[]")))
    except ValueError:
        try:
            candidates.extend(
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(
                    hostname, parsed.port or None, proto=socket.IPPROTO_TCP
                )
            )
        except OSError, ValueError:
            return None

    for ip in candidates:
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return f"blocked address {ip} (not a globally routable range)"
    return None


def _webhook_log_target(url: str) -> str:
    """Name a webhook's receiver for a log line, without quoting its secret.

    :param str url: the configured webhook URL
    :return: something an operator can act on
    :rtype: str

    The host alone, because a webhook URL routinely IS the credential. Slack,
    Discord and Teams all put the token in the path
    (`hooks.slack.com/services/T…/B…/<token>`), others put it in the query, and
    this action used to log the whole thing five times per call at INFO — so
    every log file, every log aggregator and every pasted traceback carried a
    live secret that grants posting rights to the channel.

    Dropping the path costs the one thing it was good for: telling two webhooks
    on the same host apart. The action name is a better answer to that anyway
    and now travels with every line, and the full URL is a field on the action
    for anyone who needs it. Masking selectively was the alternative and was
    rejected: it means a list of which vendors hide secrets where, which is a
    list that is wrong the first time a vendor is added to it.
    """
    try:
        return urlparse(url).hostname or "<unknown host>"
    except ValueError:
        return "<malformed URL>"


def _webhook_scrub(message: str, url: str, target: str) -> str:
    """Take the webhook URL back out of somebody else's error text.

    :param str message: the exception's own words
    :param str url: the configured webhook URL
    :param str target: what `_webhook_log_target` called the receiver
    :return: the message with the URL replaced
    :rtype: str

    Not keeping the URL out of our own log lines is only half of it, because
    the libraries quote it back at us. Measured:

        HTTPError    404 Client Error: … for url: https://hooks.slack.com/services/T…/B…/<token>
        ConnError    HTTPSConnectionPool(host='…', port=443): Max retries exceeded
                     with url: /services/T…/B…/<token> (Caused by …)

    So the full URL comes back from `raise_for_status`, and urllib3 quotes the
    path on its own. Both are replaced, longest first so the full URL wins over
    its own path. Exact substrings of a string we already hold — no pattern
    matching, nothing to be wrong about — and a path of "/" or shorter is left
    alone rather than substituted into every separator in the sentence.
    """
    parsed = urlparse(url)
    needles = [url]
    if parsed.query:
        needles.append(f"{parsed.path}?{parsed.query}")
    if len(parsed.path) > 1:
        needles.append(parsed.path)
    for needle in needles:
        message = message.replace(needle, f"<{target} webhook URL>")
    return message


class LoggerProxy:
    _ALLOWED = frozenset({"log", "info", "warning", "error", "exception"})

    def __getattr__(self, name: str) -> Any:
        if name in self._ALLOWED:
            return getattr(_server_action_logger, name)
        msg = f"LoggerProxy has no attribute {name!r}"
        raise AttributeError(msg)


_LOGGER_PROXY = LoggerProxy()


class IrActionsServerHistory(models.Model):
    _name = "ir.actions.server.history"
    _description = "Server Action History"
    _order = "create_date desc, id desc"
    _max_entries_per_action = 100

    action_id = fields.Many2one("ir.actions.server", required=True, ondelete="cascade")
    code = fields.Text()

    @api.depends("create_date", "create_uid")
    def _compute_display_name(self) -> None:
        self.display_name = False
        locale = get_lang(self.env).code
        tzinfo = self.env.tz
        for history in self.filtered("create_date"):
            dt = history.create_date.replace(microsecond=0, tzinfo=utc)
            if tzinfo:
                dt = dt.astimezone(tzinfo)
            date_label = babel.dates.format_datetime(
                dt,
                tzinfo=tzinfo,
                locale=locale,
            )
            history.display_name = _(
                "%(date_label)s - %(author)s",
                date_label=date_label,
                author=history.create_uid.name,
            )

    @api.autovacuum
    def _gc_histories(self) -> None:
        result = self._read_group(
            domain=[],
            groupby=["action_id"],
            aggregates=["id:recordset"],
            having=[("__count", ">", self._max_entries_per_action)],
        )
        to_clean = self
        for _action_id, history_ids in result:
            to_clean |= history_ids.sorted()[self._max_entries_per_action :]
        to_clean.unlink()


WEBHOOK_SAMPLE_VALUES = {
    "integer": 42,
    "float": 42.42,
    "monetary": 42.42,
    "char": "Hello World",
    "text": "Hello World",
    "html": "<p>Hello World</p>",
    "boolean": True,
    "selection": "option1",
    "date": "2020-01-01",
    "datetime": "2020-01-01 00:00:00",
    "binary": "<base64_data>",
    "many2one": 47,
    "many2many": [42, 47],
    "one2many": [42, 47],
    "reference": "res.partner,42",
    None: "some_data",
}

CRUD_STATES = ("object_write", "object_create", "object_copy")


class ServerActionWithWarningsError(UserError):
    pass


class IrActionsServer(models.Model):
    _name = "ir.actions.server"
    _description = "Server Actions"
    _table = "ir_act_server"
    _inherit = ["ir.actions.actions"]
    _order = "sequence,name,id"
    _allow_sudo_commands = False

    @api.model
    def _default_update_path(self) -> str:
        if not self.env.context.get("default_model_id"):
            return ""
        ir_model = self.env["ir.model"].browse(self.env.context["default_model_id"])
        model = self.env[ir_model.model]
        sensible_default_fields = [
            "partner_id",
            "user_id",
            "user_ids",
            "stage_id",
            "state",
            "active",
        ]
        for field_name in sensible_default_fields:
            if field_name in model._fields and not model._fields[field_name].readonly:
                return field_name
        return ""

    name = fields.Char(compute="_compute_name", store=True, readonly=False)
    automated_name = fields.Char(compute="_compute_name", store=True)
    type = fields.Char(default="ir.actions.server")
    usage = fields.Selection(
        [
            ("ir_actions_server", "Server Action"),
            ("ir_cron", "Scheduled Action"),
        ],
        string="Usage",
        default="ir_actions_server",
        required=True,
    )
    state = fields.Selection(
        [
            ("object_write", "Update Record"),
            ("object_create", "Create Record"),
            ("object_copy", "Duplicate Record"),
            ("code", "Execute Code"),
            ("webhook", "Send Webhook Notification"),
            ("multi", "Multi Actions"),
        ],
        string="Type",
        required=True,
        copy=True,
        help="Type of server action. The following values are available:\n"
        "- 'Update Record': update the values of a record\n"
        "- 'Create Record': create a new record with new values\n"
        "- 'Duplicate Record': copy an existing record\n"
        "- 'Execute Code': a block of Python code that will be executed\n"
        "- 'Send Webhook Notification': send a POST request to an external system\n"
        "- 'Multi Actions': define an action that triggers several other server actions\n"
        "\nAdditional types may be added by other modules (e.g. Discuss, SMS).",
    )
    allowed_states = fields.Json(
        string="Allowed states", compute="_compute_allowed_states"
    )
    sequence = fields.Integer(
        default=5,
        help="When dealing with multiple actions, the execution order is "
        "based on the sequence. Low number means high priority.",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        ondelete="cascade",
        index=True,
        help="Model on which the server action runs.",
    )
    available_model_ids = fields.Many2many(
        "ir.model",
        string="Available Models",
        compute="_compute_available_model_ids",
        store=False,
    )
    model_name = fields.Char(related="model_id.model", string="Model Name")
    warning = fields.Text(string="Warning", compute="_compute_warning", recursive=True)
    ir_cron_ids = fields.One2many(
        "ir.cron",
        "ir_actions_server_id",
        "Scheduled Action",
        context={"active_test": False},
    )
    code = fields.Text(
        string="Python Code",
        groups="base.group_system",
        help="Write Python code that the action will execute. Some variables are "
        "available for use; help about python expression is given in the help tab.",
    )
    show_code_history = fields.Boolean(compute="_compute_show_code_history")
    parent_id = fields.Many2one(
        "ir.actions.server",
        string="Parent Action",
        index=True,
        ondelete="cascade",
    )
    child_ids = fields.One2many(
        "ir.actions.server",
        "parent_id",
        copy=True,
        domain=lambda self: str(self._get_children_domain()),
        string="Child Actions",
        help="Child server actions that will be executed. The global return value is the action returned by the last child that returns one; children that return nothing are skipped over.",
    )
    crud_model_id = fields.Many2one(
        "ir.model",
        string="Record to Create",
        compute="_compute_crud_relations",
        inverse="_set_crud_model_id",
        readonly=False,
        store=True,
        help="Specify which kind of record should be created. Set this field only to specify a different model than the base model.",
    )
    crud_model_name = fields.Char(
        related="crud_model_id.model", string="Target Model Name", readonly=True
    )
    link_field_id = fields.Many2one(
        "ir.model.fields",
        string="Link Field",
        help="Specify a field used to link the newly created record on the record used by the server action.",
    )
    group_ids = fields.Many2many(
        "res.groups",
        "ir_act_server_group_rel",
        "act_id",
        "gid",
        string="Allowed Groups",
        help="Groups that can execute the server action. Leave empty to allow everybody.",
    )

    update_field_id = fields.Many2one(
        "ir.model.fields",
        string="Field to Update",
        ondelete="cascade",
        compute="_compute_crud_relations",
        store=True,
        readonly=False,
    )
    update_path = fields.Char(
        string="Field to Update Path",
        help="Path to the field to update, e.g. 'partner_id.name'",
        default=_default_update_path,
    )
    update_related_model_id = fields.Many2one(
        "ir.model",
        compute="_compute_crud_relations",
        readonly=False,
        store=True,
    )
    update_field_type = fields.Selection(related="update_field_id.ttype", readonly=True)
    update_m2m_operation = fields.Selection(
        [
            ("add", "Adding"),
            ("remove", "Removing"),
            ("set", "Setting it to"),
            ("clear", "Clearing it"),
        ],
        string="Many2many Operations",
        default="add",
    )
    update_boolean_value = fields.Selection(
        [("true", "Yes (True)"), ("false", "No (False)")],
        string="Boolean Value",
        default="true",
    )

    value = fields.Text(
        help="For Python expressions, this field may hold a Python expression "
        "that can use the same values as for the code field on the server action,"
        "e.g. `env.user.name` to set the current user's name as the value "
        "or `record.id` to set the ID of the record on which the action is run.\n\n"
        "For Static values, the value will be used directly without evaluation, e.g."
        "`42` or `My custom name` or the selected record."
    )
    evaluation_type = fields.Selection(
        [
            ("value", "Update"),
            ("sequence", "Sequence"),
            ("equation", "Compute"),
        ],
        "Value Type",
        default="value",
        change_default=True,
    )
    html_value = fields.Html()
    sequence_id = fields.Many2one("ir.sequence", string="Sequence to use")
    resource_ref = fields.Reference(
        string="Record",
        selection="_selection_target_model",
        inverse="_set_resource_ref",
    )
    selection_value = fields.Many2one(
        "ir.model.fields.selection",
        string="Custom Value",
        ondelete="cascade",
        domain='[("field_id", "=", update_field_id)]',
        inverse="_set_selection_value",
    )

    value_field_to_show = fields.Selection(
        [
            ("value", "value"),
            ("html_value", "html_value"),
            ("sequence_id", "sequence_id"),
            ("resource_ref", "reference"),
            ("update_boolean_value", "update_boolean_value"),
            ("selection_value", "selection_value"),
        ],
        compute="_compute_value_field_to_show",
    )
    webhook_url = fields.Char(
        string="Webhook URL",
        help="URL to send the POST request to.\n\n"
        "The request is UNAUTHENTICATED: no credential, no signature, no "
        "retry, and no record of the exchange beyond the server log. That is "
        "the right shape for notifying a receiver that accepts an open URL.\n\n"
        "For anything that needs a credential, a retry policy, a rate limit, "
        "secret redaction or an auditable record of what was sent, use an "
        "'Execute Code' action against a configured outbound endpoint "
        "instead. With the API Transport application installed:\n"
        "    endpoint = env['api.endpoint.outbound'].search(\n"
        "        [('code', '=', 'my_service')], limit=1)\n"
        "    endpoint._get_api_client().post('/path', json={'id': record.id})\n"
        "That endpoint owns the credential, the retry policy and the "
        "api.event.log row.",
    )
    webhook_timeout = fields.Integer(
        string="Webhook Timeout (s)",
        default=1,
        help="Seconds to wait for the receiver before giving up.\n\n"
        "The default of 1 second is deliberately short, and the cost of "
        "raising it is paid by a worker: the call is made after the "
        "transaction commits, so the request thread is held for however long "
        "this allows.\n\n"
        "It is also short enough that a receiver which merely thinks for a "
        "moment times out, and a timeout here is genuinely ambiguous — the "
        "receiver may well have processed the payload. Raise it for a slow "
        "but trusted receiver; if delivery has to be certain, this action is "
        "the wrong tool (see Webhook URL).",
    )
    webhook_field_ids = fields.Many2many(
        "ir.model.fields",
        "ir_act_server_webhook_field_rel",
        "server_id",
        "field_id",
        string="Webhook Fields",
        help="Fields to send in the POST request. "
        "The id and model of the record are always sent as '_id' and '_model'. "
        "The name of the action that triggered the webhook is always sent as '_action'.",
    )
    webhook_sample_payload = fields.Text(
        string="Sample Payload", compute="_compute_webhook_sample_payload"
    )

    #: Ceiling on `webhook_timeout`. The call runs in `cr.postcommit`, so the
    #: request worker is held for its duration; a value in minutes turns one
    #: unreachable receiver into exhausted workers. Generous enough for any
    #: receiver worth waiting for synchronously, and a refusal that says why.
    _WEBHOOK_TIMEOUT_CEILING = 60

    @api.constrains("webhook_timeout")
    def _check_webhook_timeout(self) -> None:
        for action in self:
            if action.state != "webhook":
                continue
            if not 1 <= action.webhook_timeout <= self._WEBHOOK_TIMEOUT_CEILING:
                raise ValidationError(
                    _(
                        "Webhook timeout must be between 1 and %(ceiling)s "
                        "seconds. The call is made after the transaction "
                        "commits, so this is time a worker spends waiting; a "
                        "receiver that needs longer should be given a queue "
                        "rather than a synchronous webhook.",
                        ceiling=self._WEBHOOK_TIMEOUT_CEILING,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:

        def with_inherited(vals: ValuesType) -> ValuesType:
            if not (parent_id := vals.get("parent_id")):
                return vals
            parent = self.browse(parent_id)
            return {
                **vals,
                "model_id": parent.model_id.id,
                "group_ids": parent.group_ids.ids,
            }

        vals_list = [with_inherited(vals) for vals in vals_list]
        actions = super().create(vals_list)

        history_vals = []
        for action, vals in zip(actions, vals_list, strict=True):
            if "code" in vals:
                history_vals.append({"action_id": action.id, "code": vals.get("code")})
        if history_vals:
            self.env["ir.actions.server.history"].create(history_vals)

        return actions

    def write(self, vals: dict[str, Any]) -> bool:
        if "code" in vals:
            new_code = vals.get("code")
            history_vals = [
                {"action_id": action.id, "code": new_code}
                for action in self
                if new_code != action.code
            ]
            if history_vals:
                self.env["ir.actions.server.history"].create(history_vals)
        return super().write(vals)

    @api.depends("state", "code")
    def _compute_show_code_history(self) -> None:
        self.show_code_history = False
        code_actions = self.filtered(lambda a: a.state == "code")
        if not code_actions:
            return

        History = self.env["ir.actions.server.history"]
        all_history = History.search_fetch(
            [("action_id", "in", code_actions.ids)],
            ["action_id", "code"],
        )

        action_codes = {a.id: a.code for a in code_actions}
        actions_with_diff = set()
        for hist in all_history:
            aid = hist.action_id.id
            if aid not in actions_with_diff and hist.code != action_codes.get(aid):
                actions_with_diff.add(aid)

        for action in code_actions:
            action.show_code_history = action.id in actions_with_diff

    @api.model
    def _warning_depends(self) -> list[str]:
        return [
            "state",
            "model_id",
            "group_ids",
            "parent_id",
            "child_ids.warning",
            "child_ids.model_id",
            "child_ids.group_ids",
            "update_path",
            "update_field_type",
            "evaluation_type",
            "webhook_field_ids",
            "usage",
        ]

    def _get_child_warnings(self) -> list[str]:
        """What a `multi` action has to say about the actions it runs.

        Split out of `_get_warning_messages`, which is a chain of independent
        checks and was over the function-length budget: these three are the ones
        about somebody else's record rather than this one's own configuration.
        """
        self.ensure_one()
        warnings = []
        children_wrong_model = self.env["ir.actions.server"]
        children_wrong_groups = self.env["ir.actions.server"]
        children_with_warnings = self.env["ir.actions.server"]
        for child in self.child_ids:
            if self.model_id and child.model_id != self.model_id:
                children_wrong_model |= child
            if self.group_ids and child.group_ids != self.group_ids:
                children_wrong_groups |= child
            if child.warning:
                children_with_warnings |= child

        if children_wrong_model:
            warnings.append(
                _(
                    "Following child actions should have the same model (%(model)s): %(children)s",
                    model=self.model_id.name,
                    children=", ".join(children_wrong_model.mapped("name")),
                )
            )

        if children_wrong_groups:
            warnings.append(
                _(
                    "Following child actions should have the same groups (%(groups)s): %(children)s",
                    groups=", ".join(self.group_ids.mapped("name")),
                    children=", ".join(children_wrong_groups.mapped("name")),
                )
            )

        if children_with_warnings:
            warnings.append(
                _(
                    "Following child actions have warnings: %(children)s",
                    children=", ".join(children_with_warnings.mapped("name")),
                )
            )
        return warnings

    def _get_warning_messages(self) -> list[str]:
        self.ensure_one()
        warnings = self._get_child_warnings()

        if (
            (relation_chain := self._get_relation_chain("update_path"))
            and relation_chain[0]
            and isinstance(relation_chain[0][-1], fields.Json)
        ):
            warnings.append(
                _(
                    "JSON fields (such as '%s') are not supported.",
                    relation_chain[0][-1].string,
                )
            )

        if self.usage == "ir_cron" and self.state in (
            self._get_states_needing_a_live_record()
        ):
            warnings.append(
                _(
                    "A scheduled action runs on no record, and this one needs "
                    "one to act on. It would do nothing, every time it ran."
                )
            )

        if (
            self.state == "object_write"
            and self.evaluation_type == "sequence"
            and self.update_field_type
            and self.update_field_type not in ("char", "text")
        ):
            warnings.append(_("A sequence must only be used with character fields."))

        if self.state == "webhook" and self.model_id:
            restricted_fields = []
            Model = self.env[self.model_id.model]
            for model_field in self.webhook_field_ids:
                field = Model._fields.get(model_field.name)
                if field and field.groups:
                    restricted_fields.append(f"- {model_field.field_description}")
            if restricted_fields:
                warnings.append(
                    _(
                        "Group-restricted fields cannot be included in "
                        "webhook payloads, as it could allow any user to "
                        "accidentally leak sensitive information. You will "
                        "have to remove the following fields from the webhook payload:\n%(restricted_fields)s",
                        restricted_fields="\n".join(restricted_fields),
                    )
                )

        return warnings

    def _compute_allowed_states(self) -> None:
        self.allowed_states = [value for value, __ in self._fields["state"].selection]

    @api.depends(lambda self: self._warning_depends())
    def _compute_warning(self) -> None:
        for action in self:
            if warnings := action._get_warning_messages():
                action.warning = "\n\n".join(warnings)
            else:
                action.warning = False

    @api.model
    def _get_children_domain(self) -> Domain:
        return Domain(
            [
                ("model_id", "=", unquote("model_id")),
                ("parent_id", "=", False),
                ("id", "!=", unquote("id")),
            ]
        )

    def _generate_action_name(self) -> str:
        self.ensure_one()
        if self.state == "object_create":
            return _("Create %(model_name)s", model_name=self.crud_model_id.name)
        if self.state == "object_write":
            return _("Update %(model_name)s", model_name=self.crud_model_id.name)
        if self.state == "object_copy":
            if not self.crud_model_id or not self.resource_ref:
                return _("Duplicate ...")
            record = self.env[self.crud_model_id.model].browse(self.resource_ref.id)
            return _("Duplicate %(record)s", record=record.display_name)
        return dict(self._fields["state"]._description_selection(self.env)).get(
            self.state, ""
        )

    def _name_depends(self) -> list[str]:
        return [
            "state",
            "crud_model_id",
            "resource_ref",
        ]

    @api.depends(lambda self: self._name_depends())
    def _compute_name(self) -> None:
        for action in self:
            was_automated = action.name == action.automated_name
            action.automated_name = action._generate_action_name()
            if was_automated:
                action.name = action.automated_name

    @api.onchange("name")
    def _onchange_name(self) -> None:
        if not self.name:
            self.automated_name = self._generate_action_name()
            self.name = self.automated_name

    @api.depends_context("uid")
    def _compute_available_model_ids(self) -> None:
        allowed_models = self.env["ir.model"].search(
            [
                (
                    "model",
                    "in",
                    list(self.env["ir.model.access"]._get_allowed_models()),
                )
            ]
        )
        self.available_model_ids = allowed_models.ids

    @api.depends("model_id", "update_path", "state")
    def _compute_crud_relations(self) -> None:
        for action in self:
            action.update_related_model_id = False
            if action.model_id and action.state in CRUD_STATES:
                if action.state in ("object_create", "object_copy"):
                    action.crud_model_id = action.model_id
                    action.update_field_id = False
                    action.update_path = False
                elif action.state == "object_write":
                    if action.update_path:
                        model, field = action._traverse_path()
                        action.crud_model_id = model
                        action.update_field_id = field
                        if (
                            action.evaluation_type == "value"
                            and field
                            and field.relation
                        ):
                            action.update_related_model_id = action.env[
                                "ir.model"
                            ]._get_id(field.relation)
                    else:
                        action.crud_model_id = action.model_id
                        action.update_field_id = False
            else:
                action.crud_model_id = False
                action.update_field_id = False
                action.update_path = False

    def _traverse_path(self) -> tuple[Any, Any]:
        self.ensure_one()
        field_chain, _field_chain_str = self._get_relation_chain("update_path")
        if not field_chain:
            return False, False
        last_field = field_chain[-1]
        model_id = self.env["ir.model"]._get(last_field.model_name)
        field_id = self.env["ir.model.fields"]._get(
            last_field.model_name, last_field.name
        )
        return model_id, field_id

    def _get_relation_chain(
        self, searched_field_name: str, raise_on_error: bool = False
    ) -> tuple[list[Any], str]:
        self.ensure_one()
        if (
            not searched_field_name
            or searched_field_name not in self._fields
            or not self[searched_field_name]
            or not self.model_id
        ):
            return [], ""
        path = self[searched_field_name].split(".")
        model = self.env[self.model_id.model]
        chain = []
        for i, field_name in enumerate(path):
            is_last_field = i == len(path) - 1
            if not field_name:
                if raise_on_error:
                    raise ValidationError(
                        _(
                            "The path '%(path)s' contains an empty segment. "
                            "Remove the extra '.'.",
                            path=self[searched_field_name],
                        )
                    )
                return [], ""
            if field_name not in model._fields:
                if raise_on_error:
                    raise ValidationError(
                        _(
                            "Unknown field '%(field_name)s' on model '%(model_name)s'.",
                            field_name=field_name,
                            model_name=model._name,
                        )
                    )
                return [], ""
            field = model._fields[field_name]
            if not is_last_field:
                if not field.relational:
                    if raise_on_error:
                        current_field = field.get_description(self.env)["string"]
                        searched_field = self._fields[
                            searched_field_name
                        ].get_description(self.env)["string"]
                        raise ValidationError(
                            _(
                                "The path in field '%(searched_field)s' contains a non-relational field (%(current_field)s) that is not the last segment. Only the last field in a path may be non-relational.",
                                searched_field=searched_field,
                                current_field=current_field,
                            )
                        )
                    return [], ""
                model = self.env[field.comodel_name]
            chain.append(field)
        stringified_path = " > ".join(
            [field.get_description(self.env)["string"] for field in chain]
        )
        return chain, stringified_path

    @api.depends("state", "model_id.model", "webhook_field_ids", "name")
    def _compute_webhook_sample_payload(self) -> None:
        for action in self:
            if action.state != "webhook":
                action.webhook_sample_payload = False
                continue
            payload = {
                "_id": 1,
                "_model": action.model_id.model,
                "_action": f"{action.name}(#{action.id})",
            }
            if action.model_id:
                sample_record = (
                    self.env[action.model_id.model]
                    .with_context(active_test=False)
                    .search([], limit=1)
                )
                if sample_record:
                    payload["_id"] = sample_record.id
                    payload.update(
                        sample_record.read(
                            action.webhook_field_ids.mapped("name"), load=None
                        )[0]
                    )
                else:
                    for field in action.webhook_field_ids:
                        payload[field.name] = (
                            WEBHOOK_SAMPLE_VALUES[field.ttype]
                            if field.ttype in WEBHOOK_SAMPLE_VALUES
                            else WEBHOOK_SAMPLE_VALUES[None]
                        )
            action.webhook_sample_payload = json.dumps(
                payload, indent=4, sort_keys=True, default=str
            )

    @api.constrains("code")
    def _check_python_code(self) -> None:
        for action in self.sudo().filtered("code"):
            msg = test_python_expr(expr=action.code.strip(), mode="exec")
            if msg:
                raise ValidationError(msg)

    @api.constrains("update_path", "model_id", "state")
    def _check_update_path(self) -> None:
        for action in self:
            if (
                action.state == "object_write"
                and action.update_path
                and action.model_id
            ):
                action._get_relation_chain("update_path", raise_on_error=True)

    @api.constrains("parent_id", "child_ids")
    def _check_children(self) -> None:
        if self._has_cycle():
            raise ValidationError(_("Recursion found in child server actions"))

        if children_with_warnings := self.child_ids.filtered("warning"):
            raise ValidationError(
                _(
                    "Following child actions have warnings: %(children)s",
                    children=", ".join(children_with_warnings.mapped("name")),
                )
            )

    @api.model
    @tools.ormcache(cache="stable")
    def _unconditional_clear_fields(self) -> frozenset[str]:
        return super()._unconditional_clear_fields() | {"model_id"}

    def _menu_access_model_field(self) -> str:
        return "model_name"

    def _is_batchable(self) -> bool:
        """Whether the runner acts on the whole ``active_ids`` set at once.

        False for everything base contributes: those runners read ``active_id``
        and mean one record by it, and the ``record`` a user writes in a ``code``
        action means the same. A state whose runner takes ``active_ids`` as a set
        says so here, and a caller holding many records -- an automation rule is
        the one in the tree -- may then run it once instead of once per record.
        """
        self.ensure_one()
        if self.state == "multi":
            # a multi action does nothing itself: it hands its context to each
            # child, so it can take the batch exactly when all of them can
            return all(child._is_batchable() for child in self.child_ids)
        return False

    @api.model
    def _get_states_needing_a_live_record(self) -> frozenset[str]:
        """States whose action is meaningless once its record is gone.

        A caller that fires actions on records it is about to delete -- an
        `on_unlink` automation is the one in the tree -- asks this rather than
        keeping its own list of the states that mind, which is a copy that goes
        stale the moment a module contributes another one.
        """
        return frozenset()

    def _get_readable_fields(self) -> frozenset[str]:
        return super()._get_readable_fields() | {
            "group_ids",
            "model_name",
        }

    def _get_runner(self) -> tuple[Any, bool]:
        multi = True
        t = self.env.registry[self._name]
        fn = getattr(t, f"_run_action_{self.state}_multi", None)
        if not fn:
            multi = False
            fn = getattr(t, f"_run_action_{self.state}", None)
        return fn, multi

    def create_action(self) -> bool:
        self.check_access("write")
        for model_id, actions in self.grouped("model_id").items():
            actions.write({"binding_model_id": model_id.id, "binding_type": "action"})
        return True

    def unlink_action(self) -> bool:
        self.check_access("write")
        self.filtered("binding_model_id").write({"binding_model_id": False})
        return True

    def history_wizard_action(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Code History"),
            "target": "new",
            "views": [(False, "form")],
            "res_model": "server.action.history.wizard",
            "context": {"default_action_id": self.id},
        }

    def _run_action_code_multi(self, eval_context: dict[str, Any]) -> Any:
        if not self.code:
            return None
        safe_eval(self.code.strip(), eval_context, mode="exec", filename=str(self))
        return eval_context.get("action")

    def _run_action_multi(self, eval_context: dict[str, Any] | None = None) -> Any:
        res = False
        for act in self.child_ids.sorted():
            res = act.run() or res
        return res

    def _run_action_object_write(
        self, eval_context: dict[str, Any] | None = None
    ) -> None:
        vals = self._eval_value(eval_context=eval_context)
        res = {action.update_field_id.name: vals[action.id] for action in self}

        if self.env.context.get("onchange_self"):
            record_cached = self.env.context["onchange_self"]
            for field, new_value in res.items():
                record_cached[field] = new_value
        elif self.update_path:
            starting_record = self.env[self.model_id.model].browse(
                self.env.context.get("active_id")
            )
            path = self.update_path.split(".")
            target_records = reduce(getitem, path[:-1], starting_record)
            target_records.write(res)
        else:
            raise UserError(
                _(
                    "The 'Update Record' action '%(name)s' has no field to update. "
                    "Please set an update path.",
                    name=self.name,
                )
            )

    def _run_action_webhook(self, eval_context: dict[str, Any] | None = None) -> None:
        record = self.env[self.model_id.model].browse(self.env.context.get("active_id"))
        url = self.webhook_url
        if not record:
            return
        if not url:
            raise UserError(
                _(
                    "The webhook action '%(name)s' has no URL to send the request "
                    "to. Please set a Webhook URL.",
                    name=self.name,
                )
            )
        if blocked := _webhook_url_blocked_reason(url):
            raise UserError(
                _(
                    "The webhook action '%(name)s' targets a forbidden address "
                    "(%(reason)s). Webhooks may only call public hosts.",
                    name=self.name,
                    reason=blocked,
                )
            )
        vals = {
            "_model": self.model_id.model,
            "_id": record.id,
            "_action": f"{self.name}(#{self.id})",
        }
        if self.webhook_field_ids:
            vals.update(
                record.read(self.webhook_field_ids.mapped("name"), load=None)[0]
            )
        json_values = json_dumps(vals, default=str, option=OPT_SORT_KEYS)

        # Captured as plain values, not read off `self` inside the closures:
        # they run after the transaction ends, when reading a field would query
        # a cursor that is no longer the one this action was loaded on.
        action_label = vals["_action"]
        timeout = self.webhook_timeout or 1
        # The URL itself never reaches the log -- see `_webhook_log_target`. It
        # still reaches `requests`, which is the only place it belongs.
        target = _webhook_log_target(url)

        _logger.info("Webhook %s to %s", action_label, target)
        _logger.debug("POST JSON data for webhook call: %s", json_values)
        deliver = self._webhook_delivery(url, timeout, action_label, target)

        @self.env.cr.postrollback.add
        def _add_post_rollback():
            _logger.warning(
                "Webhook %s to %s cancelled: the transaction rolled back",
                action_label,
                target,
            )

        @self.env.cr.postcommit.add
        def _add_post_commit():
            deliver(json_values)

    def _webhook_delivery(self, url, timeout, action_label, target):
        """Return the callable that actually sends the webhook.

        :param str url: where to POST
        :param int timeout: seconds
        :param str action_label: `name(#id)`, for the log
        :param str target: the receiver's host — see `_webhook_log_target`
        :return: a callable taking the JSON body
        :rtype: collections.abc.Callable[[str], None]

        A **plain closure over plain values**, deliberately, rather than a bound
        method. What it returns runs from a `postcommit` hook, after the
        transaction has ended and the cursor it was built on is gone, so
        anything that reads a field there queries a dead cursor. Returning a
        closure makes the boundary explicit and puts every ORM read on this side
        of it: an override decides how to send *while it still can*, and hands
        back something that no longer needs the ORM.

        The delivery is unauthenticated by design at this layer. `base` has no
        credential store and cannot depend on one; a module that does —
        `api_transport` — overrides this to send through a configured endpoint.
        """
        return partial(
            self._webhook_deliver_unauthenticated, url, timeout, action_label, target
        )

    @staticmethod
    def _webhook_deliver_unauthenticated(
        url, timeout, action_label, target, json_values
    ):
        """POST the payload with no credential, which is all `base` can do."""
        _logger.debug("Webhook %s to %s - start", action_label, target)
        import requests

        try:
            response = requests.post(
                url,
                data=json_values,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            response.raise_for_status()
            _logger.info("Webhook %s to %s - succeeded", action_label, target)
        except requests.exceptions.ReadTimeout:
            _logger.warning(
                "Webhook %s to %s timed out after %ss. The receiver may or "
                "may not have processed it. Raise 'Webhook Timeout (s)' on "
                "the action if the receiver is simply slow; if delivery has "
                "to be certain, this action cannot give you that.",
                action_label,
                target,
                timeout,
            )
        except requests.exceptions.RequestException as e:
            _logger.error(
                "Webhook %s to %s failed and will NOT be retried: %s",
                action_label,
                target,
                _webhook_scrub(str(e), url, target),
            )

    def _link_to_active_record(self, new_id: int) -> None:
        if not self.link_field_id:
            return
        record = self.env[self.model_id.model].browse(self.env.context.get("active_id"))
        if self.link_field_id.ttype in ("one2many", "many2many"):
            record.write({self.link_field_id.name: [Command.link(new_id)]})
        else:
            record.write({self.link_field_id.name: new_id})

    def _run_action_object_copy(
        self, eval_context: dict[str, Any] | None = None
    ) -> None:
        if not self.resource_ref:
            raise UserError(_("No record selected to duplicate."))
        dupe = self.env[self.crud_model_id.model].browse(self.resource_ref.id).copy()
        self._link_to_active_record(dupe.id)

    def _run_action_object_create(
        self, eval_context: dict[str, Any] | None = None
    ) -> None:
        res_id, _res_name = self.env[self.crud_model_id.model].name_create(self.value)
        self._link_to_active_record(res_id)

    def _get_eval_context(self, action: Self) -> dict[str, Any]:

        def log(message, level="info"):
            with self.pool.cursor() as cr:
                cr.execute(
                    """
                    INSERT INTO ir_logging(create_date, create_uid, type, dbname, name, level, message, path, line, func)
                    VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        self.env.uid,
                        "server",
                        self.env.cr.dbname,
                        __name__,
                        level,
                        message,
                        "action",
                        action.id,
                        action.name,
                    ),
                )

        eval_context = super()._get_eval_context(action=action)
        model_name = action.model_id.sudo().model
        model = self.env[model_name]
        record = None
        records = None
        if self.env.context.get("active_model") == model_name:
            if self.env.context.get("active_id"):
                record = model.browse(self.env.context["active_id"])
            if self.env.context.get("active_ids"):
                records = model.browse(self.env.context["active_ids"])
        if self.env.context.get("onchange_self"):
            record = self.env.context["onchange_self"]
        eval_context.update(
            {
                "env": self.env,
                "model": model,
                "UserError": UserError,
                "record": record,
                "records": records,
                "log": log,
                "_logger": _LOGGER_PROXY,
            }
        )
        return eval_context

    def _get_target_records(self, action: Self | None = None) -> Any:
        """Return the records ``action`` is to run on, browsed in ``self``'s env.

        ``active_ids`` are ids *in the model the caller was looking at*, which
        ``active_model`` names. When that is a different model than the action's,
        those ids mean nothing here -- reading them as our own would act on
        whichever records happen to carry the same ids. The eval context has
        always guarded ``record``/``records`` that way; every runner that dug the
        raw ids out of the context instead did not, and this is what they call so
        that one rule holds for all of them.

        An absent ``active_model`` is trusted: cron jobs, ``run()`` from code and
        the tests pass ``active_ids`` alone, and refusing those would break every
        such caller for a guard that has nothing to compare against.
        """
        action = action or self
        model = self.env[action.sudo().model_name]
        context = self.env.context
        active_model = context.get("active_model")
        if active_model and active_model != model._name:
            return model
        if active_ids := context.get("active_ids"):
            return model.browse(active_ids)
        if active_id := context.get("active_id"):
            return model.browse(active_id)
        if onchange_self := context.get("onchange_self"):
            # the record being edited is not necessarily in the database yet
            return model.browse(onchange_self._origin.id or ())
        return model

    def run(self) -> dict[str, Any] | bool:
        res = False
        for action in self.sudo():
            eval_context = self._get_eval_context(action)
            records = self._get_target_records(action)
            action.sudo(self.env.su)._can_execute_action_on_records(records)
            res = action._run(records, eval_context)
        return res

    def _log_missing_target(self, runner: Any) -> None:
        _logger.warning(
            "Server action %r (type %r) was triggered with no target record "
            "(no active_id/active_ids in context, or they name another model); "
            "its %s runner requires one and will be skipped. Only 'code' "
            "actions run without a target record.",
            self.name,
            self.state,
            runner.__name__,
        )

    def _run(self, records: Any, eval_context: dict[str, Any]) -> dict[str, Any] | bool:
        self.ensure_one()
        if self.warning:
            raise ServerActionWithWarningsError(
                _(
                    "Server action %(action_name)s has one or more warnings, address them first.",
                    action_name=self.name,
                )
            )

        runner, multi = self._get_runner()
        res = False
        if runner and multi:
            if not records and self.state in self._get_states_needing_a_live_record():
                # a `multi` runner takes the whole set and returns quietly on an
                # empty one, so nothing said that a cron -- which passes no
                # `active_ids` at all -- had scheduled an action that can only
                # ever do nothing. The states that mind are the ones that mind
                # about their record being deleted: the same question.
                self._log_missing_target(runner)
            run_self = self.with_context(eval_context["env"].context)
            res = runner(run_self, eval_context=eval_context)
        elif runner:
            if not records:
                if self.env.context.get("onchange_self"):
                    # a record still being composed: run once, on no record
                    return runner(self, eval_context=eval_context) or False
                self._log_missing_target(runner)
            for record in records:
                run_self = self.with_context(active_ids=record.ids, active_id=record.id)
                eval_context["env"] = eval_context["env"](context=run_self.env.context)
                eval_context["records"] = eval_context["record"] = record
                res = runner(run_self, eval_context=eval_context)
        else:
            _logger.warning(
                "Found no way to execute server action %r of type %r, ignoring it. "
                "Verify that the type is correct or add a method called "
                "`_run_action_<type>` or `_run_action_<type>_multi`.",
                self.name,
                self.state,
            )
        return res or False

    def _can_execute_action_on_records(self, records: Any) -> None:
        self.ensure_one()
        config = self.sudo()

        action_groups = config.group_ids
        if action_groups:
            if not (action_groups & self.env.user.sudo().all_group_ids):
                raise AccessError(
                    _("You don't have enough access rights to run this action.")
                )
            return

        model_name = config.model_id.model
        try:
            self.env[model_name].check_access("write")
        except AccessError:
            _logger.warning(
                "Forbidden server action %r executed while the user %s does not have access to %s.",
                config.name,
                self.env.user.login,
                model_name,
            )
            raise

        if records.ids:
            try:
                records.check_access("write")
            except AccessError:
                _logger.warning(
                    "Forbidden server action %r executed while the user %s does not have access to %s.",
                    config.name,
                    self.env.user.login,
                    records,
                )
                raise

    @api.depends("evaluation_type", "update_field_id.ttype")
    def _compute_value_field_to_show(self) -> None:
        for action in self:
            if action.evaluation_type == "sequence":
                action.value_field_to_show = "sequence_id"
            elif action.update_field_id.ttype in (
                "one2many",
                "many2one",
                "many2many",
            ):
                action.value_field_to_show = "resource_ref"
            elif action.update_field_id.ttype == "selection":
                action.value_field_to_show = "selection_value"
            elif action.update_field_id.ttype == "boolean":
                action.value_field_to_show = "update_boolean_value"
            elif action.update_field_id.ttype == "html":
                action.value_field_to_show = "html_value"
            else:
                action.value_field_to_show = "value"

    @api.model
    @tools.ormcache("self.env.lang")
    def _selection_target_model(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (model.model, model.name)
            for model in self.env["ir.model"].sudo().search([])
        )

    @api.onchange("crud_model_id")
    def _set_crud_model_id(self) -> None:
        invalid = self.filtered(
            lambda a: (
                a.state == "object_copy"
                and a.resource_ref
                and a.resource_ref._name != a.crud_model_id.model
            )
        )
        invalid.resource_ref = False
        invalid = self.filtered(
            lambda a: (
                a.link_field_id
                and not (
                    a.link_field_id.model == a.model_id.model
                    and a.link_field_id.relation == a.crud_model_id.model
                )
            )
        )
        invalid.link_field_id = False

    @api.onchange("resource_ref")
    def _set_resource_ref(self) -> None:
        for action in self.filtered(
            lambda action: action.value_field_to_show == "resource_ref"
        ):
            if action.resource_ref:
                action.value = str(action.resource_ref.id)

    @api.onchange("selection_value")
    def _set_selection_value(self) -> None:
        for action in self.filtered(
            lambda action: action.value_field_to_show == "selection_value"
        ):
            if action.selection_value:
                action.value = action.selection_value.value

    def _to_number(self, converter: Any) -> Any:
        self.ensure_one()
        try:
            return converter(self.value)
        except ValueError, TypeError:
            raise UserError(
                _(
                    "The value %(value)r configured on action '%(action)s' is not a "
                    "valid number for field '%(field)s'.",
                    value=self.value,
                    action=self.name,
                    field=self.update_field_id.field_description,
                )
            ) from None

    def _eval_value(self, eval_context: dict[str, Any] | None = None) -> dict[int, Any]:
        result = {}
        for action in self:
            expr = action.value
            if action.evaluation_type == "equation":
                expr = safe_eval(action.value, eval_context)
            elif action.evaluation_type == "sequence":
                expr = action.sequence_id.next_by_id()
            elif action.update_field_id.ttype in ("one2many", "many2many"):
                expr = []
                match action.update_m2m_operation:
                    case "add":
                        with contextlib.suppress(ValueError, TypeError):
                            expr = [Command.link(int(action.value))]
                    case "remove":
                        with contextlib.suppress(ValueError, TypeError):
                            expr = [Command.unlink(int(action.value))]
                    case "set":
                        with contextlib.suppress(ValueError, TypeError):
                            expr = [Command.set([int(action.value)])]
                    case "clear":
                        expr = [Command.clear()]
                    case _:
                        pass
            elif action.update_field_id.ttype == "boolean":
                expr = action.update_boolean_value == "true"
            elif action.update_field_id.ttype in ("many2one", "integer"):
                ttype = action.update_field_id.ttype
                if not action.value:
                    expr = False if ttype == "many2one" else 0
                else:
                    expr = action._to_number(int)
                    if expr == 0 and ttype == "many2one":
                        expr = False
            elif action.update_field_id.ttype == "float":
                expr = 0.0 if not action.value else action._to_number(float)
            elif action.update_field_id.ttype == "html":
                expr = action.html_value
            result[action.id] = expr
        return result

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = default or {}
        vals_list = super().copy_data(default=default)
        if not default.get("name"):
            for vals in vals_list:
                vals["name"] = _("%s (copy)", vals.get("name", ""))
        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    def action_open_parent_action(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "target": "current",
            "views": [[False, "form"]],
            "res_model": self._name,
            "res_id": self.parent_id.id,
        }

    def action_open_scheduled_action(self) -> dict[str, Any]:
        self.ensure_one()
        if not self.ir_cron_ids:
            raise UserError(
                _("No scheduled action is associated with this server action.")
            )
        return {
            "type": "ir.actions.act_window",
            "target": "current",
            "views": [[False, "form"]],
            "res_model": "ir.cron",
            "res_id": self.ir_cron_ids.ids[0],
        }
