import datetime
import inspect
import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import ormcache

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

ORIGIN_ATTR = "approval_binding_origin"
ENABLED_PARAM = "approval.binding_enabled"
REPLAY_CONTEXT_KEY = "approval_binding_replay"
INVOKE_CONTEXT_KEY = "approval_binding_invoking"
ENFORCEABLE_ACTION_TYPES = frozenset({"ir.actions.server", "ir.actions.report"})


class ApprovalBinding(models.Model):
    _name = "approval.binding"
    _inherit = ["mixin.approval.domain"]
    _description = "Approval Binding"
    _order = "model_name, method, sequence, id"

    name = fields.Char(compute="_compute_name", store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Model",
        required=True,
        ondelete="cascade",
        index=True,
    )
    model_name = fields.Char(
        related="model_id.model",
        store=True,
        index=True,
    )
    method = fields.Char(
        help="Method to gate. It is wrapped at registry load, so the gate "
        "holds for every caller, not only the user interface. A binding gates "
        "a method or an action, never both.",
    )
    action_id = fields.Many2one(
        comodel_name="ir.actions.actions",
        string="Action",
        ondelete="cascade",
        index="btree_not_null",
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
        ],
        required=True,
        default="advise",
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
          only clears the gate for the next call.""",
    )
    sudo_policy = fields.Selection(
        selection=[
            ("enforce", "Applies to everyone"),
            ("superuser", "Superuser passes"),
            ("bypass", "Any elevated caller passes"),
        ],
        required=True,
        default="superuser",
        help="""Who the gate does NOT apply to.

        `sudo()` flips `su` and keeps `uid`, so "elevated" covers both the
        real superuser and an ordinary user who called through `sudo()`. Those
        are different risks and this is deliberately not one switch:

        • Applies to everyone: nothing passes. Correct for a gate that must
          hold against internal callers too.
        • Superuser passes: the default. Internal machinery keeps working, an
          ordinary user cannot self-elevate past the gate.
        • Any elevated caller passes: what `web_studio` does unconditionally.
          Every bypass is still recorded, which is the part it does not do.""",
    )

    approve_on_invoke = fields.Boolean(
        help="Request mode only. When somebody who may approve a pending step of "
        "this record calls the operation, the call records their approval -- the "
        "way a Studio approval button works -- and the operation runs if nothing "
        "is left to approve. Otherwise the remaining approvers are asked and the "
        "call waits.",
    )
    run_on_approval = fields.Boolean(
        default=True,
        help="Request mode only. Run the operation, once and as the person who "
        "asked, when the request is approved. Off, approval only clears the gate "
        "and the operation runs when it is next called, which is how Studio "
        "approvals behave.",
    )
    observation_ids = fields.One2many(
        comodel_name="approval.binding.observation",
        inverse_name="binding_id",
    )
    observation_count = fields.Count("observation_ids", "Observations")
    elevated_count = fields.Integer(
        compute="_compute_elevation_counts",
    )
    self_elevated_count = fields.Integer(
        compute="_compute_elevation_counts",
    )

    _model_method_domain_uniq = models.Constraint(
        "unique nulls not distinct (model_id, method, action_id, subject_domain)",
        "A binding already covers that model, operation and condition.",
    )

    @api.depends("model_id", "method", "action_id", "mode")
    def _compute_name(self) -> None:
        for binding in self:
            target = binding.method or binding.action_id.name or "?"
            binding.name = f"{binding.model_name or '?'}.{target} ({binding.mode})"

    @api.depends("method", "action_id", "action_id.type")
    def _compute_is_enforced(self) -> None:
        for binding in self:
            binding.is_enforced = bool(binding.method) or (
                binding.action_id.type in ENFORCEABLE_ACTION_TYPES
            )

    def _compute_elevation_counts(self) -> None:
        grouped = self.env["approval.binding.observation"]._read_group(
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

    def _domain_source_field(self) -> str:
        return "subject_domain"

    # -- configuration-time validation ------------------------------------

    @api.constrains(
        "model_id",
        "method",
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
                raise ValidationError(
                    self.env._(
                        "%(model)s is not in the registry.",
                        model=binding.model_id.model,
                    ),
                )
            if bool(binding.method) == bool(binding.action_id):
                raise ValidationError(
                    self.env._(
                        "%(name)s must gate exactly one thing: a method or an action.",
                        name=binding.name,
                    ),
                )
            if binding.method:
                binding._check_method_available(model)
            else:
                binding._check_action_available()
            if binding.subject_domain:
                binding._check_domain_against_model(model)
            if binding.mode != "advise" and not binding.category_id:
                raise ValidationError(
                    self.env._(
                        "%(name)s is in %(mode)s mode, so it needs an approval "
                        "category to consult.",
                        name=binding.name,
                        mode=binding.mode,
                    ),
                )
            if binding.approve_on_invoke and binding.mode != "request":
                raise ValidationError(
                    self.env._(
                        "%(name)s approves on invoke, which needs Request mode: "
                        "Block mode raises no request for the caller to approve.",
                        name=binding.name,
                    ),
                )
            if binding.mode == "request" and binding.run_on_approval:
                if binding.method:
                    binding._check_method_replayable(model)
                elif binding.action_id.type != "ir.actions.server":
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
                raise ValidationError(
                    self.env._(
                        "%(action)s prints %(report_model)s, not %(model)s.",
                        action=self.action_id.name,
                        report_model=report_model,
                        model=self.model_id.model,
                    ),
                )
            if self.mode == "request":
                raise ValidationError(
                    self.env._(
                        "%(action)s is a report, and a report cannot wait for an "
                        "approval: refusing to render rolls back the request that "
                        "would have asked for one. Use Block, and let the client "
                        "raise the request before printing.",
                        action=self.action_id.name,
                    ),
                )

    def _check_method_available(self, model) -> None:
        self.check_singleton()
        if self.method in AUTOMATION_CLAIMED_METHODS:
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
        if self.method == "_register_hook" or self.model_id.model == self._name:
            raise ValidationError(
                self.env._("A binding cannot gate the binding machinery."),
            )
        function = getattr(model, self.method, None)
        if function is None or not callable(function):
            raise ValidationError(
                self.env._(
                    "%(model)s has no method %(method)s.",
                    model=model._name,
                    method=self.method,
                ),
            )

    def _check_method_replayable(self, model) -> None:
        self.check_singleton()
        function = getattr(model, self.method)
        signature = inspect.signature(function)
        required = [
            parameter
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.default is inspect.Parameter.empty
            and parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        ]
        if required:
            raise ValidationError(
                self.env._(
                    "%(method)s takes %(args)s, so it cannot be replayed after "
                    "approval. Request mode only gates methods that take no "
                    "argument; use Block mode for this one.",
                    method=self.method,
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
        if elevation == "none":
            return False
        if self.sudo_policy == "enforce":
            return False
        if self.sudo_policy == "bypass":
            return True
        return elevation == "superuser"

    def _get_selected(self, records):
        self.check_singleton()
        if not self.subject_domain:
            return records
        domain = self._parse_domain_or_warn()
        if domain is None:
            return records.browse()
        return records.filtered_domain(domain)

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
            "res_id": record.id,
            "user_id": self.env.uid,
            "elevation": elevation,
            "would_block": would_block,
        }

    def _enforce(self, record, elevation: str, observations: list, covered_ids) -> bool:
        self.check_singleton()
        covered = record.id in covered_ids

        if self.mode == "advise" or self._passes_on_elevation(elevation):
            observations.append(
                self._get_observation_vals(record, elevation, not covered)
            )
            return False

        if covered:
            return False

        if self.mode == "block":
            raise UserError(
                self.env._(
                    "%(record)s needs an approval before %(method)s can run.\n\n"
                    "Ask for approval on the document first.",
                    record=record.display_name,
                    method=self.method,
                ),
            )
        return True

    def _raise_requests_for(self, records):
        self.check_singleton()
        Request = self.env["approval.request"]
        requests = Request
        if "approval_request_id" in records._fields:
            for record in records:
                request = record.sudo().approval_request_id
                if request.state not in ("new", "pending"):
                    record.with_context(
                        approval_binding_for=(record._name, record.id, self.id),
                    ).action_create_approval_request()
                    request = record.sudo().approval_request_id
                requests |= request
            return requests

        open_by_res_id = {
            request.res_id: request
            for request in Request.search(
                [
                    ("binding_id", "=", self.id),
                    ("res_model", "=", records._name),
                    ("res_id", "in", records.ids),
                    ("state", "in", ("new", "pending")),
                ],
            )
        }
        for record in records:
            request = open_by_res_id.get(record.id)
            if not request:
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
            requests |= request
        return requests

    def _approve_on_invoke(self, requests) -> None:
        self.check_singleton()
        user = self.env.user
        for request in requests.filtered(lambda r: r.state == "pending"):
            approver = request._get_current_pending_approver(user)
            if not approver:
                continue
            try:
                with self.env.cr.savepoint():
                    request.with_user(user).with_context(
                        **{INVOKE_CONTEXT_KEY: True}
                    ).action_approve(approver)
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
        requests.filtered(
            lambda r: (
                r.binding_id == self
                and r.state == "approved"
                and not r.date_binding_replayed
            ),
        ).write({"date_binding_replayed": fields.Datetime.now()})

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
                    raise UserError(self.env._("The record no longer exists."))
                if self._get_selected(probe) and probe.id not in self._get_covered_ids(
                    probe
                ):
                    raise UserError(
                        self.env._(
                            "What was approved is no longer what is there: a "
                            "value this gate reads changed after the request was "
                            "raised. Ask for approval again."
                        )
                    )
                replaying = record.with_context(**{REPLAY_CONTEXT_KEY: request.id})
                if self.action_id:
                    self._run_action_on(replaying)
                else:
                    getattr(replaying, self.method)()
        except UserError as exc:
            error = str(exc) or type(exc).__name__
            _logger.info(
                "Approval binding %s: request %s approved, operation %s not run: %s",
                self.id,
                request.id,
                self.method,
                error,
            )

        if error:
            request.sudo().write({"binding_replay_error": error})
            body = self.env._(
                "The gated operation %(method)s did not run: %(error)s",
                method=self.method,
                error=error,
            )
        else:
            request.sudo().write(
                {
                    "date_binding_replayed": fields.Datetime.now(),
                    "binding_replay_error": False,
                }
            )
            body = self.env._(
                "The gated operation %(method)s ran as %(user)s.",
                method=self.method,
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
        result = super().write(vals)
        self._apply_to_registry()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result

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
            pairs.setdefault(binding.model_name, set()).add(binding.method)

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
    def _gate(self, records, bindings, label: str, call):
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
            records.env["approval.binding.observation"].sudo().create(observations)
        if not wanting:
            return call(records)
        if records.env.context.get(REPLAY_CONTEXT_KEY):
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
            still = pending.filtered(
                lambda record, ids=covered_ids: record.id not in ids,
            )
            if still:
                waiting |= still
                shown |= requests
        runnable = records - waiting
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
                return origin(records, *args, **kwargs)

            bindings = Binding._bindings_for(model_name, method_name)
            if not bindings:
                return origin(records, *args, **kwargs)

            return Binding._gate(
                records,
                bindings,
                method_name,
                lambda runnable: origin(runnable, *args, **kwargs),
            )

        guarded.__name__ = method_name
        guarded.__qualname__ = f"{model_name}.{method_name}"
        return guarded
