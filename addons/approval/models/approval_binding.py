import inspect
import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import ormcache

_logger = logging.getLogger(__name__)

# `automation._unregister_hook` walks the whole registry and does
# `delattr(Model, name)` for each of these, without checking who installed the
# attribute. A binding on any of them would be silently removed the next time
# automation re-registers, so the gate would stop existing without any error.
# `web_studio`'s approval rules refuse create/write/unlink for the same reason.
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


class ApprovalBinding(models.Model):
    """Gates a model's method on an approval, declaratively.

    `mixin.approval` requires the document to ask for its own approval. A
    binding is the other direction: the operation is intercepted, and the
    approval is consulted before it runs. That is what lets an approval cover
    an act that no document models -- applying an inventory adjustment,
    granting access -- and it is the mechanism `web_studio`'s approval rules
    already use, reimplemented here without their two defects (see `mode` and
    `sudo_policy`).
    """

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
    model_name = fields.Char(related="model_id.model", store=True, index=True)
    method = fields.Char(
        required=True,
        help="Method to gate. It is wrapped at registry load, so the gate "
        "holds for every caller, not only the user interface.",
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
          the record. The document asks for its own approval separately.
        • Request: the first call raises the approval instead of running, and
          the operation runs once it is approved.""",
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

    observation_ids = fields.One2many(
        comodel_name="approval.binding.observation",
        inverse_name="binding_id",
    )
    observation_count = fields.Count("observation_ids", "Observations")
    elevated_count = fields.Integer(compute="_compute_elevation_counts")
    self_elevated_count = fields.Integer(compute="_compute_elevation_counts")

    _model_method_domain_uniq = models.Constraint(
        "unique nulls not distinct (model_id, method, subject_domain)",
        "A binding already covers that model, method and condition.",
    )

    @api.depends("model_id", "method", "mode")
    def _compute_name(self) -> None:
        for binding in self:
            binding.name = (
                f"{binding.model_name or '?'}.{binding.method or '?'} ({binding.mode})"
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

    @api.constrains("model_id", "method", "mode", "subject_domain", "category_id")
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
            binding._check_method_available(model)
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
            if binding.mode == "request":
                binding._check_method_replayable(model)

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
        """Request mode re-runs the method after approval, so it must be safe to.

        Storing a call's arguments to replay them later is where this design
        would start guessing: a recordset argument may be stale, a keyword may
        carry a closure. Rather than half-solve that, request mode is limited
        to methods that take nothing but `self`, and the limit is enforced
        here instead of discovered at replay time.
        """
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

    # -- evaluation --------------------------------------------------------

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

    def _applies_to(self, record) -> bool:
        self.check_singleton()
        if not self.subject_domain:
            return True
        domain = self._parse_domain_or_warn()
        if domain is None:
            return False
        return bool(record.filtered_domain(domain))

    def _is_covered(self, record) -> bool:
        """Whether an approval already stands for this record."""
        self.check_singleton()
        if "approval_request_id" not in record._fields:
            return False
        request = record.sudo().approval_request_id
        return bool(
            request
            and request.state == "approved"
            and (not self.category_id or request.category_id == self.category_id)
        )

    def _get_observation_vals(self, record, elevation: str, would_block: bool) -> dict:
        self.check_singleton()
        return {
            "binding_id": self.id,
            "res_id": record.id,
            "user_id": self.env.uid,
            "elevation": elevation,
            "would_block": would_block,
        }

    def _enforce(self, record, elevation: str, observations: list) -> bool:
        """Apply this binding to one record. Returns True if it wants a request.

        Raises in Block mode when nothing covers the record.

        `elevation` is the CALLER's, measured once by the wrapper. This binding
        is read through `sudo()`, so asking `self.env` reports every caller as
        elevated -- and under "Any elevated caller passes" that waved an
        ordinary, unelevated user straight past a Block gate.

        Observations are appended to `observations` rather than written here,
        so a call on many records inserts them in one statement.
        """
        self.check_singleton()
        covered = self._is_covered(record)

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

    @api.model
    def _bindings_for(self, model_name: str, method: str):
        return self.sudo().browse(self._get_binding_ids(model_name, method))

    @api.model
    @ormcache("model_name", "method")
    def _get_binding_ids(self, model_name: str, method: str) -> tuple[int, ...]:
        """Every gated call consults this, so it is cached per (model, method).

        The key carries neither uid nor context, so the lookup must not depend
        on either: it runs under sudo, and `active_test` is forced rather than
        inherited -- a first caller with `active_test=False` would otherwise
        cache archived bindings for everyone.
        """
        return tuple(
            self.sudo()
            .with_context(active_test=True)
            .search([("model_name", "=", model_name), ("method", "=", method)])
            .ids
        )

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
        """Make a binding change take effect without a restart.

        The wrapper resolves its bindings at call time, so editing, archiving
        or re-moding a binding on an already-wrapped method only needs the
        lookup cache dropped -- and Odoo signals a cache clear to every worker.
        Only a binding on a method nothing wraps yet needs a new patch, and
        that is the one change another worker cannot see without reloading
        its registry, so it is the only one that asks for a reload.
        """
        self.env.registry.clear_cache()
        unwrapped = False
        for binding in self:
            ModelClass = self.env.registry.get(binding.model_name)
            if ModelClass is None:
                continue
            method = getattr(ModelClass, binding.method, None)
            if method is not None and getattr(method, ORIGIN_ATTR, None) is None:
                unwrapped = True
        if unwrapped:
            self._register_hook()
            self.env.registry.registry_invalidated = True

    def _raise_requests_for(self, records):
        """Ask for approval instead of running, and show what was raised.

        A record that already implements `mixin.approval` asks through its own
        `action_create_approval_request`, so its category matching and its
        `_before_approval_request_submit` hook still run. Anything else gets a
        request pointed at it by `res_model` / `res_id`, which is the same
        binding the mixin uses.
        """
        requests = self.env["approval.request"]
        for record in records:
            binding = self.filtered(lambda b, r=record: b.mode == "request")[:1]
            if not binding:
                continue
            if "approval_request_id" in record._fields:
                record.action_create_approval_request()
                requests |= record.approval_request_id
                continue
            request = self.env["approval.request"].create(
                {
                    "name": record.display_name,
                    "category_id": binding.category_id.id,
                    "request_owner_id": self.env.uid,
                    "res_model": record._name,
                    "res_id": record.id,
                }
            )
            request.action_confirm()
            requests |= request
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

    # -- registry patching -------------------------------------------------

    def _register_hook(self):
        """Wrap each gated method once, with every binding on it consulted.

        One patch per (model, method), never one per binding: a second patch
        over the first would make removal order-dependent, and `automation`
        already demonstrates what an indiscriminate `delattr` does to somebody
        else's wrapper.
        """
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
            if binding.method in AUTOMATION_CLAIMED_METHODS:
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

    def _get_guarded_method(self, model_name: str, method_name: str):
        def guarded(records, *args, **kwargs):
            origin = getattr(guarded, ORIGIN_ATTR)
            Binding = records.env["approval.binding"]
            if not Binding._enabled():
                return origin(records, *args, **kwargs)

            bindings = Binding._bindings_for(model_name, method_name)
            if not bindings:
                return origin(records, *args, **kwargs)

            elevation = Binding._elevation()
            observations = []
            wants_request = records.browse()
            for record in records:
                for binding in bindings:
                    if not binding._applies_to(record):
                        continue
                    if binding._enforce(record, elevation, observations):
                        wants_request |= record

            if observations:
                records.env["approval.binding.observation"].sudo().create(observations)
            if wants_request:
                return bindings._raise_requests_for(wants_request)
            return origin(records, *args, **kwargs)

        guarded.__name__ = method_name
        guarded.__qualname__ = f"{model_name}.{method_name}"
        return guarded
