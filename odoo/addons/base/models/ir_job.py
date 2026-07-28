"""Framework-native background job queue (``ir.job``).

Postgres-as-broker asynchronous execution: a job is a method call — model,
method, records, arguments — persisted as an ``ir_job`` row **in the caller's
transaction** (transactional enqueue: the job and the business change commit
or vanish together).  Dedicated workers (``WorkerJob`` in prefork mode, the
``job_thread`` daemon threads in threaded mode — see ``odoo.service``) wake up
on a ``job_queue`` NOTIFY, claim work with ``FOR NO KEY UPDATE SKIP LOCKED``
and execute it in-process, each job in its own transaction.

``pending`` means *claimable this instant*, nothing weaker.  A job waiting on
its ``eta`` -- a caller's "run this tonight", or the exponential backoff of a
retry -- is ``scheduled`` until :meth:`IrJob._promote_due_jobs` moves it over.
The distinction is what keeps ``ir_job_claim_idx`` exact: while delayed jobs
shared ``pending``, they sat in that index ahead of the ready ones (they are
older, and it is ordered by ``priority, create_date``), so every claim walked
past them and Postgres eventually abandoned the index for a sequential scan.
Measured on the real table: a claim costs 0.055 ms on an idle queue, 5.5 ms
behind 50k delayed jobs and 23.6 ms behind 200k -- linear, and since claims
serialize on one advisory lock that figure *is* the database's claim
throughput.  Holding delayed jobs in their own state keeps it at 0.055 ms
however many of them are waiting.

Enqueue API (only methods decorated with :func:`odoo.api.job` are accepted)::

    records.delayed(priority=5, eta=60)._my_job_method("a", k=2)

Liveness is advisory-lock based: the executing session holds a session-level
advisory lock on the job id for the whole run; the lock vanishes the instant
the session dies, and ``_reap_dead_jobs`` requeues ``started`` rows whose lock
has become free.  Completion is atomic: ``state = 'done'`` is written inside
the job's own business transaction, so a crash can never yield "work applied
but job still pending" — only the safe inverse (work rolled back, job retried).
"""

import json
import logging
import os
import socket
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg.errors

from odoo import api, db, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import (
    RetryableJobError,
    TerminalJobError,
    UserError,
    ValidationError,
)
from odoo.libs.constants import GC_UNLINK_LIMIT, JOB_QUEUE_CHANNEL
from odoo.modules.registry import Registry
from odoo.tools import SQL

from .ir_cron import (
    BadModuleStateError,
    BadVersionError,
    IrCron,
    notify_channel,
    worker_real_time_budget,
)

_logger = logging.getLogger(__name__)

NOTIFY_PENDING_KEY = "ir.job.notify"
"""``cr.postcommit.data`` key coalescing a transaction's worker wake-ups."""

ALLOWED_CONTEXT_KEYS = ("lang", "tz", "allowed_company_ids")

DEAD_JOB_GRACE_S = 60

RETRY_BACKOFF_BASE_S = 10
RETRY_BACKOFF_MAX_S = 3600

CLAIM_MAX_ATTEMPTS = 10

DRAIN_BUDGET_RATIO = 0.4
"""Fraction of the worker's real-time limit a single drain pass may consume.

Below a half because the prefork worker pings its watchdog *before* sleeping:
``WorkerCron.sleep`` caps its select at half the watchdog timeout, so a pass
that starts after a full idle sleep only has the other half of the window left.
Unlike the cron backstop, a drain reaches this bound on any real backlog, so it
is sized for the worst case rather than the typical one.
"""

MAINTENANCE_INTERVAL_S = 30
REAP_BATCH_SIZE = 1000

DONE_RETENTION = timedelta(days=7)
FAILED_RETENTION = timedelta(days=30)

_last_maintenance: dict[str, float] = {}
"""Per-process monotonic clock of the last maintenance sweep, by database."""


class JobState(StrEnum):
    """The lifecycle of an ``ir.job`` row.

    A ``StrEnum`` so a member is interchangeable with the string the column
    holds -- comparisons against values read back from raw SQL just work --
    while the set of legal states, their labels and the state *groups* below
    have exactly one definition.  They used to be six bare module constants
    whose groupings were then respelled as literals in every query.
    """

    WAIT_DEPS = "wait_deps"
    SCHEDULED = "scheduled"
    PENDING = "pending"
    STARTED = "started"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


STATES = [
    (JobState.WAIT_DEPS, "Waiting Dependencies"),
    (JobState.SCHEDULED, "Scheduled"),
    (JobState.PENDING, "Pending"),
    (JobState.STARTED, "Started"),
    (JobState.DONE, "Done"),
    (JobState.FAILED, "Failed"),
    (JobState.CANCELLED, "Cancelled"),
]

QUEUED_STATES = (
    JobState.WAIT_DEPS,
    JobState.SCHEDULED,
    JobState.PENDING,
    JobState.STARTED,
)
"""States in which a job still owes work, and so holds its ``identity_key``."""

CANCELLABLE_STATES = (JobState.WAIT_DEPS, JobState.SCHEDULED, JobState.PENDING)
"""States a job can still be cancelled from -- everything not yet running."""

RUNNABLE_STATES = (JobState.SCHEDULED, JobState.PENDING)
"""States "Run Manually" accepts: a job whose only obstacle is its clock."""

_DUE_STATE_SQL = SQL(
    "CASE WHEN eta IS NULL OR eta <= (now() AT TIME ZONE 'UTC')"
    " THEN 'pending' ELSE 'scheduled' END"
)
"""Which queued state a job belongs in *right now*, given its ``eta``.

``pending`` means claimable this instant; a job waiting on its clock is
``scheduled``.  Every writer that puts a job back in the queue -- enqueue, retry
backoff, dependency release, the repair sweep -- has to make that distinction,
and each one spelling it out separately is how they drift.
"""

DEAD_DEPENDENCY_STATES = (JobState.FAILED, JobState.CANCELLED)
"""Dependency states that cascade-cancel whatever is waiting on them."""


def _states_sql(states: tuple[JobState, ...]) -> str:
    """Render *states* as a SQL ``IN`` list.

    Returns plain text, not :class:`SQL`, because two of the call sites are
    index predicates built at class-definition time -- and the ``ON CONFLICT``
    arbiter has to spell the same predicate as the partial index it targets, so
    both must come from here or they drift apart silently.  The values are
    enum members this module defines; nothing external reaches the string.
    """
    return "(" + ", ".join(f"'{state.value}'" for state in states) + ")"


QUEUED_STATES_SQL = _states_sql(QUEUED_STATES)


def _format_exception(exc: BaseException) -> str:
    """Render *exc* and its traceback.

    Formatted from the exception object rather than from ``format_exc()``,
    which reads the *caller's* ``except`` block: every caller outside one --
    a test, a future direct call -- silently stored ``"NoneType: None"`` as
    the job's traceback, and the coupling was invisible at the call site.
    """
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _job_config_of(model_cls: type, method_name: str) -> dict | None:
    """The :func:`odoo.api.job` configuration of *method_name*, or ``None``.

    Resolved along the MRO rather than off the most-derived function, because
    ``@api.job`` marks a *function* while Odoo composes models out of one class
    per extending module.  A module doing the ordinary thing::

        class ResPartner(models.Model):
            _inherit = "res.partner"

            def _sync_to_wms(self, batch_size=100):
                ...
                return super()._sync_to_wms(batch_size)

    puts an undecorated function first in the MRO, and the marker vanished:
    every enqueue of that method started raising, and rows already queued for it
    refused to run.  Nothing said so at import time -- the trap sprang in
    production, on a method the module never meant to change the nature of.

    Walking the chain means "declared a job anywhere in its own inheritance" is
    what counts, which is the property the decorator was always describing.  It
    does not widen the security contract :meth:`IrJob._run_claimed` rests on: a
    name that no class in the chain decorated still resolves to ``None``.
    """
    for klass in model_cls.__mro__:
        func = klass.__dict__.get(method_name)
        if func is not None and (job_config := getattr(func, "_job_config", None)):
            return job_config
    return None


def _advisory_key_sql(job_id: int) -> SQL:
    """Bigint advisory-lock key for a job id (single source for claim/reaper)."""
    return SQL("hashtextextended('ir_job:' || %s::text, 0)", job_id)


@contextmanager
def _job_session_lock(cr, job_id: int, *, blocking: bool = True) -> Iterator[bool]:
    """Hold the session advisory lock naming *job_id* for the block.

    Yields whether the lock was taken -- always ``True`` when *blocking*, the
    ``pg_try_advisory_lock`` result otherwise -- and releases it on the way out
    only if it was.  The lock is what proves a worker is alive
    (:meth:`IrJob._reap_dead_jobs`), so the acquire/release pair must not drift
    between its two call sites: releasing a lock never taken would decrement
    somebody else's hold, and leaking one would make a finished job look
    forever running.  It is session-scoped, so it deliberately survives every
    ``commit`` made inside the block -- the claim loop's, and any the job's own
    code performs.

    The release tolerates a failure: leaving the block through a database error
    leaves the transaction aborted, and an unlock that raised there would mask
    the exception that caused it.  Nothing leaks, because the pool runs
    ``pg_advisory_unlock_all()`` when the connection goes back (see
    ``odoo.db.lifecycle``), and a lock still held within the same session is
    re-entrant rather than self-blocking.
    """
    if blocking:
        cr.execute(SQL("SELECT pg_advisory_lock(%s)", _advisory_key_sql(job_id)))
        acquired = True
    else:
        cr.execute(SQL("SELECT pg_try_advisory_lock(%s)", _advisory_key_sql(job_id)))
        acquired = cr.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            try:
                cr.execute(
                    SQL("SELECT pg_advisory_unlock(%s)", _advisory_key_sql(job_id))
                )
            except psycopg.Error:
                _logger.warning(
                    "Job %s: could not release its liveness lock, "
                    "leaving it to the connection pool",
                    job_id,
                )


class DelayedProxy:
    """Proxy returned by ``records.delayed()``.

    Any method call on it enqueues an ``ir.job`` instead of executing;
    call-site keyword overrides win over the ``@api.job`` defaults.
    """

    __slots__ = ("_props", "_records")

    def __init__(self, records: models.BaseModel, props: dict[str, Any]) -> None:
        self._records = records
        self._props = props

    def __getattr__(self, name: str):
        records, props = self._records, self._props

        def enqueue(*args: Any, **kwargs: Any) -> models.BaseModel:
            return records.env["ir.job"]._enqueue(
                records, name, args=args, kwargs=kwargs, **props
            )

        return enqueue


class Base(models.AbstractModel):
    _inherit = "base"

    def delayed(
        self,
        *,
        priority: int | None = None,
        eta: Any = None,
        channel: str | None = None,
        max_retries: int | None = None,
        identity_key: str | None = None,
        after: models.BaseModel | None = None,
        description: str | None = None,
    ) -> DelayedProxy:
        """Return a proxy that enqueues the next method call as an ``ir.job``.

        ``records.delayed()._method(args)`` persists the call in the current
        transaction and returns the job record; workers execute it after
        commit.  The method must be decorated with :func:`odoo.api.job`.

        :param priority: lower runs first (default: the decorator's)
        :param eta: earliest execution time — seconds from now (int/float)
            or a naive-UTC datetime (default: run ASAP)
        :param channel: ``ir.job.channel`` name (default: the decorator's)
        :param max_retries: retry budget (default: the decorator's)
        :param identity_key: dedup handle — while a job with the same key is
            queued (waiting, pending or started), re-enqueueing returns it
            instead of inserting
        :param after: ``ir.job`` recordset this job depends on — it stays in
            ``wait_deps`` until every dependency is ``done``, and is cancelled
            if any of them fails or is cancelled.  Chain jobs by passing the
            previous ``delayed()`` result; fan-in by passing a union.
        :param description: human-readable label shown in the job list
            instead of the technical ``model.method`` name
        """
        return DelayedProxy(
            self,
            {
                "priority": priority,
                "eta": eta,
                "channel": channel,
                "max_retries": max_retries,
                "identity_key": identity_key,
                "after": after,
                "description": description,
            },
        )


class IrJobChannel(models.Model):
    """Capacity class for background jobs.

    ``capacity`` bounds how many jobs of the channel run concurrently across
    the whole cluster (enforced by the claim query).  A channel referenced by
    jobs but absent from this table has an implicit capacity of 1.

    Archiving a channel *pauses* it: its jobs stay ``pending`` and claimable
    again the moment it is unarchived.  It deliberately does not fall back to
    the implicit capacity, which would silently turn "switch this channel off"
    into "run it one at a time" -- the opposite of the intent, and invisible
    because an archived row also drops out of the default list view.
    """

    _name = "ir.job.channel"
    _description = "Background Job Channel"
    _order = "name"
    _allow_sudo_commands = False

    name = fields.Char(required=True)
    capacity = fields.Integer(
        default=1,
        required=True,
        help="Maximum number of jobs of this channel running concurrently, "
        "across all job workers.",
    )
    active = fields.Boolean(
        default=True,
        help="Archived channels are paused: none of their jobs is claimed "
        "until the channel is restored.",
    )
    running_count = fields.Integer(
        string="Running",
        compute="_compute_running_count",
        help="Jobs of this channel currently executing, across all workers.",
    )
    pending_count = fields.Integer(
        string="Pending",
        compute="_compute_running_count",
        help="Jobs of this channel waiting to be claimed.",
    )

    _name_uniq = models.UniqueIndex("(name)", "Channel names must be unique.")
    _check_capacity = models.Constraint(
        "CHECK(capacity > 0)",
        "The channel capacity must be strictly positive.",
    )

    @api.depends("name")
    def _compute_running_count(self) -> None:
        """Count this channel's in-flight and queued jobs.

        Depends only on ``name`` — the ``ir_job`` rows it counts are not a
        field path the ORM can trigger on, so the pair is a read-time snapshot
        (as an operational gauge should be) rather than a maintained value.
        """
        counts = {
            (channel, state): count
            for channel, state, count in self.env["ir.job"]
            .sudo()
            ._read_group(
                [
                    ("channel", "in", self.mapped("name")),
                    ("state", "in", (JobState.STARTED, JobState.PENDING)),
                ],
                ["channel", "state"],
                ["__count"],
            )
        }
        for record in self:
            record.running_count = counts.get((record.name, JobState.STARTED), 0)
            record.pending_count = counts.get((record.name, JobState.PENDING), 0)


class IrJob(models.Model):
    """A persisted method call, executed asynchronously by the job workers."""

    _name = "ir.job"
    _description = "Background Job"
    _order = "priority, create_date, id"
    _allow_sudo_commands = False

    name = fields.Char(
        readonly=True,
        help="Optional human-readable label shown instead of "
        "the technical model.method display name.",
    )
    uuid = fields.Char(readonly=True, index=True)
    channel = fields.Char(required=True, default="root", readonly=True)
    state = fields.Selection(
        STATES, required=True, default=JobState.PENDING, index=True
    )
    priority = fields.Integer(default=10, readonly=True)
    eta = fields.Datetime(
        string="Execute After", help="Earliest execution time (empty: ASAP)."
    )
    identity_key = fields.Char(readonly=True)

    model_name = fields.Char(required=True, readonly=True)
    method_name = fields.Char(required=True, readonly=True)
    record_ids = fields.Json(readonly=True)
    args = fields.Json(readonly=True)
    kwargs = fields.Json(readonly=True)
    user_id = fields.Many2one("res.users", required=True, readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    context = fields.Json(readonly=True)

    retry = fields.Integer(default=0, readonly=True)
    max_retries = fields.Integer(default=5, readonly=True)
    exc_name = fields.Char(readonly=True)
    exc_message = fields.Char(readonly=True)
    exc_info = fields.Text(readonly=True)

    started_at = fields.Datetime(readonly=True)
    done_at = fields.Datetime(readonly=True)
    worker_ident = fields.Char(readonly=True)

    depends_on_ids = fields.Many2many(
        "ir.job",
        relation="ir_job_dependency",
        column1="job_id",
        column2="depends_on_id",
        string="Depends On",
        readonly=True,
        help="This job stays in 'Waiting Dependencies' until every listed "
        "job is done; it is cancelled if any of them fails.",
    )
    dependent_ids = fields.Many2many(
        "ir.job",
        relation="ir_job_dependency",
        column1="depends_on_id",
        column2="job_id",
        string="Dependents",
        readonly=True,
    )

    _claim_idx = models.Index("(priority, create_date, id) WHERE state = 'pending'")
    _due_idx = models.Index("(eta) WHERE state = 'scheduled'")
    _capacity_idx = models.Index("(channel) WHERE state = 'started'")
    _retention_idx = models.Index(
        "(done_at) WHERE state IN ('done', 'failed', 'cancelled')"
    )
    _identity_uniq = models.UniqueIndex(
        f"(identity_key) WHERE state IN {QUEUED_STATES_SQL}"
        " AND identity_key IS NOT NULL",
        "A job with the same identity key is already queued.",
    )

    @api.constrains("depends_on_ids", "dependent_ids")
    def _check_dependency_cycle(self) -> None:
        """Refuse dependency loops, which nothing downstream can break.

        A cycle leaves every job on it in ``wait_deps`` forever:
        ``_resolve_dependencies`` only promotes a job once all its dependencies
        are ``done``, and ``_gc_jobs`` only prunes terminal states, so the rows
        are never run, never cancelled and never collected.

        Both sides of the relation are watched: ``dependent_ids`` writes the
        same ``ir_job_dependency`` rows from the other end and would otherwise
        close a loop without triggering the check.  ``after=`` needs no guard --
        a new job only ever depends on already-inserted rows -- and its raw
        ``INSERT`` would not fire a constraint anyway.
        """
        if self._has_cycle("depends_on_ids"):
            raise ValidationError(self.env._("Job dependencies cannot form a cycle."))

    @api.job(max_retries=0)
    def _job_ping(self, message: str = "") -> None:
        """Operational smoke test: verify job workers pick up and run jobs.

        ``env["ir.job"].delayed()._job_ping("hi")`` from a shell, then check
        the log (and the job row turning ``done``) to confirm the pipeline —
        enqueue, NOTIFY, claim, execute — works on a deployment.
        """
        _logger.info("ir.job ping: %s", message or "pong")

    @api.model
    def _enqueue(
        self,
        records: models.BaseModel,
        method_name: str,
        *,
        args: tuple = (),
        kwargs: dict | None = None,
        priority: int | None = None,
        eta: Any = None,
        channel: str | None = None,
        max_retries: int | None = None,
        identity_key: str | None = None,
        after: models.BaseModel | None = None,
        description: str | None = None,
    ) -> models.BaseModel:
        """Persist a job row for ``records.method_name(*args, **kwargs)``.

        Raw ``INSERT ... ON CONFLICT DO NOTHING`` (not ``create()``): the
        partial unique index arbitrates ``identity_key`` dedup against rows a
        search-then-create would miss, namely those this transaction has not
        flushed.  It does *not* make the dedup race-free across transactions:
        cursors run at ``REPEATABLE READ``, where a conflict with a row
        committed after this snapshot raises ``SerializationFailure`` rather
        than skipping the insert, and ``retrying`` replays the request.  So the
        ``DO NOTHING`` branch below only ever fires for an in-snapshot row.
        Called from ``delayed()`` only — it is not an RPC surface, and access
        control is the ``@api.job`` marker check plus the model ACL on
        ``ir.job`` itself.

        With ``after``, the job starts in ``wait_deps`` unless every
        dependency is already done.  The dependency-state read is not locked
        against a dependency finishing concurrently — the repair sweep in
        ``_process_jobs`` re-resolves stuck jobs on every worker pass, so a
        race delays the job by at most one pass instead of losing it.
        On an ``identity_key`` dedup hit the existing job is returned as-is:
        no new dependencies are attached.

        Unsaved records are refused: ``records.ids`` drops ``NewId`` entries, so
        a non-empty recordset that has not been flushed would persist
        ``record_ids = []`` and the job would later run against nothing, doing
        no work and reporting success.

        Every timestamp here comes from the database, never from the app host's
        clock, but from two different database clocks -- and which one is not
        interchangeable:

        * ``create_date``/``write_date`` use ``cr.now()`` (``now()``, the
          *transaction* clock), because that is what the ORM stamps every other
          row in the database with;
        * the ``eta`` an offset resolves to, and the ``pending``-vs-
          ``scheduled`` decision, use :meth:`_clock_now`
          (``clock_timestamp()``, the *statement* clock).

        Reading the app host's clock let the writer and the readers disagree
        whenever that host and the database differ: an ``eta`` a few seconds out
        landed ``pending`` yet unclaimable, sitting in ``ir_job_claim_idx`` --
        the pollution the ``scheduled`` state exists to prevent -- and reported
        as ready by every gauge.  ``IrCron._now`` avoids the same trap the same
        way.

        Using the *transaction* clock for the ``eta`` would trade that for a
        second bug, because ``now()`` is pinned at ``BEGIN``: measured, a
        transaction open for six seconds resolved ``eta=3`` to three seconds in
        the *past*, so the delay the caller asked for silently vanished.  The
        readers compare against ``now()`` in their own short transactions, which
        is real time to within a millisecond, so ``clock_timestamp()`` is the
        writer-side clock that pairs with them.
        """
        job_config = _job_config_of(type(records), method_name)
        if job_config is None:
            raise UserError(
                self.env._(
                    "Method %(model)s.%(method)s cannot be enqueued: it is not "
                    "declared with @api.job.",
                    model=records._name,
                    method=method_name,
                )
            )
        if len(records) != len(records.ids):
            raise UserError(
                self.env._(
                    "Cannot enqueue %(model)s.%(method)s on unsaved records: "
                    "the job would run against no record at all.",
                    model=records._name,
                    method=method_name,
                )
            )
        try:
            args_json = json.dumps(list(args))
            kwargs_json = json.dumps(dict(kwargs or {}))
        except (TypeError, ValueError) as exc:
            # ValueError too: a self-referential argument raises "Circular
            # reference detected", not TypeError, and escaped as a raw traceback
            raise UserError(
                self.env._(
                    "Job arguments for %(model)s.%(method)s must be "
                    "JSON-serializable: %(error)s",
                    model=records._name,
                    method=method_name,
                    error=exc,
                )
            ) from exc

        env = self.env
        now = env.cr.now().replace(microsecond=0)
        state = JobState.PENDING
        if eta is not None:
            clock_now = self._clock_now()
            if isinstance(eta, (int, float)):
                eta = clock_now.replace(microsecond=0) + timedelta(seconds=eta)
            if eta and eta > clock_now:
                state = JobState.SCHEDULED
        dep_ids: list[int] = []
        if after:
            if after._name != self._name:
                raise UserError(self.env._("Job dependencies must be ir.job records."))
            env.cr.execute(
                SQL(
                    "SELECT id, state FROM ir_job WHERE id IN %s",
                    tuple(after.ids),
                )
            )
            dep_rows = env.cr.fetchall()
            dep_ids = [row[0] for row in dep_rows]
            dep_states = {row[1] for row in dep_rows}
            if dep_states & set(DEAD_DEPENDENCY_STATES):
                raise UserError(
                    self.env._(
                        "Cannot enqueue after a failed or cancelled job; "
                        "requeue the dependency first."
                    )
                )
            if dep_states - {JobState.DONE}:
                state = JobState.WAIT_DEPS

        context = {
            key: env.context[key] for key in ALLOWED_CONTEXT_KEYS if key in env.context
        }
        env.cr.execute(
            SQL(
                f"""
                INSERT INTO ir_job (
                    name, uuid, channel, state, priority, eta, identity_key,
                    model_name, method_name, record_ids, args, kwargs,
                    user_id, company_id, context, retry, max_retries,
                    create_uid, create_date, write_uid, write_date
                ) VALUES (
                    %s, gen_random_uuid()::varchar, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s::jsonb, 0, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (identity_key)
                    WHERE state IN {QUEUED_STATES_SQL}
                    AND identity_key IS NOT NULL
                    DO NOTHING
                RETURNING id
                """,
                description,
                channel or job_config["channel"],
                state,
                priority if priority is not None else job_config["priority"],
                eta or None,
                identity_key,
                records._name,
                method_name,
                json.dumps(records.ids),
                args_json,
                kwargs_json,
                env.uid,
                env.company.id,
                json.dumps(context),
                max_retries if max_retries is not None else job_config["max_retries"],
                env.uid,
                now,
                env.uid,
                now,
            )
        )
        row = env.cr.fetchone()
        if row is None:
            env.cr.execute(
                SQL(
                    "SELECT id FROM ir_job WHERE identity_key = %s"
                    f" AND state IN {QUEUED_STATES_SQL}"
                    " ORDER BY id DESC LIMIT 1",
                    identity_key,
                )
            )
            row = env.cr.fetchone()
            if dep_ids:
                _logger.warning(
                    "ir.job %s.%s deduplicated on identity key %r: the job it "
                    "was chained after (%s) is NOT a dependency of the "
                    "existing job %s, which may therefore run first",
                    records._name,
                    method_name,
                    identity_key,
                    dep_ids,
                    row[0] if row else None,
                )
        elif dep_ids:
            env.cr.execute(
                SQL(
                    "INSERT INTO ir_job_dependency (job_id, depends_on_id)"
                    " SELECT %s, dep FROM unnest(%s::int[]) AS dep",
                    row[0],
                    dep_ids,
                )
            )
        if state == JobState.PENDING:
            self._notify_after_commit(env.cr)
        return self.browse(row[0])

    @api.model
    def _clock_now(self) -> datetime:
        """Real naive-UTC time as the *database* reads it right now.

        ``cr.now()`` cannot serve here: it is ``now()``, pinned at ``BEGIN``, so
        inside a long transaction it lags real time by that transaction's age --
        enough to resolve a relative ``eta`` into the past.  Every consumer of
        this value is deciding whether a moment has already arrived, which is a
        question about the wall clock, not about this transaction.
        """
        self.env.cr.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')")
        return self.env.cr.fetchone()[0]

    @staticmethod
    def _notify_after_commit(cr) -> None:
        """Queue exactly one worker wake-up for the whole transaction.

        ``postcommit`` is an append-only queue, so registering the wake-up per
        enqueue made a transaction that queued N jobs pay N round-trips to the
        ``postgres`` database *after* commit -- measured at 1.4 s for 500 jobs,
        all of it latency the enqueuing request cannot overlap with anything.
        One NOTIFY wakes every worker, so the extra ones bought nothing.

        ``postcommit.data`` is the sentinel's home because it is cleared with
        the callback queue itself, on commit *and* on rollback, so the flag
        cannot leak into the next transaction on the same cursor.
        """
        if cr.postcommit.data.get(NOTIFY_PENDING_KEY):
            return
        cr.postcommit.data[NOTIFY_PENDING_KEY] = True
        db_name = cr.dbname
        cr.postcommit.add(lambda: IrJob._notify_workers(db_name))

    @staticmethod
    def _notify_workers(db_name: str) -> None:
        """NOTIFY the job workers of ``db_name`` (they LISTEN on 'postgres')."""
        notify_channel(JOB_QUEUE_CHANNEL, db_name)

    @staticmethod
    def _process_jobs(db_name: str) -> None:
        """Claim and execute the ready jobs of this database.

        Entry point for ``WorkerJob.process_work`` and the threaded server's
        ``job_thread`` — the ``ir.job`` counterpart of
        ``IrCron._process_jobs``, sharing its guard structure: pre-flight
        checks run on a raw cursor without loading the registry (a
        wrong-version or mid-upgrade database must not be loaded at all).

        The drain is bounded by :meth:`_drain_deadline` rather than by the
        queue: both servers measure a worker against ``limit_time_real_cron``
        over the *whole* call (the prefork master pings its watchdog once per
        ``process_work``, the threaded server stamps ``thread.start_time`` once
        per database), so an unbounded drain of a large backlog guaranteed a
        SIGKILL mid-job — which then reaped and retried that job, burning its
        budget one watchdog period at a time.  Returning at the deadline lets
        the worker loop ping, re-check its limits and come straight back.
        """
        previous_dbname = getattr(threading.current_thread(), "dbname", None)
        try:
            db_conn = db.db_connect(db_name)
            threading.current_thread().dbname = db_name
            with db_conn.cursor() as pre_cr:
                IrCron._check_version(pre_cr)
                if IrCron._modules_are_changing(pre_cr):
                    _logger.debug(
                        "Skipping database %s because of modules to"
                        " install/upgrade/remove.",
                        db_name,
                    )
                    return
            IrJob._run_maintenance(db_conn)
            IrJob._run_promotion(db_conn)
            with db_conn.cursor() as pre_cr:
                pre_cr.execute(
                    "SELECT EXISTS (SELECT 1 FROM ir_job WHERE state = 'pending')"
                )
                if not pre_cr.fetchone()[0]:
                    return
            IrJob._claim_and_run_loop(db_name, deadline=IrJob._drain_deadline())
        except BadVersionError:
            _logger.warning(
                "Skipping database %s as its base version is not current.", db_name
            )
        except BadModuleStateError:
            _logger.warning(
                "Skipping database %s because of modules to install/upgrade/remove.",
                db_name,
            )
        except psycopg.errors.UndefinedTable:
            _logger.debug("No ir_job table on database %s.", db_name)
        except db.PoolError:
            _logger.info("Skipping database %s: could not connect.", db_name)
        except Exception:
            _logger.exception("Unexpected exception in job queue for %s:", db_name)
        finally:
            if previous_dbname is None:
                if hasattr(threading.current_thread(), "dbname"):
                    del threading.current_thread().dbname
            else:
                threading.current_thread().dbname = previous_dbname

    @staticmethod
    def _drain_deadline() -> float | None:
        """Monotonic instant at which a drain pass must hand back control.

        Derived from :func:`worker_real_time_budget`, the same option the
        servers police workers with.  The margin leaves room for the job that is
        running when the deadline falls due, which is not interrupted — a
        *single* job longer than the budget is still killed by the watchdog,
        which no bound here can prevent.
        """
        budget = worker_real_time_budget()
        return time.monotonic() + budget * DRAIN_BUDGET_RATIO if budget else None

    @staticmethod
    def _promote_due_jobs(cr) -> int:
        """Move ``scheduled`` jobs whose ``eta`` has arrived into ``pending``.

        The counterpart of holding delayed work out of ``pending``: something
        has to put it back.  Driven by ``ir_job_due_idx``, so on an idle queue
        it matches nothing and touches no heap page.

        Takes a cursor, like :meth:`_reap_dead_jobs` and
        :meth:`_resolve_dependencies`, so the whole queue state machine stays
        exercisable inside a single test transaction; :meth:`_run_promotion`
        is the wrapper that gives it a transaction of its own in a worker.
        """
        cr.execute(
            "UPDATE ir_job SET state = 'pending',"
            " write_date = (now() AT TIME ZONE 'UTC')"
            " WHERE state = 'scheduled'"
            " AND (eta IS NULL OR eta <= (now() AT TIME ZONE 'UTC'))"
        )
        if cr.rowcount:
            _logger.debug("Promoted %s scheduled job(s) now due", cr.rowcount)
        return cr.rowcount

    @staticmethod
    def _run_promotion(db_conn) -> int:
        """Run :meth:`_promote_due_jobs` once, on a transaction of its own.

        Every pass, *unthrottled*: this is what bounds a delayed job's latency,
        since nothing NOTIFYs the queue when a clock runs out and an ``eta`` is
        only noticed when a worker looks.  Deliberately not folded into
        :meth:`_run_maintenance`, whose 30 s throttle covers two expensive
        database-wide repairs and would charge that delay to every scheduled
        job.

        Elected and transaction-scoped for the same reason the repair sweep is,
        and with the lock as the transaction's first statement for the same
        reason: concurrent promoters of the same rows would have all but one
        fail with ``40001`` on a ``REPEATABLE READ`` cursor.  Whoever holds the
        lock is already doing this pass's work, so skipping is free.
        """
        with db_conn.cursor() as cr:
            cr.execute(
                "SELECT pg_try_advisory_xact_lock("
                "hashtextextended('ir_job_promote', 0))"
            )
            if not cr.fetchone()[0]:
                return 0
            promoted = IrJob._promote_due_jobs(cr)
            cr.commit()
        return promoted

    @staticmethod
    def _run_maintenance(db_conn) -> None:
        """Reap dead jobs and repair dependency states, at most one at a time.

        Both sweeps are database-wide repairs whose result does not depend on
        which worker runs them, yet every worker ran both on every pass: their
        cost was multiplied by the worker count for no added effect (measured
        at 55-130 ms per pass on a 50k-row queue, on the critical path of every
        NOTIFY).  A try-lock elects a single sweeper and the
        per-process clock throttles it, so a busy queue spends its passes
        claiming work instead of re-deriving the same repairs.

        The throttle is advanced even when the lock is not obtained: another
        worker is sweeping *right now*, which is exactly what this pass would
        have done.

        The sweep opens its own transaction instead of borrowing the
        pre-flight's.  Both sweeps ``UPDATE`` rows that a concurrently
        committing worker writes too -- ``_release_dependents`` promotes
        exactly the ``wait_deps`` rows ``_resolve_dependencies`` promotes -- and
        on a ``REPEATABLE READ`` cursor whose snapshot was already pinned by the
        version and module-state reads, such an ``UPDATE`` raises ``40001``
        instead of quietly matching no row.  That escaped into
        ``_process_jobs``'s catch-all, so losing one race cost the worker its
        entire pass: the drain never ran and ready jobs waited for the next
        NOTIFY.  Electing the sweeper is now the transaction's *first*
        statement, which pins a fresh snapshot -- the discipline
        :meth:`_claim_next` documents -- and a race lost anyway costs only this
        sweep, which the next pass repeats.
        """
        now = time.monotonic()
        if (
            now - _last_maintenance.get(db_conn.dbname, float("-inf"))
            < MAINTENANCE_INTERVAL_S
        ):
            return
        _last_maintenance[db_conn.dbname] = now
        with db_conn.cursor() as cr:
            cr.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended('ir_job_gc', 0))"
            )
            if not cr.fetchone()[0]:
                return
            try:
                IrJob._reap_dead_jobs(cr)
                IrJob._resolve_dependencies(cr)
                cr.commit()
            except psycopg.errors.SerializationFailure:
                cr.rollback()
                _logger.info(
                    "Job maintenance sweep of %s lost a race with a worker;"
                    " the next sweep repeats it",
                    db_conn.dbname,
                )

    @staticmethod
    def _claim_and_run_loop(
        db_name: str,
        *,
        channels: list[str] | None = None,
        deadline: float | None = None,
    ) -> bool:
        """Drain ready jobs: claim → lock → commit → execute → finalize.

        Returns whether the drain stopped on its *deadline* — that is, whether
        ready work may remain.  It notifies the workers on the way out so the
        remainder is picked up immediately rather than at the next poll.

        Registry and cache invalidations are published (and, on failure, rolled
        back) around every job, exactly as ``IrCron._callback`` does for cron
        actions.  Without it a job that changed the registry — a new field, a
        view, a record rule — left every *other* process serving a stale
        registry indefinitely, and left *this* long-lived worker process with
        an in-memory registry built from writes its own rollback had undone.

        Signalling is also checked per job rather than once per pass: a drain
        lasts as long as its time budget, and a registry reloaded by another
        process halfway through it would otherwise be picked up only by the
        next pass.  The reload swaps the registry object, so the cursor's
        transaction — which is what ``api.Environment`` resolves model classes
        from — has to be re-pointed at it.
        """
        registry = Registry(db_name).check_signaling()
        worker_ident = f"{socket.gethostname()}:{os.getpid()}"
        with registry.cursor() as cr:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    _logger.info(
                        "Job drain of %s yielded on its time budget; notifying",
                        db_name,
                    )
                    IrJob._notify_workers(db_name)
                    return True
                job = IrJob._claim_next(cr, worker_ident, channels)
                if job is None:
                    cr.rollback()
                    return False
                if (reloaded := registry.check_signaling()) is not registry:
                    registry = reloaded
                    cr.transaction.reset()
                with _job_session_lock(cr, job["id"]):
                    cr.commit()
                    try:
                        registry[IrJob._name]._run_claimed(cr, job)
                        cr.commit()
                        registry.signal_changes()
                    except Exception as exc:
                        registry.reset_changes()
                        cr.rollback()
                        if not isinstance(exc, RetryableJobError):
                            _logger.exception(
                                "Job %s (%s.%s) failed",
                                job["id"],
                                job["model_name"],
                                job["method_name"],
                            )
                        registry[IrJob._name]._record_failure(cr, job, exc)
                        cr.commit()

    @staticmethod
    def _claim_next(
        cr, worker_ident: str, channels: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Atomically claim the next ready job, or return ``None``.

        :param channels: restrict the claim to these channels (default: any).
            A worker pool can then be dedicated to a channel -- and a caller
            that must not disturb the rest of the queue, such as a test, can
            confine itself to its own jobs.  Without it every claim is
            database-wide, so a caller sharing the database with a live queue
            claims and commits somebody else's work.

        The ``eta`` test is kept even though ``pending`` now means "claimable
        this instant" and :meth:`_promote_due_jobs` owns the transition.  It
        costs nothing -- the partial index holds only ready rows, so the filter
        passes on all of them -- and it keeps the claim correct if a future
        ``eta`` is written straight onto a ``pending`` row, which the form view
        allows.  The index is what the state buys; the predicate is what keeps
        the invariant from being load-bearing.

        The per-database advisory xact-lock serializes concurrent claims:
        ``SKIP LOCKED`` alone cannot prevent two workers from both observing
        a channel below capacity and over-admitting.  A channel with no
        ``ir_job_channel`` row has an implicit capacity of 1.

        An archived (``active = False``) channel is paused rather than reset to
        the implicit capacity of 1: see :class:`IrJobChannel`.

        Saturated channels are collected once, in the ``saturated`` CTE, rather
        than by re-counting each candidate row's channel: as a correlated
        subquery the capacity test ran per row scanned, so a backlog queued
        behind a channel at capacity was re-counted from scratch on every
        claim.  Measured on a saturated channel with 50k pending jobs, one
        claim executed both subplans 50 001 times for 84 ms and 200k buffer
        hits; since claims are serialized on the advisory lock, that latency is
        the whole database's claim throughput.  With the CTE the same claim
        takes 12 ms, and the counting scan uses ``ir_job_capacity_idx``.
        Both forms read one snapshot, so the capacity decision is unchanged.

        Acquiring that lock is also what makes the attempt racy, so each try
        runs on a fresh snapshot.  Cursors are ``REPEATABLE READ`` and the
        ``pg_advisory_xact_lock`` call is the transaction's first statement, so
        it pins the snapshot: a claimer that *waits* for the lock resumes
        holding a snapshot older than the winner's commit, and its ``UPDATE`` of
        the row the winner just took fails with ``40001``.  Measured at eight
        concurrent claimers, that was roughly seven failures per successful
        claim, each one escaping ``_claim_and_run_loop`` and ending the worker
        pass.

        The ``40001`` is a safety net, not the bug: a stale snapshot also
        undercounts the channel's ``started`` rows, and the serialization
        failure is what stops the claim from over-admitting on that stale count
        (the stale claimer always collides with the winner's row first, because
        both order candidates the same way).  Retrying therefore only restores
        liveness -- it must roll back first, which is what refreshes the
        snapshot so the retry counts capacity correctly.  Nothing of the
        caller's is pending at this point: the loop commits between jobs.
        """
        for _attempt in range(CLAIM_MAX_ATTEMPTS):
            try:
                cr.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended('ir_job_claim', 0))"
                )
                cr.execute(
                    SQL(
                        """
                        UPDATE ir_job
                        SET state = 'started',
                            started_at = (now() AT TIME ZONE 'UTC'),
                            worker_ident = %s,
                            write_date = (now() AT TIME ZONE 'UTC')
                        WHERE id = (
                            WITH saturated AS (
                                SELECT b.channel
                                FROM ir_job b
                                WHERE b.state = 'started'
                                GROUP BY b.channel
                                HAVING count(*) >= COALESCE(
                                    (SELECT c.capacity FROM ir_job_channel c
                                     WHERE c.name = b.channel AND c.active), 1)
                            ), paused AS (
                                SELECT c.name AS channel
                                FROM ir_job_channel c
                                WHERE NOT c.active
                            )
                            SELECT j.id
                            FROM ir_job j
                            WHERE j.state = 'pending'
                              AND (j.eta IS NULL
                                   OR j.eta <= (now() AT TIME ZONE 'UTC'))
                              %s
                              AND j.channel NOT IN (
                                  SELECT channel FROM saturated
                                  UNION ALL SELECT channel FROM paused)
                            ORDER BY j.priority, j.create_date, j.id
                            LIMIT 1
                            FOR NO KEY UPDATE SKIP LOCKED
                        )
                        RETURNING id, uuid, channel, priority, model_name,
                                  method_name, record_ids, args, kwargs,
                                  user_id, company_id, context, retry,
                                  max_retries
                        """,
                        worker_ident,
                        (
                            SQL("AND j.channel = ANY(%s)", list(channels))
                            if channels is not None
                            else SQL()
                        ),
                    )
                )
            except psycopg.errors.SerializationFailure:
                cr.rollback()
                continue
            row = cr.fetchone()
            if row is None:
                return None
            return dict(zip([d.name for d in cr.description], row, strict=True))
        _logger.warning(
            "job claim gave up after %s serialization failures", CLAIM_MAX_ATTEMPTS
        )
        return None

    @staticmethod
    def _run_claimed(cr, job: dict[str, Any]) -> None:
        """Execute a claimed job and mark it done in the SAME transaction.

        Atomic completion: the business writes and ``state = 'done'`` commit
        together (in the caller), so a crash between them is impossible —
        re-execution can only happen when the effects were rolled back too.
        Raises on business failure; the caller rolls back and records it.

        The scheduling user is re-checked here rather than trusted from enqueue
        time: archiving an account is how access is revoked, and a queue holds
        that account's work for as long as its ``eta`` and retry backoff last.
        ``ir.cron`` refuses to run a server action as an archived user for the
        same reason.

        The company comes from the stored context's ``allowed_company_ids``, or
        (when the enqueue carried none, as a cron/shell/nested enqueue does)
        from the user's companies as they stand at execution time.  The
        persisted ``company_id`` is deliberately *not* used to seed the scope:
        ``allowed_company_ids = [company_id]`` would pin ``env.company``
        correctly but shrink ``env.companies`` to that one company, silently
        hiding records from any job that reads across the user's companies.
        Pinning the enqueue-time scope faithfully means storing the whole
        ``[company] + rest`` list at enqueue, which in turn lets a job run
        against a company revoked in the meantime (nothing validates
        ``allowed_company_ids`` against ``user.company_ids``).
        """
        env = api.Environment(cr, job["user_id"], dict(job["context"] or {}))
        if not env.user.active and env.uid != SUPERUSER_ID:
            raise TerminalJobError(
                env._(
                    "Job %(id)s runs as %(login)s, whose account has been "
                    "archived since the job was enqueued.",
                    id=job["id"],
                    login=env.user.login,
                )
            )
        records = env[job["model_name"]].browse(job["record_ids"] or [])
        if _job_config_of(type(records), job["method_name"]) is None:
            raise TypeError(
                f"ir.job {job['id']}: {job['model_name']}.{job['method_name']} "
                "is not declared with @api.job"
            )
        _logger.info(
            "Job %s: %s%s.%s() starting (retry %s/%s)",
            job["id"],
            job["model_name"],
            job["record_ids"] or "",
            job["method_name"],
            job["retry"],
            job["max_retries"],
        )
        getattr(records, job["method_name"])(
            *(job["args"] or []), **(job["kwargs"] or {})
        )
        env.flush_all()
        cr.execute(
            SQL(
                "UPDATE ir_job SET state = 'done',"
                " done_at = (now() AT TIME ZONE 'UTC'),"
                " exc_name = NULL, exc_message = NULL, exc_info = NULL,"
                " write_date = (now() AT TIME ZONE 'UTC')"
                " WHERE id = %s AND state = 'started'",
                job["id"],
            )
        )
        if IrJob._release_dependents(cr, job["id"]):
            IrJob._notify_after_commit(cr)
        _logger.info("Job %s: done", job["id"])

    @classmethod
    def _record_failure(cls, cr, job: dict[str, Any], exc: BaseException) -> None:
        """Requeue with backoff while the retry budget lasts, else fail.

        Runs on a fresh transaction (the caller rolled the business one back).
        Every exception consumes a retry; ``RetryableJobError`` only differs
        in that it may carry an explicit delay and is not logged as an error,
        and ``TerminalJobError`` in that it consumes the budget outright --
        it names a condition the next attempt is certain to hit again, so
        climbing the backoff ladder only buys one traceback per rung.
        A classmethod (not staticmethod) so the registry dispatch in
        ``_claim_and_run_loop`` lets per-database overrides of
        ``_notify_failed`` apply.
        """
        retry = job["retry"]
        exc_info = _format_exception(exc)
        if retry < job["max_retries"] and not isinstance(exc, TerminalJobError):
            seconds = getattr(exc, "seconds", None)
            delay = (
                seconds
                if seconds is not None
                else min(RETRY_BACKOFF_BASE_S * 2**retry, RETRY_BACKOFF_MAX_S)
            )
            cr.execute(
                SQL(
                    """
                    UPDATE ir_job
                    SET state = CASE WHEN %s > 0 THEN 'scheduled' ELSE 'pending' END,
                        retry = retry + 1,
                        eta = (now() AT TIME ZONE 'UTC') + %s * interval '1 second',
                        exc_name = %s, exc_message = %s, exc_info = %s,
                        started_at = NULL, worker_ident = NULL,
                        write_date = (now() AT TIME ZONE 'UTC')
                    WHERE id = %s AND state = 'started'
                    """,
                    delay,
                    delay,
                    type(exc).__name__,
                    str(exc)[:1000],
                    exc_info,
                    job["id"],
                )
            )
            _logger.info(
                "Job %s: retry %s/%s in %ss (%s)",
                job["id"],
                retry + 1,
                job["max_retries"],
                delay,
                type(exc).__name__,
            )
        else:
            cr.execute(
                SQL(
                    """
                    UPDATE ir_job
                    SET state = 'failed',
                        done_at = (now() AT TIME ZONE 'UTC'),
                        exc_name = %s, exc_message = %s, exc_info = %s,
                        write_date = (now() AT TIME ZONE 'UTC')
                    WHERE id = %s AND state = 'started'
                    """,
                    type(exc).__name__,
                    str(exc)[:1000],
                    exc_info,
                    job["id"],
                )
            )
            _logger.error(
                "Job %s: failed permanently after %s retries", job["id"], retry
            )
            IrJob._cancel_dependents(cr, [job["id"]])
            cls._notify_failed(cr, job, exc)

    @staticmethod
    def _notify_failed(cr, job: dict[str, Any], exc: BaseException) -> None:
        """Notify some administrator that a job failed permanently.

        The base implementation only logs (the caller already logged the
        error); override it per database with an actual communication
        mechanism (mail activity, chat ping, ...) — the ``mail``-aware
        override cannot live in base, mirroring ``IrCron._notify_admin``.
        """

    @staticmethod
    def _reap_dead_jobs(cr) -> None:
        """Requeue ``started`` jobs whose worker died mid-run.

        A live worker holds the job's session advisory lock for the whole
        execution; if ``pg_try_advisory_lock`` succeeds here, the owning
        session is gone.  The grace period keeps brand-new claims out of
        consideration entirely.  Replaces any heartbeat machinery: liveness
        is the lock itself.

        Capped at ``REAP_BATCH_SIZE`` rows: after a mass worker kill the
        candidate set is the whole in-flight queue, and every row costs a
        try-lock round-trip, on the pre-flight cursor that gates all job
        processing for the database.  Whatever is left over is reaped by the
        next sweep.
        """
        cr.execute(
            "SELECT id, retry, max_retries FROM ir_job"
            " WHERE state = 'started' AND started_at <"
            " (now() AT TIME ZONE 'UTC') - %s * interval '1 second'"
            " ORDER BY started_at LIMIT %s",
            (DEAD_JOB_GRACE_S, REAP_BATCH_SIZE),
        )
        for job_id, retry, max_retries in cr.fetchall():
            with _job_session_lock(cr, job_id, blocking=False) as acquired:
                if not acquired:
                    continue
                if retry < max_retries:
                    cr.execute(
                        SQL(
                            "UPDATE ir_job SET state = 'pending',"
                            " retry = retry + 1, started_at = NULL,"
                            " worker_ident = NULL, exc_name = 'WorkerDied',"
                            " exc_message = 'job worker died during execution',"
                            " write_date = (now() AT TIME ZONE 'UTC')"
                            " WHERE id = %s AND state = 'started'",
                            job_id,
                        )
                    )
                else:
                    cr.execute(
                        SQL(
                            "UPDATE ir_job SET state = 'failed',"
                            " done_at = (now() AT TIME ZONE 'UTC'),"
                            " exc_name = 'WorkerDied',"
                            " exc_message = 'job worker died during execution',"
                            " write_date = (now() AT TIME ZONE 'UTC')"
                            " WHERE id = %s AND state = 'started'",
                            job_id,
                        )
                    )
                if cr.rowcount:
                    _logger.warning("Job %s: reaped from a dead worker", job_id)

    @staticmethod
    def _release_dependents(cr, job_id: int) -> int:
        """Promote ``wait_deps`` dependents of ``job_id`` whose every
        dependency is now done.  Returns the number that became *claimable*.

        Called inside the completing job's transaction, after its own row
        turned ``done`` (visible in-snapshot), so promotion is atomic with
        completion.

        A dependent carrying a future ``eta`` lands in ``scheduled``, not
        ``pending``, and is deliberately excluded from the count: the caller
        NOTIFYs on it, and waking every worker in the cluster for a job none of
        them may claim yet buys nothing.
        """
        cr.execute(
            SQL(
                """
                UPDATE ir_job d
                SET state = %s, write_date = (now() AT TIME ZONE 'UTC')
                WHERE d.state = 'wait_deps'
                  AND d.id IN (SELECT job_id FROM ir_job_dependency
                               WHERE depends_on_id = %s)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ir_job_dependency dd
                      JOIN ir_job pj ON pj.id = dd.depends_on_id
                      WHERE dd.job_id = d.id AND pj.state != 'done'
                  )
                RETURNING d.state
                """,
                _DUE_STATE_SQL,
                job_id,
            )
        )
        return sum(1 for (state,) in cr.fetchall() if state == JobState.PENDING)

    @staticmethod
    def _cancel_dependents(cr, job_ids: list[int]) -> int:
        """Cascade-cancel the transitive ``wait_deps`` dependents of
        failed/cancelled jobs.  Returns the number of cancelled jobs.
        """
        cr.execute(
            SQL(
                """
                WITH RECURSIVE dependents AS (
                    SELECT d.job_id FROM ir_job_dependency d
                    WHERE d.depends_on_id = ANY(%s::int[])
                    UNION
                    SELECT d2.job_id FROM ir_job_dependency d2
                    JOIN dependents ON d2.depends_on_id = dependents.job_id
                )
                UPDATE ir_job j
                SET state = 'cancelled',
                    done_at = (now() AT TIME ZONE 'UTC'),
                    exc_name = 'DependencyFailed',
                    exc_message = 'a job this one depends on failed'
                                  ' or was cancelled',
                    write_date = (now() AT TIME ZONE 'UTC')
                WHERE j.id IN (SELECT job_id FROM dependents)
                  AND j.state = 'wait_deps'
                """,
                job_ids,
            )
        )
        if cr.rowcount:
            _logger.info(
                "Cancelled %s dependent job(s) of failed/cancelled %s",
                cr.rowcount,
                job_ids,
            )
        return cr.rowcount

    @staticmethod
    def _resolve_dependencies(cr) -> None:
        """Repair sweep: re-derive the state of every ``wait_deps`` job.

        Promotes jobs whose dependencies all completed and cascade-cancels
        jobs with a failed/cancelled dependency.  Needed because enqueueing
        with ``after=`` reads dependency states without locking them — a
        dependency finishing in the race window is caught here on the next
        worker pass (see ``_enqueue``).

        The dead-dependency scan is restricted to failures that still have a
        ``wait_deps`` dependent.  Unrestricted, it re-collected every
        failed/cancelled job in the retention window — thirty days of them —
        and pushed them all through the recursive cascade on every sweep, to
        update nothing: the cascade itself only touches ``wait_deps`` rows.
        """
        cr.execute(
            SQL(
                """
            UPDATE ir_job d
            SET state = %s, write_date = (now() AT TIME ZONE 'UTC')
            WHERE d.state = 'wait_deps'
              AND NOT EXISTS (
                  SELECT 1
                  FROM ir_job_dependency dd
                  JOIN ir_job pj ON pj.id = dd.depends_on_id
                  WHERE dd.job_id = d.id AND pj.state != 'done'
              )
            """,
                _DUE_STATE_SQL,
            )
        )
        promoted = cr.rowcount
        cr.execute(
            "SELECT DISTINCT d.depends_on_id FROM ir_job_dependency d"
            " JOIN ir_job pj ON pj.id = d.depends_on_id"
            " JOIN ir_job cj ON cj.id = d.job_id"
            " WHERE pj.state IN ('failed', 'cancelled')"
            " AND cj.state = 'wait_deps'"
        )
        dead = [r[0] for r in cr.fetchall()]
        if dead:
            IrJob._cancel_dependents(cr, dead)
        if promoted:
            _logger.info("Promoted %s job(s) whose dependencies completed", promoted)

    @api.autovacuum
    def _gc_jobs(self) -> tuple[int, bool]:
        """Prune finished jobs past their retention window.

        ``done``/``cancelled`` after ``DONE_RETENTION``; ``failed`` after the
        longer ``FAILED_RETENTION`` (still inspectable/requeueable meanwhile).
        Dependency rows follow via the M2M table.
        """
        now = self.env.cr.now()
        domain = [
            "|",
            "&",
            ("state", "in", (JobState.DONE, JobState.CANCELLED)),
            ("done_at", "<", now - DONE_RETENTION),
            "&",
            ("state", "=", JobState.FAILED),
            ("done_at", "<", now - FAILED_RETENTION),
        ]
        records = self.sudo().search(domain, limit=GC_UNLINK_LIMIT)
        records.unlink()
        return len(records), len(records) == GC_UNLINK_LIMIT

    def write(self, vals: dict[str, Any]) -> bool:
        result = super().write(vals)
        if "eta" in vals and "state" not in vals:
            self._align_state_with_eta()
        return result

    def _align_state_with_eta(self) -> None:
        """Re-derive the queued state of these jobs from their ``eta``.

        The invariant the whole ``pending``/``scheduled`` split rests on --
        ``pending`` means *claimable this instant* -- is otherwise enforced only
        by the writers that happen to remember it (``_enqueue``,
        ``_record_failure``, ``_release_dependents``, all of which go through
        :data:`_DUE_STATE_SQL`).  A plain ORM write does not, and the form view
        exposes ``eta`` as an editable field: postponing a pending job left it
        ``pending`` and unclaimable, sitting in ``ir_job_claim_idx`` and counted
        as ready; bringing a scheduled job forward left it ``scheduled``, which
        :meth:`_promote_due_jobs` does pick up, but only on the next worker
        pass.  Making the model enforce it costs nothing here and keeps the
        claim index exact whatever writes the field.
        """
        now = self._clock_now()
        queued = self.filtered(lambda job: job.state in RUNNABLE_STATES)
        due = queued.filtered(lambda job: not job.eta or job.eta <= now)
        if promote := due.filtered(lambda job: job.state != JobState.PENDING):
            promote.write({"state": JobState.PENDING})
            self._notify_after_commit(self.env.cr)
        if postpone := (queued - due).filtered(
            lambda job: job.state != JobState.SCHEDULED
        ):
            postpone.write({"state": JobState.SCHEDULED})

    @api.depends("name", "model_name", "method_name")
    def _compute_display_name(self) -> None:
        for job in self:
            job.display_name = (
                job.name or f"{job.model_name}.{job.method_name} (#{job.id})"
            )

    def action_run_now(self) -> None:
        """Execute a pending job immediately, in the current transaction.

        The ops "Run Manually" button: claims the job by id (ignoring its
        ``eta`` and — deliberately, like ``ir.cron``'s direct trigger — the
        channel capacity) and runs it inline.  On success the job commits
        ``done`` with the request; on failure the exception propagates to the
        user and the whole transaction rolls back, leaving the job pending
        and untouched.

        The run takes the job's advisory lock first, transaction-scoped so it
        lasts exactly as long as the inline run.  It is the same lock a worker
        holds, and it is what proves liveness to :meth:`_reap_dead_jobs`:
        The manual runner was the one executor that did not hold it, which
        matters as soon as the job's own code commits: that commit publishes
        the ``started`` row to every other session while the run is still in
        flight, and a reaper finding it unlocked past ``DEAD_JOB_GRACE_S``
        concludes the worker died and requeues it — the work then runs a
        second time while the first run is still going, and the manual run's
        closing ``state = 'done'`` matches no row and is silently lost.  The
        lock is session-scoped precisely so those intermediate commits do not
        drop it; it is released on the way out, leaving only the return path
        (rather than the whole run) unprotected.

        Taking it non-blocking also replaces an unbounded wait: a second "Run
        Manually" used to block on the first run's uncommitted row lock for as
        long as that run lasted, holding a request worker, before finally
        reporting that the job is not pending.
        """
        self.ensure_one()
        self.browse().check_access("write")
        self.env.flush_all()
        cr = self.env.cr
        with _job_session_lock(cr, self.id, blocking=False) as acquired:
            if not acquired:
                raise UserError(self.env._("This job is already running."))
            cr.execute(
                SQL(
                    """
                    UPDATE ir_job
                    SET state = 'started',
                        started_at = (now() AT TIME ZONE 'UTC'),
                        worker_ident = %s,
                        write_date = (now() AT TIME ZONE 'UTC')
                    WHERE id = %s AND state IN %s
                    RETURNING id, uuid, channel, priority, model_name,
                              method_name, record_ids, args, kwargs, user_id,
                              company_id, context, retry, max_retries
                    """,
                    f"manual:{self.env.uid}",
                    self.id,
                    tuple(RUNNABLE_STATES),
                )
            )
            row = cr.fetchone()
            if row is None:
                raise UserError(self.env._("Only a queued job can be run manually."))
            job = dict(zip([d.name for d in cr.description], row, strict=True))
            self.invalidate_recordset()
            type(self)._run_claimed(cr, job)
            self.invalidate_recordset()

    def action_requeue(self) -> None:
        """Put failed/cancelled jobs back in the queue (fresh retry budget).

        A job with unfinished dependencies goes back to ``wait_deps``, not
        ``pending``.  Requeue failed dependencies first (or together): a
        requeued dependent whose dependency is still failed gets cancelled
        again by the repair sweep, by design.

        The previous run's traces are cleared along with the retry budget.  A
        requeued job kept the ``exc_*`` of the failure being retried — so the
        form showed an Error page on a job that is merely queued — and a
        ``worker_ident``/``started_at`` naming a worker that is not running it,
        which is exactly the shape :meth:`_reap_dead_jobs` reads as liveness.
        """
        self.browse().check_access("write")
        for job in self:
            if job.state not in DEAD_DEPENDENCY_STATES:
                raise UserError(
                    self.env._("Only failed or cancelled jobs can be requeued.")
                )
        requeued = False
        for job in self:
            waiting = any(dep.state != JobState.DONE for dep in job.depends_on_ids)
            requeued = requeued or not waiting
            job.sudo().write(
                {
                    "state": JobState.WAIT_DEPS if waiting else JobState.PENDING,
                    "retry": 0,
                    "eta": False,
                    "done_at": False,
                    "started_at": False,
                    "worker_ident": False,
                    "exc_name": False,
                    "exc_message": False,
                    "exc_info": False,
                }
            )
        if requeued:
            self._notify_after_commit(self.env.cr)

    def action_cancel(self) -> None:
        """Cancel waiting/pending jobs (started jobs cannot be interrupted).

        Waiting dependents of a cancelled job are cascade-cancelled too —
        they could never start otherwise.
        """
        self.browse().check_access("write")
        for job in self:
            if job.state not in CANCELLABLE_STATES:
                raise UserError(
                    self.env._("Only jobs that have not started yet can be cancelled.")
                )
        self.sudo().write({"state": JobState.CANCELLED, "done_at": self.env.cr.now()})
        self.env.flush_all()
        type(self)._cancel_dependents(self.env.cr, self.ids)
