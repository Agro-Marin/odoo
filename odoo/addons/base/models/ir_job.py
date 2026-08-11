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
from odoo.db.errors import PG_RETRY_EXCEPTIONS
from odoo.exceptions import (
    ConcurrencyError,
    RetryableJobError,
    TerminalJobError,
    UserError,
    ValidationError,
)
from odoo.libs import backoff
from odoo.models import GC_UNLINK_LIMIT
from odoo.modules.registry import Registry
from odoo.tools import SQL
from odoo.tools.constants import JOB_QUEUE_CHANNEL

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

CONCURRENCY_MAX_ATTEMPTS = 5
CONCURRENCY_BACKOFF_BASE_S = 0.2
CONCURRENCY_BACKOFF_MAX_S = 2.0
JOB_CONCURRENCY_EXCEPTIONS = (*PG_RETRY_EXCEPTIONS, ConcurrencyError)
"""Failures that mean "somebody else committed first", not "this job is broken".

The set :func:`odoo.service.transaction.retrying` replays an HTTP request on.
A job body writing the same rows as a concurrent request loses the same races,
and reaching them through :meth:`IrJob._record_failure` instead charged each
one a retry off the budget plus a rung of the backoff ladder -- five lost races
and a perfectly correct job is ``failed`` for good.
"""

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
    return "(" + ", ".join(f"'{state.value}'" for state in states) + ")"


QUEUED_STATES_SQL = _states_sql(QUEUED_STATES)


def _format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _current_job() -> dict | None:
    """The job this thread is executing, if any.

    Set by :meth:`IrJob._run_claimed` around the body call so a job can ask
    for its own deferral without being handed a handle to itself.
    """
    return getattr(threading.current_thread(), "ir_job", None)


@contextmanager
def _running_job(job: dict[str, Any]) -> Iterator[None]:
    """Mark this thread as executing ``job`` for the duration of the body."""
    thread = threading.current_thread()
    previous = getattr(thread, "ir_job", None)
    thread.ir_job = job
    try:
        yield
    finally:
        thread.ir_job = previous


def _job_config_of(model_cls: type, method_name: str) -> dict | None:
    for klass in model_cls.__mro__:
        func = klass.__dict__.get(method_name)
        if func is not None and (job_config := getattr(func, "_job_config", None)):
            return job_config
    return None


def _advisory_key_sql(job_id: int | SQL) -> SQL:
    return SQL("hashtextextended('ir_job:' || %s::text, 0)", job_id)


@contextmanager
def _job_session_lock(cr, job_id: int, *, blocking: bool = True) -> Iterator[bool]:
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
    __slots__ = ("_props", "_records")

    def __init__(self, records: models.BaseModel, props: dict[str, Any]) -> None:
        self._records = records
        self._props = props

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        records, props = self._records, self._props

        def enqueue(*args: Any, **kwargs: Any) -> models.BaseModel:
            return records.env["ir.job"]._enqueue(
                records, name, args=args, kwargs=kwargs, **props
            )

        return enqueue


class Base(models.AbstractModel):
    _inherit = "base"

    @api.private
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
    defer_count = fields.Integer(
        default=0,
        readonly=True,
        help="Times the job asked to be run again later. A deferral is not a "
        "failure, so it has its own budget and does not consume a retry.",
    )
    max_defers = fields.Integer(default=100, readonly=True)
    defer_reason = fields.Char(
        readonly=True,
        help="Why the job last asked to be run again later.",
    )
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
        if self._has_cycle("depends_on_ids"):
            raise ValidationError(self.env._("Job dependencies cannot form a cycle."))

    @api.job(max_retries=0)
    def _job_ping(self, message: str = "") -> None:
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
                    defer_count, max_defers,
                    create_uid, create_date, write_uid, write_date
                ) VALUES (
                    %s, gen_random_uuid()::varchar, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s::jsonb, 0, %s,
                    0, %s,
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
                job_config["max_defers"],
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
    def _defer(self, seconds: int, reason: str = "") -> None:
        """Ask the queue to run this job again later, keeping what it did.

        For a job whose work is not finished because something *outside* it is
        not ready yet -- polling a remote service that is still preparing an
        answer, waiting on a file that has not landed. That is not a failure,
        and it must not be reported as one:

        - the body's writes are kept and committed, because a poll that
          learned something should not throw the answer away;
        - ``retry`` is untouched, so the tolerance that exists for genuine
          errors is not eaten by a service that is merely slow;
        - nothing is recorded in ``exc_*``, because nothing went wrong;
        - the job keeps its ``identity_key`` throughout, so a caller cannot
          queue a duplicate for the same work while it waits.

        Raising :class:`RetryableJobError` is the wrong tool for this: it is
        an exception, so the transaction is rolled back and the poll's
        findings are lost, and it spends a retry per attempt.

        Deferrals have their own budget, ``max_defers`` on ``@api.job``. A job
        that exhausts it fails, because a job that never stops asking for more
        time is stuck.

        :param int seconds: how long to wait before running again
        :param str reason: shown on the job, for whoever looks at the queue
        :raises UserError: if called outside a running job
        :raises TerminalJobError: if the deferral budget is spent
        """
        job = _current_job()
        if job is None:
            raise UserError(
                self.env._(
                    "_defer() can only be called from inside a running job."
                )
            )
        if job["defer_count"] >= job["max_defers"]:
            raise TerminalJobError(
                self.env._(
                    "Job %(id)s asked to be deferred %(count)s times, its "
                    "whole budget, and is still not finished.",
                    id=job["id"],
                    count=job["defer_count"],
                )
            )
        job["defer"] = {"seconds": max(int(seconds), 0), "reason": reason or ""}

    @api.model
    def _clock_now(self) -> datetime:
        self.env.cr.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')")
        return self.env.cr.fetchone()[0]

    @staticmethod
    def _notify_after_commit(cr) -> None:
        if cr.postcommit.data.get(NOTIFY_PENDING_KEY):
            return
        cr.postcommit.data[NOTIFY_PENDING_KEY] = True
        db_name = cr.dbname
        cr.postcommit.add(lambda: IrJob._notify_workers(db_name))

    @staticmethod
    def _notify_workers(db_name: str) -> None:
        notify_channel(JOB_QUEUE_CHANNEL, db_name)

    @staticmethod
    def _process_jobs(db_name: str) -> None:
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
        budget = worker_real_time_budget()
        return time.monotonic() + budget * DRAIN_BUDGET_RATIO if budget else None

    @staticmethod
    def _promote_due_jobs(cr) -> int:
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
                    exc = IrJob._run_with_concurrency_replay(registry, cr, job)
                    if exc is None:
                        registry.signal_changes()
                        continue
                    IrJob._log_job_failure(job, exc)
                    registry[IrJob._name]._record_failure(cr, job, exc)
                    cr.commit()

    @staticmethod
    def _run_with_concurrency_replay(
        registry, cr, job: dict[str, Any]
    ) -> BaseException | None:
        for attempt in range(1, CONCURRENCY_MAX_ATTEMPTS + 1):
            try:
                registry[IrJob._name]._run_claimed(cr, job)
                cr.commit()
                return None
            except Exception as exc:
                registry.reset_changes()
                cr.rollback()
                if not isinstance(exc, JOB_CONCURRENCY_EXCEPTIONS):
                    return exc
                if attempt == CONCURRENCY_MAX_ATTEMPTS:
                    _logger.info(
                        "Job %s: %s on every one of %s attempts, recording it",
                        job["id"],
                        type(exc).__name__,
                        CONCURRENCY_MAX_ATTEMPTS,
                    )
                    return exc
                wait = backoff.delay(
                    attempt,
                    base=CONCURRENCY_BACKOFF_BASE_S,
                    cap=CONCURRENCY_BACKOFF_MAX_S,
                )
                _logger.info(
                    "Job %s: %s, replaying in %.2fs (attempt %s/%s)",
                    job["id"],
                    type(exc).__name__,
                    wait,
                    attempt,
                    CONCURRENCY_MAX_ATTEMPTS,
                )
                time.sleep(wait)
        raise AssertionError("the replay loop always returns")

    @staticmethod
    def _log_job_failure(job: dict[str, Any], exc: BaseException) -> None:
        if isinstance(exc, RetryableJobError):
            return
        target = f"{job['model_name']}.{job['method_name']}"
        if isinstance(exc, UserError):
            _logger.warning("Job %s (%s) refused: %s", job["id"], target, exc)
        else:
            _logger.error("Job %s (%s) failed", job["id"], target, exc_info=exc)

    @staticmethod
    def _claim_next(
        cr, worker_ident: str, channels: list[str] | None = None
    ) -> dict[str, Any] | None:
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
                                  max_retries, defer_count, max_defers
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
        env = IrJob._narrow_company_scope(env, job)
        try:
            model = env[job["model_name"]]
        except KeyError:
            raise TerminalJobError(
                env._(
                    "Job %(id)s targets model %(model)s, which no longer exists "
                    "in this database.",
                    id=job["id"],
                    model=job["model_name"],
                )
            ) from None
        records = model.browse(job["record_ids"] or [])
        if _job_config_of(type(records), job["method_name"]) is None:
            raise TerminalJobError(
                env._(
                    "Job %(id)s calls %(model)s.%(method)s, which is not "
                    "declared with @api.job.",
                    id=job["id"],
                    model=job["model_name"],
                    method=job["method_name"],
                )
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
        job.pop("defer", None)
        with _running_job(job):
            getattr(records, job["method_name"])(
                *(job["args"] or []), **(job["kwargs"] or {})
            )
        env.flush_all()
        if defer := job.get("defer"):
            IrJob._record_deferral(cr, job, defer)
            return
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
        if not cr.rowcount:
            _logger.error(
                "Job %s: completed but its row was no longer 'started'; the"
                " work commits without being marked done and may run again",
                job["id"],
            )
        if IrJob._release_dependents(cr, job["id"]):
            IrJob._notify_after_commit(cr)
        _logger.info("Job %s: done", job["id"])

    @staticmethod
    def _record_deferral(cr, job: dict[str, Any], defer: dict[str, Any]) -> None:
        """Put a job that asked for more time back on the clock.

        Deliberately not :meth:`_record_failure`: ``retry`` is untouched and
        ``exc_*`` is cleared, because a deferral says the job made progress
        and is not finished, not that anything went wrong. Dependents stay
        blocked, which is correct -- the job has not delivered yet.
        """
        seconds = defer["seconds"]
        cr.execute(
            SQL(
                """
                UPDATE ir_job
                SET state = CASE WHEN %s > 0 THEN 'scheduled' ELSE 'pending' END,
                    eta = (now() AT TIME ZONE 'UTC') + %s * interval '1 second',
                    defer_count = defer_count + 1,
                    defer_reason = %s,
                    exc_name = NULL, exc_message = NULL, exc_info = NULL,
                    started_at = NULL, worker_ident = NULL,
                    write_date = (now() AT TIME ZONE 'UTC')
                WHERE id = %s AND state = 'started'
                """,
                seconds,
                seconds,
                (defer["reason"] or None) and defer["reason"][:1000],
                job["id"],
            )
        )
        if not cr.rowcount:
            _logger.error(
                "Job %s: asked to be deferred but its row was no longer"
                " 'started'; the work commits and the job may run again",
                job["id"],
            )
        _logger.info(
            "Job %s: deferred %ss (%s/%s), %s",
            job["id"],
            seconds,
            job["defer_count"] + 1,
            job["max_defers"],
            defer["reason"] or "no reason given",
        )

    @staticmethod
    def _narrow_company_scope(env, job: dict[str, Any]):
        allowed = (job["context"] or {}).get("allowed_company_ids")
        if not allowed or env.su:
            return env
        available = set(env.user._get_company_ids())
        kept = [company_id for company_id in allowed if company_id in available]
        if kept == list(allowed):
            return env
        _logger.warning(
            "Job %s: dropping %s from its company scope, no longer available to %s",
            job["id"],
            sorted(set(allowed) - available),
            env.user.login,
        )
        context = dict(env.context)
        if kept:
            context["allowed_company_ids"] = kept
        else:
            context.pop("allowed_company_ids", None)
        return api.Environment(env.cr, env.uid, context)

    @classmethod
    def _record_failure(cls, cr, job: dict[str, Any], exc: BaseException) -> None:
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
        pass

    @staticmethod
    def _reap_dead_jobs(cr) -> int:
        cr.execute(
            SQL(
                """
                WITH candidates AS MATERIALIZED (
                    SELECT id, retry < max_retries AS requeue
                    FROM ir_job
                    WHERE state = 'started'
                      AND started_at < (now() AT TIME ZONE 'UTC')
                          - %s * interval '1 second'
                    ORDER BY started_at
                    LIMIT %s
                )
                SELECT id, requeue FROM candidates WHERE pg_try_advisory_lock(%s)
                """,
                DEAD_JOB_GRACE_S,
                REAP_BATCH_SIZE,
                _advisory_key_sql(SQL.identifier("id")),
            )
        )
        rows = cr.fetchall()
        if not rows:
            return 0
        requeue_ids = [job_id for job_id, requeue in rows if requeue]
        fail_ids = [job_id for job_id, requeue in rows if not requeue]
        reaped = 0
        if requeue_ids:
            cr.execute(
                SQL(
                    "UPDATE ir_job SET state = 'pending',"
                    " retry = retry + 1, started_at = NULL,"
                    " worker_ident = NULL, exc_name = 'WorkerDied',"
                    " exc_message = 'job worker died during execution',"
                    " write_date = (now() AT TIME ZONE 'UTC')"
                    " WHERE id = ANY(%s) AND state = 'started'",
                    requeue_ids,
                )
            )
            reaped += cr.rowcount
        if fail_ids:
            cr.execute(
                SQL(
                    "UPDATE ir_job SET state = 'failed',"
                    " done_at = (now() AT TIME ZONE 'UTC'),"
                    " exc_name = 'WorkerDied',"
                    " exc_message = 'job worker died during execution',"
                    " write_date = (now() AT TIME ZONE 'UTC')"
                    " WHERE id = ANY(%s) AND state = 'started'",
                    fail_ids,
                )
            )
            reaped += cr.rowcount
        cr.execute(
            SQL(
                "SELECT pg_advisory_unlock(%s) FROM unnest(%s::bigint[]) AS id",
                _advisory_key_sql(SQL.identifier("id")),
                [job_id for job_id, _requeue in rows],
            )
        )
        if reaped:
            _logger.warning(
                "Reaped %s job(s) from dead workers: %s requeued, %s out of retries",
                reaped,
                len(requeue_ids),
                len(fail_ids),
            )
        return reaped

    @staticmethod
    def _release_dependents(cr, job_id: int) -> int:
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
                              company_id, context, retry, max_retries,
                              defer_count, max_defers
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
        self.browse().check_access("write")
        for job in self:
            if job.state not in CANCELLABLE_STATES:
                raise UserError(
                    self.env._("Only jobs that have not started yet can be cancelled.")
                )
        self.sudo().write({"state": JobState.CANCELLED, "done_at": self.env.cr.now()})
        self.env.flush_all()
        type(self)._cancel_dependents(self.env.cr, self.ids)
