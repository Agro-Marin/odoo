import contextlib
import contextvars
import logging
import weakref
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.debug_log import DebugLog

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)

# set while a grant writes the membership it projects, so the write-through of
# res.users and res.groups does not turn the projection back into grants; an
# in-process marker, not a context key a client could send
_PROJECTING: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "res_users_grant_projecting", default=False
)
# set while the grant model itself changes a grant's lifecycle fields
_LIFECYCLE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "res_users_grant_lifecycle", default=False
)
# the users a create is making: no cache holds anything about them yet
_FRESH_USERS: contextvars.ContextVar[frozenset[int]] = contextvars.ContextVar(
    "res_users_grant_fresh_users", default=frozenset()
)
# the transaction's cr.cache entry naming the users whose group state it
# computed
GROUP_STATE_COMPUTED = "res_users_group_state_computed"
# the registries whose database has the grant table
_GRANTS_AVAILABLE: weakref.WeakValueDictionary[int, Any] = weakref.WeakValueDictionary()
# set while grants follow a membership write, whose writer clears the access
# caches once it is done
_FOLLOWING: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "res_users_grant_following", default=False
)

GRANT_CAUSES = [
    ("manual", "Manual"),
    ("module", "Module data"),
    ("automation", "Automation"),
    ("migration", "Migration"),
    ("provisioning", "Provisioning"),
    ("approval_request", "Access request"),
    ("position", "Position"),
    ("break_glass", "Break-glass"),
]
# causes whose producer is a later phase: a grant cannot claim them yet
UNPRODUCED_CAUSES = frozenset({"approval_request", "position", "break_glass"})
# why a grant exists: code acting under a named privilege states it, as the
# superuser does; anyone else gives a manual grant
CAUSE_FIELDS = frozenset({"cause", "cause_model", "cause_res_id"})
# who gave or ended a grant: only the superuser writes these
AUDIT_FIELDS = CAUSE_FIELDS | frozenset(
    {"granted_by_id", "revoked_by_id", "revoked_at", "revoke_reason"}
)
EDITABLE_FIELDS = frozenset({"company_ids", "date_from", "date_to", "reason"})


@contextlib.contextmanager
def _marked(marker: contextvars.ContextVar[bool]) -> Iterator[None]:
    token = marker.set(True)
    try:
        yield
    finally:
        marker.reset(token)


def projecting() -> bool:
    return _PROJECTING.get()


class ResUsersGrant(models.Model):
    _name = "res.users.grant"
    _access_audit = True
    _description = "Group Grant"
    _order = "user_id, group_id, id"
    _rec_name = "group_id"
    _allow_sudo_commands = False

    user_id = fields.Many2one(
        comodel_name="res.users",
        index=True,
        required=True,
        ondelete="cascade",
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        index=True,
        required=True,
        ondelete="cascade",
    )
    company_ids = fields.Many2many(
        comodel_name="res.company",
        relation="res_users_grant_company_rel",
        column1="grant_id",
        column2="company_id",
        string="Companies",
        help="The grant holds only for records of these companies, and only "
        "while one of them is among the companies in use. Empty: every company "
        "the user works in.",
    )
    scoped = fields.Boolean(
        compute="_compute_scoped",
        precompute=True,
        store=True,
        help="Whether the grant is limited to some companies.",
    )
    date_from = fields.Datetime(
        string="From",
        help="The grant holds from this moment; empty: from its creation.",
    )
    date_to = fields.Datetime(
        string="Until",
        help="The grant ends at this moment; empty: until it is revoked.",
    )
    state = fields.Selection(
        selection=[
            ("scheduled", "Scheduled"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ],
        default="active",
        index=True,
        copy=False,
        readonly=True,
        required=True,
    )
    cause = fields.Selection(
        selection=GRANT_CAUSES,
        default="manual",
        readonly=True,
        required=True,
        help="Why the grant exists: given by hand, shipped by a module's data, "
        "held by code that names itself, carried over by a migration.",
    )
    cause_model = fields.Char(
        index=True,
        readonly=True,
    )
    cause_res_id = fields.Many2oneReference(
        model_field="cause_model",
        string="Cause Record",
        readonly=True,
    )
    reason = fields.Char()
    granted_by_id = fields.Many2one(
        comodel_name="res.users",
        default=lambda self: self.env.uid,
        readonly=True,
        ondelete="set null",
    )
    revoked_by_id = fields.Many2one(
        comodel_name="res.users",
        copy=False,
        readonly=True,
        ondelete="set null",
    )
    revoked_at = fields.Datetime(
        string="Revoked On",
        copy=False,
        readonly=True,
    )
    revoke_reason = fields.Char(
        copy=False,
        readonly=True,
    )

    _dates_ordered = models.Constraint(
        "CHECK(date_to IS NULL OR date_from IS NULL OR date_to > date_from)",
        "A grant must end after it starts.",
    )

    @api.depends("company_ids")
    def _compute_scoped(self) -> None:
        for grant in self:
            grant.scoped = bool(grant.company_ids)

    @api.depends("user_id", "group_id")
    def _compute_display_name(self) -> None:
        for grant in self:
            grant.display_name = (
                f"{grant.user_id.display_name}: {grant.group_id.full_name}"
            )

    @api.model
    def _live_domain(self, now: datetime | None = None) -> Domain:
        now = now or self.env.cr.now()
        return (
            Domain("state", "in", ("scheduled", "active"))
            & (Domain("date_from", "=", False) | Domain("date_from", "<=", now))
            & (Domain("date_to", "=", False) | Domain("date_to", ">", now))
        )

    def _state_at(self, date_from: Any, date_to: Any, now: datetime) -> str:
        date_from = fields.Datetime.to_datetime(date_from)
        date_to = fields.Datetime.to_datetime(date_to)
        if date_to and date_to <= now:
            return "expired"
        if date_from and date_from > now:
            return "scheduled"
        return "active"

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        now = self.env.cr.now()
        claimed: set[str] = set()
        for vals in vals_list:
            if not self.env.su:
                if vals.get("cause") in UNPRODUCED_CAUSES:
                    _debug.logic(
                        "create_refused", reason="unproduced_cause", cause=vals["cause"]
                    )
                    raise ValidationError(
                        self.env._(
                            "A grant cannot claim the cause %(cause)s: nothing "
                            "produces it yet.",
                            cause=vals["cause"],
                        )
                    )
                settable = CAUSE_FIELDS if self.env.privileges else frozenset()
                claimed.update(
                    name
                    for name in (AUDIT_FIELDS - settable) & vals.keys()
                    if vals[name]
                )
            vals["state"] = self._state_at(
                vals.get("date_from"), vals.get("date_to"), now
            )
            if vals["state"] == "expired":
                _debug.logic("create_refused", reason="already_expired")
                raise ValidationError(
                    self.env._("A grant cannot be created already expired.")
                )
        grants = super().create(vals_list)
        grants._check_scope()
        if _debug.lifecycle.enabled:
            _debug.lifecycle(
                "created",
                grants=grants.ids,
                states=sorted(set(grants.mapped("state"))),
                su=self.env.su,
            )
        grants._check_delegation()
        # refused after the delegation check: who may not give the grant at
        # all hears that, not what the grant would have claimed
        if claimed:
            _debug.logic(
                "create_refused", reason="audit_fields", fields=sorted(claimed)
            )
            raise ValidationError(
                self.env._(
                    "A grant records who gave it and why by itself: "
                    "%(fields)s cannot be set.",
                    fields=", ".join(sorted(claimed)),
                )
            )
        grants._log("grant_created")
        grants._project()
        grants._check_lasting_administrator()
        grants._schedule_boundaries()
        grants._on_grant_changed("grant_created")
        return grants

    def write(self, vals: dict[str, Any]) -> bool:
        if not _LIFECYCLE.get():
            if forbidden := set(vals) - EDITABLE_FIELDS:
                _debug.logic(
                    "write_refused",
                    grants=self.ids,
                    reason="not_editable",
                    fields=sorted(forbidden),
                )
                raise UserError(
                    self.env._(
                        "A grant's %(fields)s cannot be changed: revoke it and "
                        "grant again.",
                        fields=", ".join(sorted(forbidden)),
                    )
                )
            if ended := self.filtered(
                lambda grant: grant.state in ("expired", "revoked")
            ):
                _debug.logic("write_refused", grants=ended.ids, reason="ended")
                raise UserError(
                    self.env._("An expired or revoked grant cannot be changed.")
                )
            self._check_delegation("write")
        result = super().write(vals)
        if "company_ids" in vals:
            self._check_scope()
            self._check_delegation("write")
            self._log("grant_changed")
            self._clear_membership_caches()
            self._on_grant_changed("grant_changed")
        if not _LIFECYCLE.get() and {"date_from", "date_to"} & vals.keys():
            now = self.env.cr.now()
            with _marked(_LIFECYCLE):
                for grant in self:
                    state = grant._state_at(grant.date_from, grant.date_to, now)
                    if state != grant.state:
                        _debug.lifecycle(
                            "state_moved_by_dates",
                            grant=grant.id,
                            before=grant.state,
                            after=state,
                        )
                        grant.state = state
            self._log("grant_changed")
            self._project()
            self._check_lasting_administrator()
            self._schedule_boundaries()
            self._on_grant_changed("grant_changed")
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_by_the_superuser(self) -> None:
        if not self.env.su:
            _debug.logic("unlink_refused", grants=self.ids, reason="not_superuser")
            raise UserError(
                self.env._(
                    "A grant is part of the record of who could do what: revoke "
                    "it instead of deleting it."
                )
            )

    def unlink(self) -> bool:
        pairs = self._pairs()
        result = super().unlink()
        self._project(pairs)
        return result

    def _check_scope(self) -> None:
        user_types = self.env["res.groups"].sudo()._get_user_type_groups()
        for grant in self.sudo():
            if grant.group_id.is_privilege:
                raise ValidationError(
                    self.env._(
                        "%(group)s is a privilege: only code holds it, through "
                        "with_privilege(); it is never granted.",
                        group=grant.group_id.full_name,
                    )
                )
            if not grant.company_ids:
                continue
            if grant.group_id in user_types:
                raise ValidationError(
                    self.env._(
                        "%(group)s says what kind of user %(user)s is, in every "
                        "company: it cannot be limited to some.",
                        group=grant.group_id.full_name,
                        user=grant.user_id.name,
                    )
                )
            if outside := grant.company_ids - grant.user_id.company_ids:
                raise ValidationError(
                    self.env._(
                        "%(user)s does not work in %(companies)s: a grant cannot "
                        "be limited to a company its user is not in.",
                        user=grant.user_id.name,
                        companies=", ".join(outside.mapped("name")),
                    )
                )

    def _check_delegation(self, operation: str = "create") -> None:
        # who may give or change a grant besides the access administrators:
        # the members of the group's admin group, for someone else, within
        # their own companies, and only for groups whose implications they
        # administer too or the grantee already holds
        env = self.env
        if env.su or env.user._has_group("base.group_erp_manager"):
            _debug.logic(
                "delegation_bypassed",
                grants=self.ids,
                reason="superuser" if env.su else "access_administrator",
            )
            return
        if env.privileges and self._granted_by_privilege(operation):
            # code that keeps a membership in step with its data acts under a
            # privilege whose own rows name the group it may grant; the actor
            # granting themselves is then the data's doing, not a choice
            return
        actor = env.user
        actor_groups = set(actor._get_group_ids())
        actor_companies = set(actor._get_company_ids())
        # what each grantee holds through their other grants, read from the
        # grants rather than a cached answer that may already count these
        held_by_user: defaultdict[int, set[int]] = defaultdict(set)
        others = self.sudo().search(
            self._live_domain()
            & Domain("user_id", "in", self.sudo().user_id.ids)
            & Domain("id", "not in", self.ids)
        )
        for other in others:
            held_by_user[other.user_id.id].update(other.group_id.all_implied_ids._ids)
        for grant in self.sudo():
            group = grant.group_id
            if grant.user_id.id == actor.id:
                _debug.logic("delegation_refused", grant=grant.id, reason="self_grant")
                raise AccessError(
                    env._("You cannot grant yourself %(group)s.", group=group.full_name)
                )
            if group.admin_group_id.id not in actor_groups:
                _debug.logic(
                    "delegation_refused",
                    grant=grant.id,
                    reason="not_admin_group_member",
                    admin_group=group.admin_group_id.id,
                )
                raise AccessError(
                    env._(
                        "Only the members of %(admin)s may grant %(group)s.",
                        admin=group.admin_group_id.full_name,
                        group=group.full_name,
                    )
                )
            reach = set(grant.company_ids._ids) or set(grant.user_id._get_company_ids())
            if not reach <= actor_companies:
                _debug.logic(
                    "delegation_refused", grant=grant.id, reason="foreign_companies"
                )
                raise AccessError(
                    env._(
                        "A grant of %(group)s to %(user)s would reach companies "
                        "you do not work in: limit it to your own.",
                        user=grant.user_id.name,
                        group=group.full_name,
                    )
                )
            held = held_by_user[grant.user_id.id]
            beyond = [
                implied.full_name
                for implied in group.all_implied_ids - group
                if implied.id not in held
                and implied.admin_group_id.id not in actor_groups
            ]
            if beyond:
                _debug.logic(
                    "delegation_refused",
                    grant=grant.id,
                    reason="implied_beyond_reach",
                    implied=beyond,
                )
                raise AccessError(
                    env._(
                        "%(group)s implies %(implied)s, which you may not grant.",
                        group=group.full_name,
                        implied=", ".join(beyond),
                    )
                )

    def _granted_by_privilege(self, operation: str) -> bool:
        # every grant is one the environment's privileges allow by their own
        # rows, for this operation
        grants = self.sudo().with_context(active_test=False)
        domain = self.env["ir.access"]._privilege_domain(self._name, operation)
        return grants.filtered_domain(domain) == grants

    def _check_lasting_administrator(self) -> None:
        # the clock ends a timed grant where no constraint can refuse it: an
        # administrator must remain once every timed grant has ended, through
        # an open-ended grant or a membership no grant covers
        # an invariant of the whole database: it reads everything
        grants = self.sudo()
        env = grants.env
        system = env.ref("base.group_system", raise_if_not_found=False)
        if not (env.registry.loaded_modules and system):
            _debug.logic("lasting_administrator_skipped", reason="registry_loading")
            return
        admin_groups = system.all_implied_by_ids
        if not grants.group_id & admin_groups:
            return
        admins = env["res.users"].search(
            [("all_group_ids", "in", system.ids), ("active", "=", True)]
        )
        if not admins:
            # no administrator at all: res.users refuses that by itself
            _debug.logic("lasting_administrator_skipped", reason="no_administrator")
            return
        covering = grants.search_fetch(
            Domain("user_id", "in", admins.ids)
            & Domain("group_id", "in", admin_groups.ids)
            & Domain("state", "in", ("scheduled", "active")),
            ["user_id", "group_id", "state", "date_to"],
        )
        if any(grant.state == "active" and not grant.date_to for grant in covering):
            return
        covered = covering._pairs()
        if any(
            (admin.id, group.id) not in covered
            for admin in admins
            for group in admin.group_ids & admin_groups
        ):
            _debug.logic("lasting_administrator_kept", reason="uncovered_membership")
            return
        _debug.logic(
            "lasting_administrator_refused",
            grants=self.ids,
            admins=admins.ids,
            timed=covering.ids,
        )
        raise ValidationError(
            env._(
                "Some active user must hold %(group)s with no end date: the "
                "last administrator's access would otherwise end by itself.",
                group=system.full_name,
            )
        )

    def action_revoke(self, reason: str | None = None) -> bool:
        live = self.filtered(lambda grant: grant.state in ("scheduled", "active"))
        _debug.lifecycle(
            "revoke", grants=live.ids, skipped=(self - live).ids, reason=reason
        )
        if not live:
            return True
        live._check_delegation("write")
        with _marked(_LIFECYCLE):
            live.write(
                {
                    "state": "revoked",
                    "revoked_by_id": self.env.uid,
                    "revoked_at": self.env.cr.now(),
                    "revoke_reason": reason or False,
                }
            )
        live._log("grant_revoked", reason=reason)
        live._project()
        live._check_lasting_administrator()
        live._on_grant_changed("grant_revoked")
        return True

    @api.model
    def _grant(
        self,
        users: models.BaseModel,
        groups: models.BaseModel,
        *,
        cause: str,
        cause_ref: models.BaseModel | None = None,
        companies: models.BaseModel | None = None,
        date_to: datetime | None = None,
        reason: str | None = None,
    ) -> Self:
        # a grant of each group to each user not already holding it everywhere
        # (for a cause: through that cause, which then ends it alone)
        live = self._live_pairs(
            users,
            groups,
            unscoped=True,
            cause_model=cause_ref._name if cause_ref else None,
        )
        vals_list = [
            {
                "user_id": user.id,
                "group_id": group.id,
                "cause": cause,
                "cause_model": cause_ref._name if cause_ref else False,
                "cause_res_id": cause_ref.id if cause_ref else False,
                "company_ids": [Command.set(companies.ids)] if companies else [],
                "date_to": date_to or False,
                "reason": reason or False,
            }
            for user in users
            for group in groups
            if (user.id, group.id) not in live
        ]
        _debug.logic(
            "grant",
            cause=cause,
            users=users.ids,
            groups=groups.ids,
            new=len(vals_list),
            already_live=len(live),
        )
        return self.create(vals_list) if vals_list else self.browse()

    @api.model
    def _revoke(
        self,
        users: models.BaseModel | None,
        groups: models.BaseModel,
        *,
        cause: str | None = None,
        cause_model: str | None = None,
        reason: str | None = None,
    ) -> Self:
        # the live grants of these groups to these users (to anyone, without
        # users); with a cause, only the grants that cause made, so a
        # membership given by hand outlives the data that also implied it
        domain = self._live_domain() & Domain("group_id", "in", groups.ids)
        if users is not None:
            domain &= Domain("user_id", "in", users.ids)
        if cause:
            domain &= Domain("cause", "=", cause)
        if cause_model:
            domain &= Domain("cause_model", "=", cause_model)
        grants = self.search(domain)
        grants.action_revoke(reason)
        return grants

    def _live_pairs(
        self,
        users: models.BaseModel,
        groups: models.BaseModel,
        unscoped: bool = False,
        cause_model: str | None = None,
    ) -> set[tuple[int, int]]:
        if not users or not groups:
            return set()
        domain = (
            self._live_domain()
            & Domain("user_id", "in", users.ids)
            & Domain("group_id", "in", groups.ids)
        )
        if unscoped:
            domain &= Domain("company_ids", "=", False)
        if cause_model:
            domain &= Domain("cause_model", "=", cause_model)
        rows = self.sudo()._read_group(
            domain,
            ["user_id", "group_id"],
        )
        return {(user.id, group.id) for user, group in rows}

    @api.model
    def _membership_cause(self) -> str:
        return "module" if self.env.context.get("install_module") else "manual"

    @api.model
    def _follow_membership(
        self,
        added: Iterable[tuple[int, int]],
        removed: Iterable[tuple[int, int]],
        fresh_user_ids: Iterable[int] = (),
    ) -> None:
        # a membership written through group_ids or user_ids: an added pair is
        # granted unscoped, a removed one loses every live grant of it
        token = _FRESH_USERS.set(frozenset(fresh_user_ids))
        try:
            with _marked(_FOLLOWING):
                self._follow_membership_pairs(added, removed)
        finally:
            _FRESH_USERS.reset(token)
        # a writer clears the caches after its write; a create does not, and
        # only needs to when something asked a new user's groups before all of
        # its grants existed (an inverse granting one group of several)
        if set(fresh_user_ids) & self.env.cr.cache.get(GROUP_STATE_COMPUTED, set()):
            self._clear_membership_caches()

    def _follow_membership_pairs(
        self,
        added: Iterable[tuple[int, int]],
        removed: Iterable[tuple[int, int]],
    ) -> None:
        cause = self._membership_cause()
        added, removed = set(added), set(removed)
        if _debug.lifecycle.enabled:
            _debug.lifecycle(
                "membership_followed",
                cause=cause,
                added=sorted(added),
                removed=sorted(removed),
                fresh_users=sorted(_FRESH_USERS.get()),
            )
        by_group: defaultdict[int, list[int]] = defaultdict(list)
        for user_id, group_id in added:
            by_group[group_id].append(user_id)
        grants = self.sudo()
        users = self.env["res.users"].sudo()
        groups = self.env["res.groups"].sudo()
        for group_id, user_ids in by_group.items():
            grants._grant(users.browse(user_ids), groups.browse(group_id), cause=cause)
        if removed:
            candidates = grants.search(
                grants._live_domain()
                & Domain("user_id", "in", list({user_id for user_id, _ in removed}))
                & Domain("group_id", "in", list({group_id for _, group_id in removed}))
            )
            candidates.filtered(
                lambda grant: (grant.user_id.id, grant.group_id.id) in removed
            ).action_revoke()

    def _on_grant_changed(self, event: str) -> None:
        # called once per batch after a grant is created, changed, revoked,
        # started or expired, with the name of its ir.access.log event, or
        # grant_started for a start, which is not logged; modules that judge
        # a grant (a separation-of-duties rule) extend it
        return

    def _log(self, event: str, reason: str | None = None) -> None:
        self.env["ir.access.log"]._record(
            [
                {
                    "event": event,
                    "subject_user_id": grant.user_id.id,
                    "group_id": grant.group_id.id,
                    "grant_id": grant.id,
                    "cause": grant.cause,
                    "cause_model": grant.cause_model or False,
                    "cause_res_id": grant.cause_res_id or False,
                    "reason": reason or grant.reason or False,
                }
                for grant in self
            ]
        )

    def _schedule_boundaries(self) -> None:
        now = self.env.cr.now()
        moments = sorted(
            {
                moment
                for grant in self
                for moment in (grant.date_from, grant.date_to)
                if moment and moment > now
            }
        )
        if moments:
            cron = self.env.ref(
                "base.ir_cron_res_users_grant_boundaries", raise_if_not_found=False
            )
            _debug.lifecycle(
                "boundaries_scheduled",
                grants=self.ids,
                moments=moments,
                cron=bool(cron),
            )
            if cron:
                cron.sudo()._trigger(moments)

    @api.model
    def _cron_cross_boundaries(self) -> None:
        now = self.env.cr.now()
        grants = self.sudo().with_context(active_test=False)
        starting = grants.search(
            Domain("state", "=", "scheduled")
            & Domain("date_from", "<=", now)
            & (Domain("date_to", "=", False) | Domain("date_to", ">", now))
        )
        ending = grants.search(
            Domain("state", "in", ("scheduled", "active"))
            & Domain("date_to", "!=", False)
            & Domain("date_to", "<=", now)
        )
        _debug.lifecycle("grant_boundaries", starting=len(starting), ending=len(ending))
        # one user at a time: a boundary a constraint refuses (a scheduled
        # group disjoint from one the user keeps) stays due and is retried,
        # instead of holding back every other user's
        for user, user_grants in (starting | ending).grouped("user_id").items():
            user_starting, user_ending = user_grants & starting, user_grants & ending
            try:
                with self.env.cr.savepoint():
                    with _marked(_LIFECYCLE):
                        user_starting.write({"state": "active"})
                        user_ending.write({"state": "expired"})
                    user_ending._log("grant_expired")
                    user_grants._project()
                    if user_starting:
                        user_starting._on_grant_changed("grant_started")
                    if user_ending:
                        user_ending._on_grant_changed("grant_expired")
            except UserError as error:
                _debug.logic(
                    "boundary_refused",
                    user=user.id,
                    starting=user_starting.ids,
                    ending=user_ending.ids,
                    error=type(error).__name__,
                )
                _logger.warning(
                    "The grants %s of user %s stay due, their boundary is refused: %s",
                    user_grants.ids,
                    user.id,
                    error,
                )

    def _pairs(self) -> set[tuple[int, int]]:
        return {(grant.user_id.id, grant.group_id.id) for grant in self.sudo()}

    def _project(self, pairs: set[tuple[int, int]] | None = None) -> None:
        # group_ids holds the (user, group) pairs with an active grant, whatever
        # its scope; only the pairs these grants name are touched, so a
        # membership no grant covers yet (a database before its migration) is
        # left as it is
        if _FOLLOWING.get():
            # the membership write these grants follow has moved the pairs
            return
        pairs = self._pairs() if pairs is None else pairs
        if not pairs:
            return
        mine: defaultdict[int, set[int]] = defaultdict(set)
        for user_id, group_id in pairs:
            mine[user_id].add(group_id)
        rows = self.sudo()._read_group(
            Domain("user_id", "in", list(mine))
            & Domain("group_id", "in", list({group_id for _, group_id in pairs}))
            & Domain("state", "=", "active"),
            ["user_id", "group_id"],
        )
        active = {(user.id, group.id) for user, group in rows}
        users = self.env["res.users"].sudo().with_context(active_test=False)
        # one write per distinct change: each runs the membership constraints
        # and clears every access cache, whatever number of users it names
        by_commands: defaultdict[tuple, list[int]] = defaultdict(list)
        for user in users.browse(sorted(mine)):
            held = set(user.group_ids.ids)
            commands = tuple(
                [
                    Command.link(group_id)
                    for group_id in sorted(mine[user.id] - held)
                    if (user.id, group_id) in active
                ]
                + [
                    Command.unlink(group_id)
                    for group_id in sorted(mine[user.id] & held)
                    if (user.id, group_id) not in active
                ]
            )
            if commands:
                by_commands[commands].append(user.id)
        _debug.perf.count(
            "projected",
            users=len(mine),
            writes=len(by_commands),
            changed_users=sum(len(ids) for ids in by_commands.values()),
        )
        with _marked(_PROJECTING):
            for commands, ids in by_commands.items():
                if _debug.lifecycle.enabled:
                    _debug.lifecycle(
                        "projection_written",
                        users=ids,
                        link=[cmd[1] for cmd in commands if cmd[0] == Command.LINK],
                        unlink=[cmd[1] for cmd in commands if cmd[0] == Command.UNLINK],
                    )
                users.browse(ids).write({"group_ids": list(commands)})
        # a group_ids write clears the caches itself; a user this transaction
        # is creating has nothing cached yet
        if by_commands or not mine.keys() - _FRESH_USERS.get():
            return
        self._clear_membership_caches()

    @api.model
    def _clear_membership_caches(self) -> None:
        # what a user's groups decide: their group state, the views that bake
        # groups into their arch, and the unnamed caches keyed on the user
        # (their menus, among others). Not `stable`: ir.access rows and the
        # group hierarchy do not change with who holds a group
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.registry.clear_cache("memberships", "default", "templates")

    @api.model
    @tools.ormcache(cache="stable")
    def _grants_available(self) -> bool:
        # false only while an upgrade from before the model has not created
        # its table yet: the reflection that records the model runs with the
        # table's creation, and reads the same in memory as in PostgreSQL.
        # Once true it stays true for the registry, which is asked on every
        # cold group state
        if _GRANTS_AVAILABLE.get(id(self.pool)) is self.pool:
            return True
        available = bool(
            self.env["ir.model"]
            .sudo()
            .search_count([("model", "=", self._name)], limit=1)
        )
        if available:
            _GRANTS_AVAILABLE[id(self.pool)] = self.pool
        return available
