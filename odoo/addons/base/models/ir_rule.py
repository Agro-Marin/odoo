import logging
from typing import Any, Self

from odoo import _, api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL, config
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class IrRule(models.Model):
    _name = "ir.rule"
    _description = "Record Rule"
    _order = "model_id DESC,id"
    # Single source of truth for the four CRUD access modes: name -> SQL
    # column. Mode validation derives from these keys (mirrors
    # ir.model.access._PERM_COLUMNS).
    _PERM_COLUMNS = {
        "read": SQL("r.perm_read"),
        "write": SQL("r.perm_write"),
        "create": SQL("r.perm_create"),
        "unlink": SQL("r.perm_unlink"),
    }
    _allow_sudo_commands = False

    name = fields.Char()
    active = fields.Boolean(
        default=True,
        help="If you uncheck the active field, it will disable the record rule without deleting it (if you delete a native record rule, it may be re-created when you reload the module).",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        index=True,
        required=True,
        ondelete="cascade",
    )
    groups = fields.Many2many(
        "res.groups",
        "rule_group_rel",
        "rule_group_id",
        "group_id",
        ondelete="restrict",
    )
    domain_force = fields.Text(string="Domain")
    perm_read = fields.Boolean(string="Read", default=True)
    perm_write = fields.Boolean(string="Write", default=True)
    perm_create = fields.Boolean(string="Create", default=True)
    perm_unlink = fields.Boolean(string="Delete", default=True)

    _no_access_rights = models.Constraint(
        "CHECK (perm_read OR perm_write OR perm_create OR perm_unlink)",
        "Rule must have at least one checked access right!",
    )

    @api.model
    def _eval_context(self) -> dict[str, Any]:
        """Return the evaluation context (namespace) for ir.rule domains."""
        # Empty context for 'user' keeps domain evaluation independent from the
        # caller's context. company_ids holds the companies activated via the
        # switch-company menu (filtered and trusted).
        return {
            "user": self.env.user.with_context({}),
            "company_ids": self.env.companies.ids,
            "company_id": self.env.company.id,
        }

    @api.depends("groups")
    def _compute_global(self) -> None:
        for rule in self:
            rule["global"] = not rule.groups

    @api.constrains("model_id")
    def _check_model_name(self) -> None:
        # Don't allow rules on rules records (this model).
        if any(rule.model_id.model == self._name for rule in self):
            raise ValidationError(
                _("Rules can not be applied on the Record Rules model.")
            )

    @api.constrains("active", "domain_force", "model_id")
    def _check_domain(self) -> None:
        eval_context = self._eval_context()
        for rule in self:
            if rule.active and rule.domain_force:
                try:
                    domain = safe_eval(rule.domain_force, eval_context)
                    model = self.env[rule.model_id.model].sudo()
                    Domain(domain).validate(model)
                except Exception as e:
                    raise ValidationError(_("Invalid domain: %s", e)) from None

    def _compute_domain_keys(self) -> list[str]:
        """Return the list of context keys to use for caching ``_compute_domain``."""
        return ["allowed_company_ids"]

    def _get_failing(self, for_records: Any, mode: str = "read") -> Self:
        """Return the rules for *mode* that fail on *for_records* for the user.

        May return any global rule and/or all local rules: local rules are
        OR-ed (the group succeeds or fails as a whole) while global rules are
        AND-ed and can each fail.
        """
        # Both sudos are anti-recursion guards: loading ir.rules must not itself
        # trigger rule evaluation. active_test off so evaluation considers
        # inactive records, else archived rows are missed and rules misreported.
        Model = for_records.browse(()).sudo().with_context(active_test=False)
        eval_context = self._eval_context()

        all_rules = self._get_rules(Model._name, mode=mode).sudo()

        # First check if group rules fail for any record (i.e. searching on
        # (records, group_rules) filters some out).
        # NOTE: this group source (env.user.all_group_ids) must stay in
        # lock-step with the SQL group filter in _get_rules / _compute_domain
        # (user._get_group_ids() == clean-context all_group_ids._ids); drift
        # would mis-blame rules.
        group_rules = all_rules.filtered(
            lambda r: r.groups and r.groups & self.env.user.all_group_ids
        )
        group_domains = Domain.OR(
            safe_eval(r.domain_force, eval_context) if r.domain_force else []
            for r in group_rules
        )
        # If all records come back, the group rules are not failing. Compare
        # against the distinct-id count (search_count counts distinct rows);
        # a duplicated id would never match len(for_records) and mis-blame
        # passing group rules.
        distinct_count = len(set(for_records.ids))
        if (
            Model.search_count(group_domains & Domain("id", "in", for_records.ids))
            == distinct_count
        ):
            group_rules = self.browse(())

        # failing rules are previously selected group rules or any failing global rule
        def is_failing(r, ids=for_records.ids):
            dom = Domain(
                safe_eval(r.domain_force, eval_context) if r.domain_force else []
            )
            return Model.search_count(dom & Domain("id", "in", ids)) < len(set(ids))

        return all_rules.filtered(
            lambda r: r in group_rules or (not r.groups and is_failing(r))
        ).with_user(self.env.user)

    def _get_rules(self, model_name: str, mode: str = "read") -> Self:
        """Return all rules matching the model and mode for the current user."""
        if mode not in self._PERM_COLUMNS:
            raise ValueError(
                f"Invalid mode {mode!r}: expected one of {tuple(self._PERM_COLUMNS)}."
            )

        if self.env.su:
            return self.browse(())

        sql = SQL(
            """
            SELECT r.id FROM ir_rule r
            JOIN ir_model m ON (r.model_id=m.id)
            WHERE m.model = %s AND r.active AND %s
                AND (r.global OR r.id IN (
                    SELECT rule_group_id FROM rule_group_rel rg
                    WHERE rg.group_id = ANY(%s)
                ))
            ORDER BY r.id
        """,
            model_name,
            self._PERM_COLUMNS[mode],
            list(self.env.user._get_group_ids()),
        )
        return self.browse(v for (v,) in self.env.execute_query(sql))

    @api.model
    @tools.conditional(
        "xml" not in config["dev_mode"],
        tools.ormcache(
            "self.env.uid",
            "self.env.su",
            "model_name",
            "mode",
            "tuple(self._compute_domain_context_values())",
        ),
    )
    def _compute_domain(self, model_name: str, mode: str = "read") -> Domain:
        model = self.env[model_name]

        # add rules for parent models
        global_domains: list[Domain] = []
        for parent_model_name, parent_field_name in model._inherits.items():
            if not model._fields[parent_field_name].store:
                continue
            if domain := self._compute_domain(parent_model_name, mode):
                global_domains.append(Domain(parent_field_name, "any", domain))

        rules = self._get_rules(model_name, mode=mode)
        if not rules:
            return Domain.AND(global_domains).optimize(model)

        # browse user and rules with sudo to avoid access errors!
        eval_context = self._eval_context()
        # NOTE: keep this group source in lock-step with _get_rules' SQL filter
        # (user._get_group_ids() == clean-context all_group_ids._ids).
        user_groups = self.env.user.all_group_ids
        group_domains: list[Domain] = []
        for rule in rules.sudo():
            if rule.groups and not (rule.groups & user_groups):
                continue
            dom = (
                Domain(safe_eval(rule.domain_force, eval_context))
                if rule.domain_force
                else Domain.TRUE
            )
            if rule.groups:
                group_domains.append(dom)
            else:
                global_domains.append(dom)

        if group_domains:
            global_domains.append(Domain.OR(group_domains))
        return Domain.AND(global_domains).optimize(model)

    def _compute_domain_context_values(self) -> Any:
        for k in self._compute_domain_keys():
            v = self.env.context.get(k)
            if isinstance(v, list):
                # Tuple, not frozenset: order-dependent but safer as a cache key
                # (slightly more miss-prone).
                v = tuple(v)
            yield v

    def unlink(self) -> bool:
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        self.env.flush_all()
        self.env.registry.clear_cache()
        return res

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        self.env.flush_all()
        self.env.registry.clear_cache()
        return res

    def _make_access_error(self, operation: str, records: Any) -> AccessError:
        _logger.info(
            "Access Denied by record rules for operation: %s on record ids: %r, uid: %s, model: %s",
            operation,
            records.ids[:6],
            self.env.uid,
            records._name,
        )
        self = self.with_context(self.env.user.context_get())

        model = records._name
        description = self.env["ir.model"]._get(model).name or model
        operations = {
            "read": _("read"),
            "write": _("write"),
            "create": _("create"),
            "unlink": _("unlink"),
        }
        user_description = f"{self.env.user.name} (id={self.env.user.id})"
        operation_error = _(
            "Uh-oh! Looks like you have stumbled upon some top-secret records.\n\n"
            "Sorry, %(user)s doesn't have '%(operation)s' access to:",
            user=user_description,
            operation=operations.get(operation, operation),
        )
        failing_model = _(
            "- %(description)s (%(model)s)",
            description=description,
            model=model,
        )

        resolution_info = _(
            "If you really, really need access, perhaps you can win over your friendly administrator with a batch of freshly baked cookies."
        )

        # Public and portal users lack "base.group_no_one" even in debug mode,
        # so including rule and record names below is relatively safe.
        rules = self._get_failing(records, mode=operation).sudo()

        display_records = records[:6].sudo()
        # Heuristic: substring match on the domain source text, not a precise
        # field check (only drives the optional multi-company hint below).
        company_related = any("company_id" in (r.domain_force or "") for r in rules)

        def get_record_description(rec):
            # If the user has access to the company of the record, add this
            # information in the description to help them to change company
            if (
                company_related
                and "company_id" in rec
                and rec.company_id in self.env.user.company_ids
            ):
                return f"{description}, {rec.display_name} ({model}: {rec.id}, company={rec.company_id.display_name})"
            return f"{description}, {rec.display_name} ({model}: {rec.id})"

        context = None
        if company_related:
            suggested_companies = display_records._get_redirect_suggested_company()
            if suggested_companies and len(suggested_companies) != 1:
                resolution_info += _(
                    "\n\nNote: this might be a multi-company issue. Switching company may help - in Odoo, not in real life!"
                )
            elif (
                suggested_companies and suggested_companies in self.env.user.company_ids
            ):
                context = {
                    "suggested_company": {
                        "id": suggested_companies.id,
                        "display_name": suggested_companies.display_name,
                    }
                }
                resolution_info += _(
                    "\n\nThis seems to be a multi-company issue, you might be able to access the record by switching to the company: %s.",
                    suggested_companies.display_name,
                )
            elif suggested_companies:
                resolution_info += _(
                    "\n\nThis seems to be a multi-company issue, but you do not have access to the proper company to access the record anyhow."
                )

        if (
            not self.env.user.has_group("base.group_no_one")
            or not self.env.user._is_internal()
        ):
            msg = f"{operation_error}\n{failing_model}\n\n{resolution_info}"
        else:
            # This extended AccessError is only displayed in debug mode.
            failing_records = "\n".join(
                f"- {get_record_description(rec)}" for rec in display_records
            )
            rules_description = "\n".join(f"- {rule.name}" for rule in rules)
            failing_rules = _("Blame the following rules:\n%s", rules_description)
            msg = f"{operation_error}\n{failing_records}\n\n{failing_rules}\n\n{resolution_info}"

        # clean up the cache of records because of filtered_domain to check ir.rule + display_name above
        records.invalidate_recordset()

        exception = AccessError(msg)
        if context:
            exception.context = context
        return exception


#
# 'global' is a Python keyword, so the field cannot be declared inline; it is
# assigned onto the class instead (the metaclass normally adds '_module').
#
# Audit 2026-07-07: NOT renamed (e.g. to `is_global`) — ~76 call sites across
# this repo plus the enterprise (26) and agromarin (15) XML sites, which live
# outside this repo and would break on load. Keep the shim until a cross-repo
# rename is scheduled.
#
global_ = fields.Boolean(
    compute="_compute_global",
    store=True,
    help="If no group is specified the rule is global and applied to everyone",
)
setattr(IrRule, "global", global_)
global_.__set_name__(IrRule, "global")
