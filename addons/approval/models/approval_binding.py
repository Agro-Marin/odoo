import annotationlib
import datetime
import inspect
import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.api import MODULE_UNINSTALL_FLAG
from odoo.exceptions import UserError, ValidationError
from odoo.tools import ormcache

from . import approval_trace as trace

_logger = logging.getLogger(__name__)

AUTOMATION_CLAIMED_METHODS = frozenset(
    {
        "create",
        "write",
        "unlink",
        "_compute_field_value",
        "_onchange_methods__",
        "message_post",
    }
)

ORM_LIFECYCLE_ACTIONS = frozenset(
    {"action_archive", "action_unarchive", "toggle_active"}
)

ORIGIN_ATTR = "approval_binding_origin"
ENABLED_PARAM = "approval.binding_enabled"
REPLAY_ADMISSION = "approval.replay"
INVOKE_ADMISSION = "approval.invoking"
BINDING_FOR_ADMISSION = "approval.binding_for:"
ENFORCEABLE_ACTION_TYPES = frozenset({"ir.actions.server", "ir.actions.report"})


class ApprovalBinding(models.Model):
    _name = "approval.binding"
    _inherit = ["mixin.approval.domain"]
    _description = "Approval Binding"
    _order = "model_name, method, sequence, id"

    name = fields.Char(
        compute="_compute_name",
        store=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    model_id = fields.Many2one(
        comodel_name="ir.model",
        index=True,
        required=True,
        ondelete="cascade",
    )
    model_name = fields.Char(
        related="model_id.model",
        string="Model Name",
    )
    method = fields.Char(
        help="Method to gate. It is wrapped at registry load, so the gate "
        "holds for every caller, not only the user interface. A binding gates "
        "one thing: a verb, a method or an action."
    )
    verb = fields.Char(
        index="btree_not_null",
        help="A verb the model declares (post, confirm, validate...). It needs no "
        "wrapper of its own: every door, checkpoint and state move of the verb "
        "asks the binding.",
    )
    origin = fields.Selection(
        selection=[("module", "Shipped by a module"), ("manual", "Configured")],
        default="manual",
        readonly=True,
        required=True,
        help="Shipped by a module: the module's own obligation, of which only the "
        "mode and the sudo policy are an operator's decision.",
    )
    action_id = fields.Many2one(
        comodel_name="ir.actions.actions",
        index="btree_not_null",
        ondelete="cascade",
        help="Action to gate, instead of a method. A server action or a report is "
        "refused on the server; a window or client action only opens a view, so a "
        "binding on one is honoured by the client's check alone.",
    )
    is_enforced = fields.Boolean(
        compute="_compute_is_enforced",
        help="Whether the server itself refuses the operation. False for a window "
        "or client action: opening a view is nothing the server can intercept, so "
        "only the client's check stands in the way.",
    )
    category_id = fields.Many2one(
        comodel_name="approval.category",
        ondelete="cascade",
        help="Approval configuration consulted for this operation. Required "
        "for every mode but 'Observe'.",
    )
    subject_domain = fields.Char(
        string="Applies When",
        help="Domain on the gated model. Empty means every record.",
    )
    mode = fields.Selection(
        selection=[
            ("advise", "Observe"),
            ("block", "Block"),
            ("request", "Request"),
            ("act_decides", "The Move Decides"),
        ],
        default="advise",
        required=True,
        help="""What the binding does when it applies:

        • Observe: the operation runs. Every call is recorded, including
          whether the caller was elevated. This is how a gate is sized before
          it is switched on -- turning a gate straight to Block surfaces the
          flows that were quietly relying on not being gated, in production.
        • Block: the operation is refused unless an approved request covers
          the record. A document implementing mixin.approval asks through its
          own button; any other record is covered by an approved request that
          points at it in this binding's category.
        • Request: the call raises an approval instead of running. With Run On
          Approval, the operation then runs once the request is approved --
          exactly once, and as the person who called it; without it, approval
          only clears the gate for the next call.
        • The Move Decides: a document whose state is its approval (time off,
          an allocation, an expense) ships it on each verb of its state: the
          person who moves the state has decided the request, which follows.
          Nothing is refused or asked by it; it is not an operator's switch.""",
    )
    sudo_policy = fields.Selection(
        selection=[
            ("enforce", "Applies to everyone"),
            ("superuser", "Superuser passes"),
            ("bypass", "Any elevated caller passes"),
        ],
        default="superuser",
        required=True,
        help="""Who the gate does NOT apply to.

        `sudo()` flips `su` and keeps `uid`, so "elevated" covers both the
        real superuser and an ordinary user who called through `sudo()`. Those
        are different risks and this is deliberately not one switch:

        • Applies to everyone: nothing passes. Correct for a gate that must
          hold against internal callers too.
        • Superuser passes: the default. Internal machinery keeps working, an
          ordinary user cannot self-elevate past the gate.
        • Any elevated caller passes: what `web_studio` does unconditionally.
          Every bypass is still recorded, which is the part it does not do.

        A module's own data and demo files pass under every policy, recorded
        the same way: they are reviewed with the code, not decided by a user.""",
    )

    approve_on_invoke = fields.Boolean(
        help="Request mode only. When somebody who may approve a pending step of "
        "this record calls the operation, the call records their approval -- the "
        "way a Studio approval button works -- and the operation runs if nothing "
        "is left to approve. Otherwise the remaining approvers are asked and the "
        "call waits."
    )
    run_on_approval = fields.Boolean(
        default=True,
        help="Request mode only. Run the operation, once and as the person who "
        "asked, when the request is approved. Off, approval only clears the gate "
        "and the operation runs when it is next called, which is how Studio "
        "approvals behave.",
    )
    observation_ids = fields.One2many(
        comodel_name="approval.observation",
        inverse_name="binding_id",
    )
    observation_count = fields.Count(
        count_of="observation_ids",
        string="Observations",
    )
    elevated_count = fields.Integer(compute="_compute_elevation_counts")
    self_elevated_count = fields.Integer(compute="_compute_elevation_counts")

    _model_method_domain_uniq = models.Constraint(
        "unique nulls not distinct (model_id, method, action_id, verb, subject_domain)",
        "A binding already covers that model, operation and condition.",
    )

    @api.depends("model_id", "method", "verb", "action_id", "mode")
    def _compute_name(self) -> None:
        for binding in self:
            target = binding._get_operation_label()
            binding.name = f"{binding.model_name or '?'}.{target} ({binding.mode})"

    @api.depends("method", "verb", "action_id", "action_id.type")
    def _compute_is_enforced(self) -> None:
        for binding in self:
            binding.is_enforced = bool(binding.method or binding.verb) or (
                binding.action_id.type in ENFORCEABLE_ACTION_TYPES
            )

    def _get_operation_label(self) -> str:
        self.check_singleton()
        return self.verb or self.method or self.action_id.name or "?"

    def _get_method_name(self) -> str | None:
        """The method a replay calls: the bound method, or the verb's first door."""
        self.check_singleton()
        if self.method or not self.verb:
            return self.method or None
        verb = self.env.registry.model_verbs.get(self.model_id.model, {}).get(self.verb)
        return verb.methods[0] if verb and verb.methods else None

    def _is_document_obligation(self) -> bool:
        """A verb binding with no category: the document asks its own approval."""
        self.check_singleton()
        model = self.env.get(self.model_id.model)
        return bool(
            self.verb
            and not self.category_id
            and model is not None
            and isinstance(model, self.env.registry["mixin.approval.gate"])
        )

    def _compute_elevation_counts(self) -> None:
        grouped = self.env["approval.observation"]._read_group(
            [("binding_id", "in", self.ids)],
            ["binding_id", "elevation"],
            ["__count"],
        )
        elevated = dict.fromkeys(self.ids, 0)
        self_elevated = dict.fromkeys(self.ids, 0)
        for binding, elevation, count in grouped:
            if elevation == "none":
                continue
            elevated[binding.id] = elevated.get(binding.id, 0) + count
            if elevation == "self_elevated":
                self_elevated[binding.id] = count
        for binding in self:
            binding.elevated_count = elevated.get(binding.id, 0)
            binding.self_elevated_count = self_elevated.get(binding.id, 0)
            trace.BINDING.event(
                "elevation_counts",
                binding=binding.id,
                elevated=binding.elevated_count,
                self_elevated=binding.self_elevated_count,
            )

    def _domain_source_field(self) -> str:
        return "subject_domain"

    # -- configuration-time validation ------------------------------------

    @api.constrains(
        "model_id",
        "method",
        "verb",
        "mode",
        "subject_domain",
        "category_id",
        "approve_on_invoke",
        "run_on_approval",
        "action_id",
    )
    def _check_binding(self) -> None:
        for binding in self:
            model = self.env.get(binding.model_id.model)
            if model is None:
                trace.REFUSAL.event(
                    "binding_model_not_in_registry",
                    binding=binding.id,
                    model=binding.model_id.model,
                )
                raise ValidationError(
                    self.env._(
                        "%(model)s is not in the registry.",
                        model=binding.model_id.model,
                    ),
                )
            if bool(binding.method) + bool(binding.action_id) + bool(binding.verb) != 1:
                trace.REFUSAL.event(
                    "binding_gates_none_or_both",
                    binding=binding.id,
                    method=binding.method or None,
                    verb=binding.verb or None,
                    action=binding.action_id.id or None,
                )
                raise ValidationError(
                    self.env._(
                        "%(name)s must gate exactly one thing: a verb, a method or "
                        "an action.",
                        name=binding.name,
                    ),
                )
            if binding.mode == "act_decides":
                binding._check_move_decides(model)
            if binding.verb:
                binding._check_verb_declared(model)
            elif binding.method:
                binding._check_method_available(model)
            else:
                binding._check_action_available()
            if binding.subject_domain and binding._is_document_obligation():
                trace.REFUSAL.event(
                    "document_obligation_with_condition", binding=binding.id
                )
                raise ValidationError(
                    self.env._(
                        "%(name)s holds %(model)s's own approval, which its approval "
                        "categories scope: it takes no condition of its own.",
                        name=binding.name,
                        model=model._name,
                    ),
                )
            if binding.subject_domain:
                binding._check_domain_against_model(model)
            if (
                binding.mode not in ("advise", "act_decides")
                and not binding.category_id
                and not binding._is_document_obligation()
            ):
                trace.REFUSAL.event(
                    "binding_without_category", binding=binding.id, mode=binding.mode
                )
                raise ValidationError(
                    self.env._(
                        "%(name)s is in %(mode)s mode, so it needs an approval "
                        "category to consult.",
                        name=binding.name,
                        mode=binding.mode,
                    ),
                )
            if binding.approve_on_invoke and binding.mode != "request":
                trace.REFUSAL.event(
                    "approve_on_invoke_needs_request",
                    binding=binding.id,
                    mode=binding.mode,
                )
                raise ValidationError(
                    self.env._(
                        "%(name)s approves on invoke, which needs Request mode: "
                        "Block mode raises no request for the caller to approve.",
                        name=binding.name,
                    ),
                )
            if (
                binding.mode == "request"
                and binding.run_on_approval
                and not binding._is_document_obligation()
            ):
                if binding.method or binding.verb:
                    binding._check_method_replayable(model)
                elif binding.action_id.type != "ir.actions.server":
                    trace.REFUSAL.event(
                        "only_a_server_action_replays",
                        binding=binding.id,
                        action=binding.action_id.id,
                        type=binding.action_id.type,
                    )
                    raise ValidationError(
                        self.env._(
                            "%(name)s would run its action again once approved, "
                            "but only a server action can be run again. Turn Run "
                            "On Approval off for this one.",
                            name=binding.name,
                        ),
                    )

    def _check_action_available(self) -> None:
        self.check_singleton()
        action_type = self.action_id.type
        if action_type == "ir.actions.server":
            action_model = (
                self.env["ir.actions.server"].sudo().browse(self.action_id.id).model_id
            )
            if action_model != self.model_id:
                trace.REFUSAL.event(
                    "action_runs_on_another_model",
                    binding=self.id,
                    action=self.action_id.id,
                    action_model=action_model.model,
                    model=self.model_id.model,
                )
                raise ValidationError(
                    self.env._(
                        "%(action)s runs on %(action_model)s, not on %(model)s.",
                        action=self.action_id.name,
                        action_model=action_model.model,
                        model=self.model_id.model,
                    ),
                )
        elif action_type == "ir.actions.report":
            report_model = (
                self.env["ir.actions.report"].sudo().browse(self.action_id.id).model
            )
            if report_model != self.model_id.model:
                trace.REFUSAL.event(
                    "report_prints_another_model",
                    binding=self.id,
                    action=self.action_id.id,
                    report_model=report_model,
                    model=self.model_id.model,
                )
                raise ValidationError(
                    self.env._(
                        "%(action)s prints %(report_model)s, not %(model)s.",
                        action=self.action_id.name,
                        report_model=report_model,
                        model=self.model_id.model,
                    ),
                )
            if self.mode == "request":
                trace.REFUSAL.event(
                    "report_cannot_wait", binding=self.id, action=self.action_id.id
                )
                raise ValidationError(
                    self.env._(
                        "%(action)s is a report, and a report cannot wait for an "
                        "approval: refusing to render rolls back the request that "
                        "would have asked for one. Use Block, and let the client "
                        "raise the request before printing.",
                        action=self.action_id.name,
                    ),
                )

    def _check_move_decides(self, model) -> None:
        """A move decides only on a document whose state is its approval, and only
        through a verb that is that state's move."""
        self.check_singleton()
        verb = self.env.registry.model_verbs.get(model._name, {}).get(self.verb or "")
        synced = isinstance(model, self.env.registry["mixin.approval.state.sync"])
        if not (
            synced
            and verb is not None
            and verb.transition is not None
            and verb.transition[0] == model._get_approval_sync_state_field()
            and not self.category_id
            and not self.subject_domain
        ):
            trace.REFUSAL.event(
                "move_decides_elsewhere",
                binding=self.id,
                model=model._name,
                verb=self.verb or None,
            )
            raise ValidationError(
                self.env._(
                    "%(name)s: a move decides only a document whose state is its "
                    "approval, through a verb that moves that state, with no "
                    "category or condition of its own.",
                    name=self.name,
                ),
            )

    def _check_verb_declared(self, model) -> None:
        self.check_singleton()
        verb = self.env.registry.model_verbs.get(model._name, {}).get(self.verb)
        if verb is None:
            trace.REFUSAL.event(
                "verb_not_declared", binding=self.id, model=model._name, verb=self.verb
            )
            raise ValidationError(
                self.env._(
                    "%(model)s declares no verb %(verb)s.",
                    model=model._name,
                    verb=self.verb,
                ),
            )
        if not verb.methods and self.mode == "request":
            trace.REFUSAL.event(
                "verb_without_door_in_request_mode", binding=self.id, verb=self.verb
            )
            raise ValidationError(
                self.env._(
                    "%(verb)s has no door on %(model)s, so nothing can wait for its "
                    "approval: use Block.",
                    model=model._name,
                    verb=self.verb,
                ),
            )

    def _check_method_available(self, model) -> None:
        self.check_singleton()
        if self.method in AUTOMATION_CLAIMED_METHODS:
            trace.REFUSAL.event(
                "method_claimed_by_automation", binding=self.id, method=self.method
            )
            raise ValidationError(
                self.env._(
                    "%(method)s cannot be gated. `automation` removes that "
                    "method from every model in the registry when it "
                    "re-registers its own hooks, without checking who "
                    "installed it, so the gate would disappear silently "
                    "rather than fail.",
                    method=self.method,
                ),
            )
        if refusal := self._get_method_refusal(self.method):
            trace.REFUSAL.event(
                "method_is_orm_api", binding=self.id, method=self.method
            )
            raise ValidationError(refusal)
        if self.model_id.model == self._name:
            trace.REFUSAL.event("binding_gates_itself", binding=self.id)
            raise ValidationError(
                self.env._("A binding cannot gate the binding machinery."),
            )
        for verb_name, verb in self.env.registry.model_verbs.get(
            model._name, {}
        ).items():
            if self.method in (*verb.methods, *verb.checkpoints):
                trace.REFUSAL.event(
                    "method_is_a_verb_door",
                    binding=self.id,
                    method=self.method,
                    verb=verb_name,
                )
                raise ValidationError(
                    self.env._(
                        "%(method)s is how %(model)s does %(verb)s: bind the verb, "
                        "which every door, checkpoint and state move of it asks.",
                        method=self.method,
                        model=model._name,
                        verb=verb_name,
                    ),
                )
        function = getattr(model, self.method, None)
        if function is None or not callable(function):
            trace.REFUSAL.event(
                "method_does_not_exist",
                binding=self.id,
                model=model._name,
                method=self.method,
            )
            raise ValidationError(
                self.env._(
                    "%(model)s has no method %(method)s.",
                    model=model._name,
                    method=self.method,
                ),
            )

    @api.model
    def _get_method_refusal(self, method: str) -> str | None:
        if method not in ORM_LIFECYCLE_ACTIONS and hasattr(models.BaseModel, method):
            return self.env._(
                "%(method)s is the ORM's own API, not an operation. Every caller of "
                "the model goes through it, the gate included, so wrapping it "
                "recurses or breaks the model. Gate the method that performs the "
                "business operation instead.",
                method=method,
            )
        return None

    @api.constrains("model_id", "method")
    def _check_private_method_from_module_data(self) -> None:
        if self.env.context.get("install_module"):
            return
        for binding in self:
            if binding.method and binding.method.startswith("_"):
                trace.REFUSAL.event(
                    "private_method_outside_module_data",
                    binding=binding.id,
                    method=binding.method,
                )
                raise ValidationError(
                    self.env._(
                        "%(method)s is private. A binding on a private method is "
                        "accepted only from a module's data, where it is reviewed "
                        "with the code that calls the method.",
                        method=binding.method,
                    ),
                )

    def _check_method_replayable(self, model) -> None:
        self.check_singleton()
        method = self._get_method_name()
        function = getattr(model, method)
        signature = inspect.signature(
            function, annotation_format=annotationlib.Format.FORWARDREF
        )
        required = [
            parameter
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.default is inspect.Parameter.empty
            and parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        ]
        if required:
            trace.REFUSAL.event(
                "method_takes_arguments",
                binding=self.id,
                method=self.method,
                args=[parameter.name for parameter in required],
            )
            raise ValidationError(
                self.env._(
                    "%(method)s takes %(args)s, so it cannot be replayed after "
                    "approval. Request mode only gates methods that take no "
                    "argument; use Block mode for this one.",
                    method=method,
                    args=", ".join(p.name for p in required),
                ),
            )

    @api.model
    def _enabled(self) -> bool:
        return self.env["ir.config_parameter"].sudo().get_param(
            ENABLED_PARAM, "True"
        ).strip().lower() not in ("false", "0", "no")

    @api.model
    def _elevation(self) -> str:
        if not self.env.su:
            return "none"
        return "superuser" if self.env.uid == SUPERUSER_ID else "self_elevated"

    def _passes_on_elevation(self, elevation: str) -> bool:
        self.check_singleton()
        if self.env.context.get("install_module"):
            passes, rule = True, "module_data"
        elif elevation == "none":
            passes, rule = False, "not_elevated"
        elif self.sudo_policy == "enforce":
            passes, rule = False, "enforced"
        elif self.sudo_policy == "bypass":
            passes, rule = True, "bypass"
        else:
            passes, rule = elevation == "superuser", "superuser_only"
        trace.BINDING.event(
            "elevation",
            binding=self.id,
            elevation=elevation,
            policy=self.sudo_policy,
            rule=rule,
            passes=passes,
        )
        return passes

    def _has_anyone_to_ask(self) -> bool:
        self.check_singleton()
        category = self.category_id.sudo()
        anyone = bool(category.step_ids or category.rule_ids)
        if not anyone:
            trace.DEGRADED.event(
                "binding_has_nobody_to_ask",
                binding=self.id,
                category=category.id,
                mode=self.mode,
            )
        return anyone

    def _get_selected(self, records):
        self.check_singleton()
        if self.mode != "advise" and not self._has_anyone_to_ask():
            return records.browse()
        if self.subject_domain:
            domain = self._parse_domain_or_warn()
            if domain is None:
                return records.browse()
            records = records.filtered_domain(domain)
        steps = self.category_id.sudo().step_ids if self.mode != "advise" else ()
        if not steps:
            trace.BINDING.event("selected", binding=self.id, records=records)
            return records
        selected = records.filtered(
            lambda record: any(
                step._is_applicable_to_document(record) for step in steps
            )
        )
        trace.BINDING.event(
            "selected",
            binding=self.id,
            asked=records,
            records=selected.ids,
            steps=steps.ids,
        )
        return selected

    def _get_covered_ids(self, records) -> set[int]:
        self.check_singleton()
        if not records:
            return set()
        if "approval_request_id" in records._fields:
            return {
                record.id
                for record in records.sudo()
                if record.approval_request_id.state == "approved"
                and (
                    not self.category_id
                    or record.approval_request_id.category_id == self.category_id
                )
            }
        domain = [
            ("res_model", "=", records._name),
            ("res_id", "in", records.ids),
            ("state", "=", "approved"),
        ]
        if self.category_id:
            domain.append(("category_id", "=", self.category_id.id))
        by_id = {record.id: record for record in records}
        covered = set()
        for request in self.env["approval.request"].sudo().search(domain):
            record = by_id.get(request.res_id)
            if record is None or record.id in covered:
                continue
            if (
                request.binding_id == self
                and request.binding_snapshot
                and request.binding_snapshot != self._get_snapshot(record)
            ):
                continue
            covered.add(record.id)
        return covered

    def _get_snapshot(self, record) -> dict:
        self.check_singleton()
        if not self.subject_domain:
            return {}
        domain = self._parse_domain()
        if domain is None:
            _logger.warning(
                "Approval binding %s: subject_domain %r does not parse, so the "
                "snapshot taken for %s#%s is empty and no later change to it can "
                "move this approval's coverage.",
                self.id,
                self.subject_domain,
                record._name,
                record.id,
            )
            return {}
        probe = record.sudo()
        return {
            path: self._get_snapshot_value(probe.mapped(path))
            for path in sorted(self._domain_field_paths(domain))
        }

    @api.model
    def _get_snapshot_value(self, value):
        if isinstance(value, models.BaseModel):
            return sorted(value.ids)
        if isinstance(value, (list, tuple)):
            return [self._get_snapshot_value(item) for item in value]
        if isinstance(value, datetime.date):
            return value.isoformat()
        return value

    def _get_observation_vals(self, record, elevation: str, would_block: bool) -> dict:
        self.check_singleton()
        return {
            "binding_id": self.id,
            "model_name": record._name,
            "operation": self._get_operation_label(),
            "res_id": record.id,
            "user_id": self.env.uid,
            "elevation": elevation,
            "would_block": would_block,
        }

    def _enforce(self, record, elevation: str, observations: list, covered_ids) -> bool:
        self.check_singleton()
        covered = record.id in covered_ids

        if self.mode == "advise" or self._passes_on_elevation(elevation):
            trace.BINDING.event(
                "observed",
                binding=self.id,
                record=record.id,
                mode=self.mode,
                elevation=elevation,
                would_block=not covered,
            )
            observations.append(
                self._get_observation_vals(record, elevation, not covered)
            )
            return False

        if covered:
            trace.BINDING.event(
                "covered", binding=self.id, record=record.id, mode=self.mode
            )
            return False

        if self.mode == "block":
            trace.REFUSAL.event(
                "blocked",
                binding=self.id,
                record=record.id,
                method=self.method,
                elevation=elevation,
            )
            raise UserError(
                self.env._(
                    "%(record)s needs an approval before %(method)s can run.\n\n"
                    "Ask for approval on the document first.",
                    record=record.display_name,
                    method=self._get_operation_label(),
                ),
            )
        trace.BINDING.note(
            "wants_request",
            binding=self.id,
            record=record.id,
            method=self.method,
            elevation=elevation,
        )
        return True

    def _raise_requests_for(self, records):
        self.check_singleton()
        Request = self.env["approval.request"]
        requests = Request
        if "approval_request_id" in records._fields:
            for record in records:
                request = record.sudo().approval_request_id
                if request.state == "refused":
                    requests |= request
                    continue
                if request.state not in ("new", "pending"):
                    with self.env.transaction.admitting(
                        record._name, f"{BINDING_FOR_ADMISSION}{self.id}", record.ids
                    ):
                        record.action_create_approval_request()
                    request = record.sudo().approval_request_id
                elif request.state == "new":
                    request.action_confirm()
                requests |= request
            return requests

        latest_by_res_id = {}
        for request in Request.search(
            [
                ("binding_id", "=", self.id),
                ("res_model", "=", records._name),
                ("res_id", "in", records.ids),
            ],
            order="id desc",
        ):
            latest_by_res_id.setdefault(request.res_id, request)
        for record in records:
            request = latest_by_res_id.get(record.id)
            if request and request.state == "refused":
                requests |= request
                continue
            if not request or request.state not in ("new", "pending"):
                request = Request.create(
                    {
                        "name": record.display_name,
                        "category_id": self.category_id.id,
                        "request_owner_id": self.env.uid,
                        "res_model": record._name,
                        "res_id": record.id,
                        "binding_id": self.id,
                        "binding_snapshot": self._get_snapshot(record),
                    }
                )
                request.action_confirm()
            elif request.state == "new":
                request.write({"binding_snapshot": self._get_snapshot(record)})
                request.action_confirm()
            requests |= request
        trace.BINDING.note(
            "requests_raised",
            binding=self.id,
            records=records,
            requests=requests.ids,
        )
        return requests

    def _approve_on_invoke(self, requests) -> None:
        self.check_singleton()
        user = self.env.user
        for request in requests.filtered(lambda r: r.state == "pending"):
            approver = request._get_rows_decidable_by(user)
            if not approver:
                trace.BINDING.event(
                    "invoke_not_decidable",
                    binding=self.id,
                    request=request.id,
                    uid=user.id,
                )
                continue
            try:
                with (
                    self.env.cr.savepoint(),
                    self.env.transaction.admitting(
                        request._name, INVOKE_ADMISSION, request.ids
                    ),
                ):
                    request.with_user(user).action_approve(approver)
            except UserError as exc:
                _logger.info(
                    "Approval binding %s: %s could not approve request %s on "
                    "invoke: %s",
                    self.id,
                    user.login,
                    request.id,
                    exc,
                )

    def _mark_invoked_run(self, records) -> None:
        self.check_singleton()
        if not records:
            return
        if "approval_request_id" in records._fields:
            requests = records.sudo().approval_request_id
        else:
            requests = (
                self.env["approval.request"]
                .sudo()
                .search(
                    [
                        ("binding_id", "=", self.id),
                        ("res_model", "=", records._name),
                        ("res_id", "in", records.ids),
                    ],
                )
            )
        consumed = requests.filtered(
            lambda r: (
                r.binding_id == self
                and r.state == "approved"
                and not r.date_binding_replayed
            ),
        )
        trace.BINDING.note(
            "invoke_consumed",
            binding=self.id,
            records=records,
            requests=consumed.ids,
            already_stamped=len(requests) - len(consumed),
        )
        consumed.write({"date_binding_replayed": fields.Datetime.now()})

    def _get_requests_action(self, requests):
        if not requests:
            return False
        action = {
            "type": "ir.actions.act_window",
            "res_model": "approval.request",
            "name": self.env._("Approval Required"),
        }
        if len(requests) == 1:
            action.update(view_mode="form", res_id=requests.id)
        else:
            action.update(view_mode="list,form", domain=[("id", "in", requests.ids)])
        return action

    def _replay(self, request) -> None:
        self.check_singleton()
        owner = request.request_owner_id
        record = self.env[request.res_model].browse(request.res_id).with_user(owner)
        if owner.id == SUPERUSER_ID:
            record = record.sudo()
        error = False
        try:
            with self.env.cr.savepoint():
                probe = record.sudo()
                if not probe.exists():
                    trace.REFUSAL.event(
                        "replay_record_gone",
                        binding=self.id,
                        model=request.res_model,
                        res_id=request.res_id,
                    )
                    raise UserError(self.env._("The record no longer exists."))
                if self._get_selected(probe) and probe.id not in self._get_covered_ids(
                    probe
                ):
                    trace.REFUSAL.event(
                        "replay_snapshot_moved",
                        binding=self.id,
                        request=request.id,
                        record=probe,
                    )
                    raise UserError(
                        self.env._(
                            "What was approved is no longer what is there: a "
                            "value this gate reads changed after the request was "
                            "raised. Ask for approval again."
                        )
                    )
                with self.env.transaction.admitting(
                    "approval.binding", REPLAY_ADMISSION, self.ids
                ):
                    if self.action_id:
                        self._run_action_on(record)
                    else:
                        getattr(record, self._get_method_name())()
        except UserError as exc:
            error = str(exc) or type(exc).__name__
            trace.BINDING.note(
                "replay_failed",
                binding=self.id,
                request=request.id,
                method=self._get_operation_label(),
                error=type(exc).__name__,
            )
            _logger.info(
                "Approval binding %s: request %s approved, operation %s not run: %s",
                self.id,
                request.id,
                self._get_operation_label(),
                error,
            )

        if error:
            request.sudo().write({"binding_replay_error": error})
            body = self.env._(
                "The gated operation %(method)s did not run: %(error)s",
                method=self._get_operation_label(),
                error=error,
            )
        else:
            request.sudo().write(
                {
                    "date_binding_replayed": fields.Datetime.now(),
                    "binding_replay_error": False,
                }
            )
            trace.BINDING.note(
                "replay_ran",
                binding=self.id,
                request=request.id,
                method=self._get_operation_label(),
                owner=owner.id,
            )
            body = self.env._(
                "The gated operation %(method)s ran as %(user)s.",
                method=self._get_operation_label(),
                user=owner.display_name,
            )
        request.sudo().message_post(body=body, message_type="notification")

    @api.model
    def _bindings_for(self, model_name: str, method: str):
        return self.sudo().browse(self._get_binding_ids(model_name, method))

    @api.model
    @ormcache("model_name", "method")
    def _get_binding_ids(self, model_name: str, method: str) -> tuple[int, ...]:
        return tuple(
            self.sudo()
            .with_context(active_test=True)
            .search([("model_name", "=", model_name), ("method", "=", method)])
            .ids
        )

    @api.model
    def _bindings_for_verb(self, model_name: str, verb: str):
        return self.sudo().browse(self._get_verb_binding_ids(model_name, verb))

    @api.model
    @ormcache("model_name", "verb")
    def _get_verb_binding_ids(self, model_name: str, verb: str) -> tuple[int, ...]:
        return tuple(
            self.sudo()
            .with_context(active_test=True)
            .search([("model_name", "=", model_name), ("verb", "=", verb)])
            .ids
        )

    @api.model
    def _bindings_for_action(self, action_id: int):
        return self.sudo().browse(self._get_action_binding_ids(action_id))

    @api.model
    @ormcache("action_id")
    def _get_action_binding_ids(self, action_id: int) -> tuple[int, ...]:
        """The bindings on one action, cached like the method lookup and for the same reason."""
        return tuple(
            self.sudo()
            .with_context(active_test=True)
            .search([("action_id", "=", action_id)])
            .ids
        )

    def _run_action_on(self, records):
        """Run this binding's server action on `records`, in their environment."""
        self.check_singleton()
        action = records.env["ir.actions.server"].browse(self.action_id.id)
        trace.BINDING.note(
            "run_action", binding=self.id, action=action.id, records=records
        )
        return action.with_context(
            active_model=records._name,
            active_ids=records.ids,
            active_id=records[:1].id,
        ).run()

    # -- keeping the registry in step with the configuration ---------------

    @api.model_create_multi
    def create(self, vals_list):
        bindings = super().create(vals_list)
        bindings._apply_to_registry()
        return bindings

    def write(self, vals):
        self._check_move_decides_kept(vals)
        if {"model_id", "method", "verb", "action_id"} & vals.keys():
            self._check_target_unchanged_once_requested(vals)
        result = super().write(vals)
        self._apply_to_registry()
        return result

    def _check_target_unchanged_once_requested(self, vals) -> None:
        requested = (
            self.env["approval.request"]
            .sudo()
            .search([("binding_id", "in", self.ids)])
            .binding_id
        )
        for binding in requested:
            current = {
                "model_id": binding.model_id.id,
                "method": binding.method or False,
                "verb": binding.verb or False,
                "action_id": binding.action_id.id or False,
            }
            if any(
                field in vals and (vals[field] or False) != value
                for field, value in current.items()
            ):
                trace.REFUSAL.event(
                    "binding_target_frozen",
                    binding=binding.id,
                    fields=sorted(set(vals) & set(current)),
                )
                raise UserError(
                    self.env._(
                        "%(binding)s already has approval requests, so what it gates "
                        "cannot change. Archive it and bind the new target instead.",
                        binding=binding.name,
                    ),
                )

    def _check_move_decides_kept(self, vals=None) -> None:
        """A shipped move-decides obligation is the document's own approval flow:
        switching it off would leave requests nobody's move ever decides."""
        if self.env.context.get(MODULE_UNINSTALL_FLAG):
            return
        frozen = ("mode", "active", "verb", "model_id")
        for binding in self.filtered(lambda binding: binding.mode == "act_decides"):
            if vals is not None and not any(
                field in vals
                and vals[field]
                != binding._fields[field].convert_to_write(binding[field], binding)
                for field in frozen
            ):
                continue
            trace.REFUSAL.event("move_decides_switched_off", binding=binding.id)
            raise UserError(
                self.env._(
                    "%(binding)s is how %(model)s's state decides its approval "
                    "request; it cannot be switched off, retargeted or deleted.",
                    binding=binding.name,
                    model=binding.model_id.name,
                ),
            )

    def unlink(self):
        self._check_move_decides_kept()
        result = super().unlink()
        self.env.registry.clear_cache()
        return result

    def _get_requests_holding_decisions(self, records):
        """The requests a reset clears: approved ones, and waiting ones already decided in part."""
        self.check_singleton()
        waiting = (
            self.env["approval.request"]
            .sudo()
            .search(
                [
                    ("binding_id", "=", self.id),
                    ("res_model", "=", records._name),
                    ("res_id", "in", records.ids),
                    ("state", "=", "pending"),
                ]
            )
            .filtered(
                lambda request: request.approver_ids.filtered(
                    lambda approver: approver.decided_by_user_id
                )
            )
        )
        covering = self._get_covering_requests(records)
        trace.BINDING.event(
            "requests_holding_decisions",
            binding=self.id,
            records=records,
            covering=covering.ids,
            waiting_with_decisions=waiting.ids,
        )
        return covering | waiting

    def _get_covering_requests(self, records):
        """Every approved request that could be covering these records."""
        self.check_singleton()
        Request = self.env["approval.request"].sudo()
        if "approval_request_id" in records._fields:
            requests = records.sudo().approval_request_id
        else:
            requests = Request.search(
                [
                    ("res_model", "=", records._name),
                    ("res_id", "in", records.ids),
                    ("state", "=", "approved"),
                ]
            )
        return requests.filtered(
            lambda r: (
                r.state == "approved"
                and (not self.category_id or r.category_id == self.category_id)
            )
        )

    def _reset_coverage(self, records) -> None:
        """Reset to draft the approvals that covered these records.

        Through `action_reset_to_draft`, the framework's own lifecycle, so an
        adopter is told through `_on_approval_reset` and the decisions stay in the
        request's chatter. The one-shot stamp is cleared, so a binding that runs on
        approval runs again in the next cycle.
        """
        self.check_singleton()
        holding = self._get_requests_holding_decisions(records)
        trace.BINDING.note(
            "reset_coverage",
            binding=self.id,
            records=records,
            requests=holding.ids,
        )
        for request in holding:
            try:
                with self.env.cr.savepoint():
                    if request.state == "approved":
                        request.action_reset_to_draft()
                    else:
                        request._lock_and_reload(with_approvers=True)
                        if request.state != "pending":
                            continue
                        request._force_draft()
                    request.write(
                        {"date_binding_replayed": False, "binding_replay_error": False}
                    )
            except UserError as exc:
                _logger.info(
                    "Approval binding %s: request %s was not reset: %s",
                    self.id,
                    request.id,
                    exc,
                )
                continue
            request.message_post(
                body=self.env._(
                    "%(record)s came to match the reset condition of %(binding)s, so "
                    "this approval no longer covers it and was reset to draft.",
                    record=request.res_name or request.display_name,
                    binding=self.name,
                ),
                message_type="notification",
            )

    def _apply_to_registry(self) -> None:
        self.env.registry.clear_cache()
        unwrapped = False
        for binding in self:
            if not binding.method:
                continue
            ModelClass = self.env.registry.get(binding.model_name)
            if ModelClass is None:
                continue
            method = getattr(ModelClass, binding.method, None)
            if method is not None and getattr(method, ORIGIN_ATTR, None) is None:
                unwrapped = True
        if unwrapped:
            self._register_hook()
            self.env.registry.registry_invalidated = True

    # -- registry patching -------------------------------------------------

    def _register_hook(self):
        super()._register_hook()
        pairs = {}
        for binding in self.sudo().with_context(active_test=True).search([]):
            model = self.env.get(binding.model_name)
            if model is None:
                _logger.warning(
                    "Approval binding %s names model %s, which is not in this "
                    "registry; skipped.",
                    binding.id,
                    binding.model_name,
                )
                continue
            if not binding.method or binding.method in AUTOMATION_CLAIMED_METHODS:
                continue
            if refusal := self._get_method_refusal(binding.method):
                trace.REGISTRY.note(
                    "binding_not_applied",
                    binding=binding.id,
                    model=binding.model_name,
                    method=binding.method,
                    refusal=refusal,
                )
                _logger.warning(
                    "Approval binding %s is not applied: %s", binding.id, refusal
                )
                continue
            pairs.setdefault(binding.model_name, set()).add(binding.method)

        trace.REGISTRY.note(
            "bindings_wrapped",
            models=len(pairs),
            methods=sum(len(methods) for methods in pairs.values()),
        )
        for model_name, methods in pairs.items():
            ModelClass = self.env.registry[model_name]
            for method_name in methods:
                origin = getattr(ModelClass, method_name, None)
                if origin is None or getattr(origin, ORIGIN_ATTR, None) is not None:
                    continue
                guarded = self._get_guarded_method(model_name, method_name)
                setattr(guarded, ORIGIN_ATTR, origin)
                setattr(ModelClass, method_name, guarded)

    def _unregister_hook(self):
        """Remove only our own wrappers, identified by the marker we set."""
        for ModelClass in self.env.registry.values():
            for name, function in list(vars(ModelClass).items()):
                if getattr(function, ORIGIN_ATTR, None) is not None:
                    setattr(ModelClass, name, getattr(function, ORIGIN_ATTR))

    @api.model
    def _gate(self, records, bindings, label: str, call, replayable: bool = True):
        elevation = self._elevation()
        observations = []
        wanting = {}
        for binding in bindings:
            selected = binding._get_selected(records)
            if not selected:
                continue
            covered_ids = binding._get_covered_ids(selected)
            for record in selected:
                if binding._enforce(record, elevation, observations, covered_ids):
                    wanting[binding] = wanting.get(binding, records.browse()) | record

        if observations:
            records.env["approval.observation"].sudo().create(observations)
        if not wanting:
            return call(records)
        if not replayable:
            trace.REFUSAL.event("gate_not_replayable", method=label, records=records)
            raise UserError(
                records.env._(
                    "%(method)s needs an approval, and this call cannot be replayed "
                    "once it is granted: its arguments are not part of the "
                    "request. Hold it for approval where it is made instead.",
                    method=label,
                ),
            )
        if records.env.transaction.admitted_ids("approval.binding", REPLAY_ADMISSION):
            trace.REFUSAL.event(
                "replay_uncovered",
                method=label,
                records=records,
            )
            raise UserError(
                records.env._(
                    "%(method)s still needs an approval that does not cover "
                    "this record, so it was not run again.",
                    method=label,
                ),
            )
        waiting = records.browse()
        shown = records.env["approval.request"]
        for binding, pending in wanting.items():
            requests = binding._raise_requests_for(pending)
            if binding.approve_on_invoke:
                binding._approve_on_invoke(requests)
            covered_ids = binding._get_covered_ids(pending)
            still = pending.filtered_domain([("id", "not in", list(covered_ids))])
            if still:
                waiting |= still
                shown |= requests
        runnable = records - waiting
        trace.BINDING.note(
            "gate",
            method=label,
            records=records,
            wanting=[binding.id for binding in wanting],
            waiting=waiting.ids,
            runnable=runnable.ids,
            shown=shown.ids,
        )
        result = False
        if runnable:
            result = call(runnable)
            for binding, pending in wanting.items():
                binding._mark_invoked_run(pending & runnable)
        if waiting:
            return self._get_requests_action(shown)
        return result

    def _get_guarded_method(self, model_name: str, method_name: str):
        def guarded(records, *args, **kwargs):
            origin = getattr(guarded, ORIGIN_ATTR)
            Binding = records.env["approval.binding"]
            if not Binding._enabled():
                trace.BINDING.event(
                    "guard_skipped",
                    model=model_name,
                    method=method_name,
                    records=records.ids,
                    reason="kill_switch",
                )
                return origin(records, *args, **kwargs)

            bindings = Binding._bindings_for(model_name, method_name)
            if not bindings:
                trace.BINDING.event(
                    "guard_skipped",
                    model=model_name,
                    method=method_name,
                    records=records.ids,
                    reason="no_binding",
                )
                return origin(records, *args, **kwargs)
            trace.BINDING.event(
                "guard_entered",
                model=model_name,
                method=method_name,
                records=records.ids,
                bindings=bindings.ids,
            )

            return Binding._gate(
                records,
                bindings,
                method_name,
                lambda runnable: Binding._run_admitted(
                    runnable,
                    method_name,
                    lambda admitted: origin(admitted, *args, **kwargs),
                ),
            )

        guarded.__name__ = method_name
        guarded.__qualname__ = f"{model_name}.{method_name}"
        return guarded

    @api.model
    def _run_admitted(self, records, operation: str, call):
        """Run `call(records)` with `records` let through `operation`'s own wrapper.

        The ids are part of the admission: an operation that posts other records
        inside the admitted call leaves those records to be checked on their own.
        The admission lives on the transaction for the length of the call only.
        """
        with records.env.transaction.admitting(records._name, operation, records.ids):
            return call(records)

    @api.model
    def _get_admitted_ids(self, records, operation: str) -> set[int]:
        return set(records.env.transaction.admitted_ids(records._name, operation))

    @api.model
    def _enforce_at_checkpoint(self, records, bindings, operation: str) -> None:
        """Hold `operation`'s bindings on a path that reaches its checkpoint.

        A checkpoint can neither ask for an approval nor keep a request it raised,
        so a record Block or Request mode would stop is refused here.
        """
        admitted = self._get_admitted_ids(records, operation)
        pending = records.filtered(lambda record: record.id not in admitted)
        trace.BINDING.event(
            "checkpoint",
            operation=operation,
            records=records,
            admitted=sorted(admitted),
            checked=pending.ids,
        )
        if not pending:
            return
        elevation = self._elevation()
        observations = []
        refused = pending.browse()
        for binding in bindings:
            selected = binding._get_selected(pending)
            if not selected:
                continue
            covered_ids = binding._get_covered_ids(selected)
            for record in selected:
                if binding._enforce(record, elevation, observations, covered_ids):
                    refused |= record
        if observations:
            records.env["approval.observation"].sudo().create(observations)
        if refused:
            trace.REFUSAL.event(
                "checkpoint_blocked",
                operation=operation,
                records=refused,
                bindings=bindings.ids,
            )
            raise UserError(
                self.env._(
                    "%(records)s need an approval before %(operation)s can run, and "
                    "this way of running it cannot ask for one. Use %(operation)s "
                    "itself, which raises the request.",
                    records=", ".join(refused.mapped("display_name")),
                    operation=operation,
                ),
            )

    # -- verbs: the kernel's doors and checkpoints ask these -----------------

    @api.model
    def _get_declared_verb(self, records, verb: str):
        return records.env.registry.model_verbs.get(records._name, {}).get(verb)

    @api.model
    def _get_own_verb(self, records) -> str | None:
        """The verb a document's own obligation holds, for a request naming none."""
        for verb in records.env.registry.model_verbs.get(records._name, ()):
            own, _configured = self._split_verb_bindings(records._name, verb)
            if own:
                return verb
        return None

    @api.model
    def _split_verb_bindings(self, model_name: str, verb: str):
        """The document's own obligation on `verb`, and the configured bindings.

        A shipped obligation is the code gate it replaces, which the kill switch
        never reached; the configured bindings keep answering to it.
        """
        bindings = self._bindings_for_verb(model_name, verb).filtered(
            lambda binding: binding.mode != "act_decides"
        )
        if not bindings:
            return bindings, bindings
        own = bindings.filtered(lambda binding: binding._is_document_obligation())
        configured = bindings - own
        if configured and not self._enabled():
            configured = configured.browse()
        return own[:1], configured

    @api.model
    def _move_decides(self, model_name: str, verb: str) -> bool:
        """Whether moving a document into `verb`'s state is the request's decision."""
        return any(
            binding.mode == "act_decides"
            for binding in self._bindings_for_verb(model_name, verb)
        )

    def _hold_document_at_door(self, records, verb: str, run):
        """A document asks its own approval at the verb's door, as its code gate did."""
        self.check_singleton()
        records._check_before_approval(verb)
        if self.mode == "request" and not self._passes_on_elevation(self._elevation()):
            return records._run_through_approval(verb, run)
        records._check_approval_admits(verb, enforced=self._enforces(), binding=self)
        return self._run_admitted(records, verb, run)

    def _hold_document_at_checkpoint(self, records, verb: str) -> None:
        self.check_singleton()
        records._check_approval_admits(verb, enforced=self._enforces(), binding=self)

    def _enforces(self) -> bool:
        self.check_singleton()
        return self.mode != "advise" and not self._passes_on_elevation(
            self._elevation()
        )
