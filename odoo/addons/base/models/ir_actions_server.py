import contextlib
import ipaddress
import json
import logging
import socket
from functools import reduce
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
# Use original module path to preserve logger name for tests/monitoring
_server_action_logger = logging.getLogger(
    "odoo.addons.base.models.ir_actions.server_action_safe_eval"
)


def _webhook_url_blocked_reason(url: str) -> str | None:
    """Return a reason string if ``url`` targets a private/reserved address.

    SSRF guard for admin-configured webhook server actions: rejects a URL whose
    host is (or resolves to) a loopback/private/link-local/reserved IP — notably
    the ``169.254.169.254`` cloud-metadata endpoint. Unlike the report fetcher
    (which allows DNS because WeasyPrint re-enters ``fetch()`` on each redirect),
    a webhook is a one-shot POST, so we also resolve the hostname. Returns None
    when the URL is allowed.
    """
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
        # A real hostname: resolve it and screen every returned address.
        try:
            candidates.extend(
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(
                    hostname, parsed.port or None, proto=socket.IPPROTO_TCP
                )
            )
        except OSError, ValueError:
            # Unresolvable host reaches nothing internal; let requests fail.
            return None

    for ip in candidates:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return f"blocked address {ip} (private/reserved range)"
    return None


class LoggerProxy:
    """Restricted logger for the ``safe_eval`` sandbox: only ``log``, ``info``,
    ``warning``, ``error``, ``exception`` are exposed; anything else raises
    ``AttributeError``.
    """

    _ALLOWED = frozenset({"log", "info", "warning", "error", "exception"})

    def __getattr__(self, name: str) -> Any:
        if name in self._ALLOWED:
            return getattr(_server_action_logger, name)
        msg = f"LoggerProxy has no attribute {name!r}"
        raise AttributeError(msg)


# Stateless singleton reused across every eval-context build.
_LOGGER_PROXY = LoggerProxy()


class IrActionsServerHistory(models.Model):
    _name = "ir.actions.server.history"
    _description = "Server Action History"
    _order = "create_date desc, id desc"
    _max_entries_per_action = 100

    action_id = fields.Many2one("ir.actions.server", required=True, ondelete="cascade")
    code = fields.Text()

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

# Server-action ``state`` values that create or update records.
CRUD_STATES = ("object_write", "object_create", "object_copy")


class ServerActionWithWarningsError(UserError):
    """Exception raised when a server action that has warnings is run."""

    pass


class IrActionsServer(models.Model):
    """Server action run on a model, automatically (e.g. automation rules, cron) or manually."""

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
    # Generic
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
    # Inverse relation of ir.cron.ir_actions_server_id (has delegate=True, so either 0 or 1 cron, even if o2m field)
    ir_cron_ids = fields.One2many(
        "ir.cron",
        "ir_actions_server_id",
        "Scheduled Action",
        context={"active_test": False},
    )
    # Python code
    code = fields.Text(
        string="Python Code",
        groups="base.group_system",
        help="Write Python code that the action will execute. Some variables are "
        "available for use; help about python expression is given in the help tab.",
    )
    show_code_history = fields.Boolean(compute="_compute_show_code_history")
    # Multi
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
    # Create
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
    # Webhook
    webhook_url = fields.Char(
        string="Webhook URL", help="URL to send the POST request to."
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

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            if parent_id := vals.get("parent_id"):
                parent = self.browse(parent_id)
                vals["model_id"] = parent.model_id.id
                vals["group_ids"] = parent.group_ids.ids
        actions = super().create(vals_list)

        # create first history entries
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
        """Batch-check whether any code-type action has differing history entries."""
        self.show_code_history = False
        code_actions = self.filtered(lambda a: a.state == "code")
        if not code_actions:
            return

        History = self.env["ir.actions.server.history"]
        all_history = History.search_fetch(
            [("action_id", "in", code_actions.ids)],
            ["action_id", "code"],
        )

        # Compare in Python instead of N search_count calls.
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
        ]

    def _get_warning_messages(self) -> list[str]:
        self.ensure_one()
        warnings = []

        # Single pass over child_ids for model/group/warning checks
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
                # Need the field object (not the ir.model.fields record) for
                # ``.groups``. Use .get(): a stale webhook field (e.g. after a
                # module uninstall) must not turn this compute into a KeyError.
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
        # Pickable models depend only on the user's access rights, not on any
        # field of the record.
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
        """Compute ``crud_model_id`` and ``update_field_id`` for CRUD actions.

        ``crud_model_id`` is the model created/updated: the main model for
        create/copy, or the model of the last field in ``update_path`` for
        writes. ``update_field_id`` is that last field (writes only).
        """
        for action in self:
            # Reset unconditionally; branches below set the other crud fields.
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
        """Return the (model, field) at the end of ``update_path``."""
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
        """Resolve a dotted field path into its list of ``fields.Field`` objects.

        Degrades to ``([], "")`` on an invalid path so stored computes and the
        sample payload can read it without raising (a raising compute could
        abort an unrelated flush). Pass ``raise_on_error=True`` (from
        ``_check_update_path``) to validate user input with a ``ValidationError``.
        """
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
                        # sanity check: this should be the last field in the path
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
                    self.env[action.model_id.model]  # noqa: E8507 — inherent: each action targets a different model
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
        """Validate ``update_path`` at save time.

        Kept here (not in ``_compute_crud_relations``) so a bad path raises a
        clear error on save while stored recomputes degrade gracefully.
        """
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

    def _get_readable_fields(self) -> set[str]:
        return super()._get_readable_fields() | {
            "group_ids",
            "model_name",
        }

    def _get_runner(self) -> tuple[Any, bool]:
        """Return ``(runner, is_multi)`` for ``self.state``, ``(None, False)`` if unknown.

        Two unrelated meanings of "multi": the ``_multi`` suffix means the runner
        handles many records at once (``_run`` skips its per-record loop); the
        ``state == "multi"`` type is matched by ``_run_action_multi``, which has
        no ``_multi`` suffix and so is looped once per record.
        """
        multi = True
        t = self.env.registry[self._name]
        fn = getattr(t, f"_run_action_{self.state}_multi", None)
        if not fn:
            multi = False
            fn = getattr(t, f"_run_action_{self.state}", None)
        return fn, multi

    def create_action(self) -> bool:
        """Create a contextual action for each server action."""
        self.check_access("write")
        for model_id, actions in self.grouped("model_id").items():
            actions.write({"binding_model_id": model_id.id, "binding_type": "action"})
        return True

    def unlink_action(self) -> bool:
        """Remove the contextual actions created for the server actions."""
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
        """Run each child action in ``sequence`` order.

        Returns the last non-falsy child result: a child returning
        ``False``/``None`` does not clear an earlier child's action. Needs an
        active record in context (looped once per ``active_id`` by ``_run``), so
        triggered with none (e.g. from cron) it is skipped.
        """
        res = False
        for act in self.child_ids.sorted():
            res = act.run() or res
        return res

    def _run_action_object_write(
        self, eval_context: dict[str, Any] | None = None
    ) -> None:
        """Apply specified write changes to active_id."""
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
        """Send a post request with a read of the selected field on active_id."""
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
            # SSRF guard: never let a server action POST to an internal/metadata
            # address (e.g. 169.254.169.254, RFC1918, loopback).
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
            # requests' default JSON serializer fails on datetime/date/binary
            # fields, so serialize with json_dumps + str() default instead.
            vals.update(
                record.read(self.webhook_field_ids.mapped("name"), load=None)[0]
            )
        json_values = json_dumps(vals, default=str, option=OPT_SORT_KEYS)
        _logger.info("Webhook call to %s", url)
        _logger.debug("POST JSON data for webhook call: %s", json_values)

        @self.env.cr.postrollback.add
        def _add_post_rollback():
            _logger.warning("Webhook call to %s - cancelled due to a rollback", url)

        @self.env.cr.postcommit.add
        def _add_post_commit():
            _logger.debug("Webhook call to %s - start", url)
            import requests

            try:
                # 'send and forget': short 1s timeout so a slow/broken webhook
                # doesn't block the user, but real error codes still get logged.
                response = requests.post(
                    url,
                    data=json_values,
                    headers={"Content-Type": "application/json"},
                    timeout=1,
                )
                response.raise_for_status()
                _logger.info("Webhook call to %s - succeeded", url)
            except requests.exceptions.ReadTimeout:
                _logger.warning(
                    "Webhook call timed out after 1s - it may or may not have failed. "
                    "If this happens often, it may be a sign that the system you're "
                    "trying to reach is slow or non-functional."
                )
            except requests.exceptions.RequestException as e:
                _logger.warning("Webhook call failed: %s", e)

    def _link_to_active_record(self, new_id: int) -> None:
        """Link a newly created/copied record to the active record via ``link_field_id``."""
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
        """Duplicate the specified model object and optionally link to active record."""
        if not self.resource_ref:
            raise UserError(_("No record selected to duplicate."))
        dupe = self.env[self.crud_model_id.model].browse(self.resource_ref.id).copy()
        self._link_to_active_record(dupe.id)

    def _run_action_object_create(
        self, eval_context: dict[str, Any] | None = None
    ) -> None:
        """Create a new record via ``name_create`` and optionally link to active record."""
        res_id, _res_name = self.env[self.crud_model_id.model].name_create(self.value)
        self._link_to_active_record(res_id)

    def _get_eval_context(self, action: Self) -> dict[str, Any]:
        """Return the ``safe_eval`` context for python formulas and code actions.

        :param action: the server action; required here (unlike the optional
            base signature) since the context derives from ``action.model_id``.
        """

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

    def run(self) -> dict[str, Any] | bool:
        """Run the server action by dispatching to ``_run_action_{TYPE}[_multi]``.

        The ``_multi`` suffix means the runner handles all records at once;
        otherwise it is called once per record.

        The call context should contain:

        active_id
            id of the current record (single mode)
        active_model
            current model, which should equal the action's model
        active_ids (optional)
            ids of the current records (mass mode); takes precedence over
            ``active_id``.

        :return: an ``action_id`` to execute, or ``False`` if none.
        """
        res = False
        for action in self.sudo():
            eval_context = self._get_eval_context(action)
            records = eval_context.get("record") or eval_context["model"]
            records |= eval_context.get("records") or eval_context["model"]
            action._can_execute_action_on_records(records)
            res = action._run(records, eval_context)
        return res

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
            run_self = self.with_context(eval_context["env"].context)
            res = runner(run_self, eval_context=eval_context)
        elif runner:
            active_id = self.env.context.get("active_id")
            if not active_id and self.env.context.get("onchange_self"):
                active_id = self.env.context["onchange_self"]._origin.id
                if (
                    not active_id
                ):  # onchange on new record — run once, no active_ids loop
                    return runner(self, eval_context=eval_context) or False
            active_ids = self.env.context.get(
                "active_ids", [active_id] if active_id else []
            )
            if not active_ids:
                # No target record: a non-``_multi`` runner needs one, so the
                # loop below is a no-op. Almost always a misconfiguration (e.g. a
                # cron pointing at a non-``code`` action); warn instead of
                # failing silently.
                _logger.warning(
                    "Server action %r (type %r) was triggered with no target "
                    "record (no active_id/active_ids in context); its %s runner "
                    "requires one and will be skipped. Only 'code' actions run "
                    "without a target record.",
                    self.name,
                    self.state,
                    runner.__name__,
                )
            for active_id in active_ids:
                run_self = self.with_context(
                    active_ids=[active_id], active_id=active_id
                )
                # Re-wrap the triggering user's env with this record's context.
                # Do NOT use ``run_self.env``: it is ``sudo()``, and
                # expressions/equations must run with the user's own ACLs, never
                # elevated. (Guarded by test_b6_equation_evaluates_without_sudo_privilege.)
                eval_context["env"] = eval_context["env"](context=run_self.env.context)
                eval_context["records"] = eval_context["record"] = records.browse(
                    active_id
                )
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

        # Authorization is EITHER by group OR by record-level ACL, not both:
        # - ``group_ids`` set: group membership is the sole gate; the action runs
        #   ``sudo()``, intentionally letting an authorized user act on records
        #   they could not otherwise write. No ACL check in this branch, by design.
        # - ``group_ids`` empty: the user must hold write access to the model and
        #   the concrete records themselves.
        action_groups = self.group_ids
        if action_groups:
            if not (action_groups & self.env.user.all_group_ids):
                raise AccessError(
                    _("You don't have enough access rights to run this action.")
                )
        else:
            model_name = self.model_id.model
            try:
                self.env[model_name].check_access("write")
            except AccessError:
                _logger.warning(
                    "Forbidden server action %r executed while the user %s does not have access to %s.",
                    self.name,
                    self.env.user.login,
                    model_name,
                )
                raise

        if not self.group_ids and records.ids:
            # check access on real records only; onchange automations run on new records
            try:
                records.check_access("write")
            except AccessError:
                _logger.warning(
                    "Forbidden server action %r executed while the user %s does not have access to %s.",
                    self.name,
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
        """Return all models as a selection sequence.

        Cached (model list only changes on install/update, which clears the
        cache); returns an immutable tuple since the cached value is shared.
        """
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
        """Convert ``self.value`` with ``converter`` (``int``/``float``), raising a
        clean ``UserError`` instead of letting a bad string crash ``write()``.
        """
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
                # Default to a no-op command list so a failed int() conversion
                # or an unknown operation never passes raw text to .write().
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
                        # Unknown/falsy operation: leave the field untouched.
                        pass
            elif action.update_field_id.ttype == "boolean":
                expr = action.update_boolean_value == "true"
            elif action.update_field_id.ttype in ("many2one", "integer"):
                ttype = action.update_field_id.ttype
                if not action.value:
                    # blank -> clear the relation (False) or set 0
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
