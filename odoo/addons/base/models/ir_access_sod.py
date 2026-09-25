import json
import logging
from typing import Any

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import frozendict, ormcache

_logger = logging.getLogger(__name__)

PENDING_UPGRADE_EXCEPTIONS = "base.sod_pending_upgrade_exceptions"

SOD_LOG_EVENTS = [
    ("sod_conflict", "Duties in conflict"),
    ("sod_refused", "Refused for conflicting duties"),
]


class IrAccessLog(models.Model):
    _inherit = "ir.access.log"

    event = fields.Selection(
        selection_add=SOD_LOG_EVENTS,
        ondelete={event: "cascade" for event, _label in SOD_LOG_EVENTS},
    )


class IrAccessSodFunction(models.Model):
    """A business duty, held by whoever holds one of its groups or verbs."""

    _name = "ir.access.sod.function"
    _description = "Business Duty"
    _order = "name"

    name = fields.Char(
        translate=True,
        required=True,
    )
    group_ids = fields.Many2many(
        comodel_name="res.groups",
        help="Holding any of these groups, directly or through another, is holding "
        "the duty.",
    )
    excluded_group_ids = fields.Many2many(
        comodel_name="res.groups",
        relation="ir_access_sod_function_excluded_group_rel",
        string="Except Holders Of",
        help="Whoever holds one of these groups does not hold the duty, whatever "
        "else they hold: a manager who is also a clerk is not the clerk.",
    )
    verb_ids = fields.One2many(
        comodel_name="ir.access.sod.function.verb",
        inverse_name="function_id",
        string="Verbs",
        help="Holding a permission row for any of these verbs is holding the duty.",
    )

    def _get_holder_ids(self, users) -> set[int]:
        """Which of `users` hold this duty now."""
        self.check_singleton()
        spec = dict(self._get_duty_spec())
        groups = set(spec["groups"])
        Access = self.env["ir.access"]
        for model_name, verb in spec["verbs"]:
            groups |= Access._group_ids_with_access(model_name, verb)
        spec["groups"] = frozenset(groups)
        return {
            user.id
            for user in users
            if self._holds(spec, user.id, frozenset(user.all_group_ids._ids))
        }

    @ormcache("self.id", cache="groups")
    def _get_duty_spec(self) -> dict[str, Any]:
        # every grant asks every rule's duties: what they name is read once
        self.check_singleton()
        return {
            "groups": frozenset(self.group_ids._ids),
            "excluded": frozenset(self.excluded_group_ids._ids),
            "verbs": tuple((line.model_id.model, line.verb) for line in self.verb_ids),
        }

    @api.model
    def _holds(self, spec: dict[str, Any], user_id: int, held: frozenset) -> bool:
        return bool(spec["groups"] & held) and not spec["excluded"] & held

    @api.model_create_multi
    def create(self, vals_list):
        functions = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        return functions

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache("groups")
        return result


class IrAccessSodFunctionVerb(models.Model):
    _name = "ir.access.sod.function.verb"
    _description = "Business Duty Verb"

    function_id = fields.Many2one(
        comodel_name="ir.access.sod.function",
        index=True,
        required=True,
        ondelete="cascade",
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        required=True,
        ondelete="cascade",
    )
    verb = fields.Char(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        return lines

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache("groups")
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache("groups")
        return result

    @api.constrains("model_id", "verb")
    def _check_verb(self) -> None:
        for line in self:
            if line.verb not in self.env.registry.model_verbs.get(
                line.model_id.model, {}
            ):
                raise ValidationError(
                    self.env._(
                        "%(model)s declares no verb %(verb)s.",
                        model=line.model_id.model,
                        verb=line.verb,
                    )
                )


class IrAccessSodRule(models.Model):
    """Two duties one person must not hold together.

    Checked whenever a grant starts, changes scope or a module says a duty's
    holders changed. A conflict is logged; a blocking rule also refuses the change
    unless the person holds a live exception for the rule.
    """

    _name = "ir.access.sod.rule"
    _description = "Separation of Duties Rule"
    _order = "name"

    name = fields.Char(
        translate=True,
        required=True,
    )
    active = fields.Boolean(default=True)
    function_a_id = fields.Many2one(
        comodel_name="ir.access.sod.function",
        string="Duty",
        required=True,
        ondelete="restrict",
    )
    function_b_id = fields.Many2one(
        comodel_name="ir.access.sod.function",
        string="Conflicts With",
        required=True,
        ondelete="restrict",
    )
    action = fields.Selection(
        selection=[("warn", "Warn"), ("block", "Block")],
        default="block",
        required=True,
        help="Warn: the conflict is logged and let through. Block: the change that "
        "creates it is refused, unless the person holds a live exception for this "
        "rule.",
    )

    @api.model
    def _check_users(self, users, cause: str) -> None:
        """Log every conflict `users` hold now; refuse a blocking one without exception."""
        users = users.filtered(
            lambda user: not user.share and user.active and user.id != SUPERUSER_ID
        )
        if not users:
            return
        rule_ids = self._get_active_rule_ids()
        if not rule_ids:
            return
        logs: list[dict[str, Any]] = []
        refused = []
        Function = self.env["ir.access.sod.function"]
        for rule_id, function_a_id, function_b_id in rule_ids:
            holders = Function.browse(function_a_id)._get_holder_ids(users)
            if not holders:
                continue
            holders &= Function.browse(function_b_id)._get_holder_ids(users)
            rule = self.browse(rule_id)
            for user in users.browse(sorted(holders)):
                exception = self.env["ir.access.exception"]._find(user, "sod", rule)
                if exception:
                    exception._record_use(cause)
                    continue
                # a module's data loads before the upgrade can grant its
                # exceptions: while the registry loads, a conflict is logged
                blocking = rule.action == "block" and self.env.registry.ready
                logs.append(rule._log_values(user, cause, blocking))
                if blocking:
                    refused.append((rule, user))
        if logs:
            self.env["ir.access.log"]._record(logs)
        if refused:
            rule, user = refused[0]
            # the refusal rolls back its own log row; the server log keeps it
            _logger.warning(
                "Separation of duties rule %s refused %s: %s would hold both %s "
                "and %s.",
                rule.name,
                cause,
                user.login,
                rule.function_a_id.name,
                rule.function_b_id.name,
            )
            raise AccessError(
                self.env._(
                    "%(user)s would both %(duty)s and %(other)s, which rule "
                    "'%(rule)s' keeps apart. Ask for an exception, or remove one of "
                    "the two.",
                    user=user.name,
                    duty=rule.function_a_id.name,
                    other=rule.function_b_id.name,
                    rule=rule.name,
                )
            )

    @api.model
    @ormcache(cache="groups")
    def _get_active_rule_ids(self) -> tuple[tuple[int, int, int], ...]:
        # every grant asks, and most databases have no rule: kept off the query
        if not self.env.ref("base.privilege_check_duties", raise_if_not_found=False):
            # base's own data is loading: no module that ships a rule is yet
            return ()
        rules = self.with_privilege(
            "base.privilege_check_duties",
            reason="every grant is checked against the separation of duties",
        ).search_fetch([], ["function_a_id", "function_b_id"])
        return tuple(
            (rule.id, rule.function_a_id.id, rule.function_b_id.id) for rule in rules
        )

    @api.model
    @ormcache(cache="groups")
    def _get_affecting_group_ids(self) -> frozenset[int]:
        # the groups whose grant can make someone hold a rule's duty: those that
        # are, or imply, a group a duty is held through; a grant of any other
        # group is not checked at all
        rule_ids = self._get_active_rule_ids()
        if not rule_ids:
            return frozenset()
        Function = self.env["ir.access.sod.function"].with_privilege(
            "base.privilege_check_duties",
            reason="every grant is checked against the separation of duties",
        )
        Access = self.env["ir.access"]
        held: set[int] = set()
        for _rule_id, *function_ids in rule_ids:
            for function in Function.browse(function_ids):
                spec = function._get_duty_spec()
                held |= spec["groups"] | spec.get("approver_group_ids", frozenset())
                for model_name, verb in spec["verbs"]:
                    held |= Access._group_ids_with_access(model_name, verb)
        if not held:
            return frozenset()
        return frozenset(
            group.id
            for group in self.env["res.groups"].search_fetch([], ["all_implied_ids"])
            if held & ({group.id} | set(group.all_implied_ids._ids))
        )

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        return rules

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache("groups")
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache("groups")
        return result

    def _get_conflicting_user_ids(self, users) -> set[int]:
        self.check_singleton()
        return self.function_a_id._get_holder_ids(
            users
        ) & self.function_b_id._get_holder_ids(users)

    def _log_values(self, user, cause: str, blocking: bool) -> dict[str, Any]:
        self.check_singleton()
        return {
            "event": "sod_refused" if blocking else "sod_conflict",
            "subject_user_id": user.id,
            "cause": cause,
            "cause_model": self._name,
            "cause_res_id": self.id,
            "reason": self.name,
        }

    def _get_conflicts(self) -> list[tuple[Any, Any]]:
        """Every (rule, user) holding both duties today, excepted or not."""
        internal = self.env["res.users"].search(
            [("share", "=", False), ("id", "!=", SUPERUSER_ID)]
        )
        return [
            (rule, user)
            for rule in self
            for user in internal.browse(
                sorted(rule._get_conflicting_user_ids(internal))
            )
        ]

    def _arm_upgrade_exceptions(self, reason: str) -> None:
        """Leave these rules' upgrade-day exceptions pending, in a way that survives.

        What a module's post-migrate calls: the end stage grants them once every
        module is loaded, and if it never runs, the cron it arms does.
        """
        Param = self.env["ir.config_parameter"]
        pending = json.loads(Param.get_param(PENDING_UPGRADE_EXCEPTIONS) or "{}")
        pending.update({str(rule.id): reason for rule in self})
        Param.set_param(PENDING_UPGRADE_EXCEPTIONS, json.dumps(pending))
        self.env.ref("base.ir_cron_sod_upgrade_exceptions").write(
            {"active": True, "nextcall": fields.Datetime.now()}
        )

    @api.model
    def _cron_grant_pending_upgrade_exceptions(self) -> None:
        pending = json.loads(
            self.env["ir.config_parameter"].get_param(PENDING_UPGRADE_EXCEPTIONS)
            or "{}"
        )
        for rule_id, reason in pending.items():
            self.with_context(active_test=False).browse(
                int(rule_id)
            ).exists()._grant_upgrade_exceptions(reason)
        self.env.ref("base.ir_cron_sod_upgrade_exceptions").active = False

    def _grant_upgrade_exceptions(self, reason: str, days: int = 90):
        """Let everyone who holds both duties today keep them, for a while, by name.

        A rule shipped as blocking would otherwise refuse the next change of duties
        of each person already in conflict. Each exception is dated, reviewed and
        reminded before it lapses, like any other.
        """
        Exception_ = self.env["ir.access.exception"]
        granted = Exception_
        for rule, user in self._get_conflicts():
            if not Exception_._find(user, "sod", rule):
                granted |= Exception_._grant_for_upgrade(
                    user, "sod", rule, reason, days=days
                )
                _logger.info(
                    "Access exception granted to %s for rule %s until %s.",
                    user.login,
                    rule.name,
                    granted[-1:].date_to,
                )
        Param = self.env["ir.config_parameter"]
        pending = json.loads(Param.get_param(PENDING_UPGRADE_EXCEPTIONS) or "{}")
        if pending:
            for rule in self:
                pending.pop(str(rule.id), None)
            Param.set_param(
                PENDING_UPGRADE_EXCEPTIONS, json.dumps(pending) if pending else False
            )
            if not pending:
                self.env.ref("base.ir_cron_sod_upgrade_exceptions").active = False
        return granted

    @api.model
    def action_view_conflicts(self) -> dict[str, Any]:
        Exception_ = self.env["ir.access.exception"]
        conflicts = self.env["ir.access.sod.conflict"].create(
            [
                {
                    "rule_id": rule.id,
                    "user_id": user.id,
                    "exception_id": Exception_._find(user, "sod", rule).id,
                }
                for rule, user in self.search([])._get_conflicts()
            ]
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Duties in Conflict"),
            "res_model": "ir.access.sod.conflict",
            "view_mode": "list",
            "domain": [("id", "in", conflicts.ids)],
        }


class ResUsersGrant(models.Model):
    _inherit = "res.users.grant"
    _access_anchors = frozendict(
        {
            "owner": "user_id",
        }
    )

    def _on_grant_changed(self, event: str) -> None:
        super()._on_grant_changed(event)
        Rule = self.env["ir.access.sod.rule"]
        affecting = Rule._get_affecting_group_ids()
        if affecting and any(grant.group_id.id in affecting for grant in self):
            Rule._check_users(self.user_id, event)


class IrAccessSodConflict(models.TransientModel):
    _name = "ir.access.sod.conflict"
    _description = "Duties in Conflict"
    _order = "rule_id, user_id"

    rule_id = fields.Many2one(
        comodel_name="ir.access.sod.rule",
        required=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Person",
        required=True,
        ondelete="cascade",
    )
    exception_id = fields.Many2one(
        comodel_name="ir.access.exception",
        ondelete="set null",
        help="The live exception that lets the person hold both duties, if any.",
    )
