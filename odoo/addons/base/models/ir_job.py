"""Framework-native background job queue (``ir.job``).

Postgres-as-broker asynchronous execution: a job is a method call — model,
method, records, arguments — persisted as an ``ir_job`` row **in the caller's
transaction** (transactional enqueue: the job and the business change commit
or vanish together).  Dedicated workers (``WorkerJob`` in prefork mode, the
``job_thread`` daemon threads in threaded mode — see ``odoo.service``) wake up
on a ``job_queue`` NOTIFY, claim work with ``FOR NO KEY UPDATE SKIP LOCKED``
and execute it in-process, each job in its own transaction.

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
import traceback
from datetime import timedelta
from typing import Any

import psycopg.errors

from odoo import api, db, fields, models
from odoo.exceptions import RetryableJobError, UserError
from odoo.modules.registry import Registry
from odoo.tools import SQL

from .ir_cron import ODOO_NOTIFY_FUNCTION, BadVersionError, IrCron

_logger = logging.getLogger(__name__)

# LISTEN/NOTIFY channel; must match JOB_QUEUE_CHANNEL in odoo/service/_cron.py
# (kept as a literal here for the same reason ir_cron hardcodes
# "cron_trigger": base models do not import odoo.service).
JOB_QUEUE_CHANNEL = "job_queue"

# Context keys copied from the enqueuing environment into the job.  Everything
# else is dropped: the context is attacker-reachable data once persisted, and
# keys like ``default_*`` / ``active_test`` could change what the job writes.
ALLOWED_CONTEXT_KEYS = ("lang", "tz", "allowed_company_ids")

# A ``started`` job younger than this is never considered for reaping, closing
# any doubt about claim-to-lock ordering races (the lock is in fact acquired
# before the claim commits, so this is belt-and-braces).
DEAD_JOB_GRACE_S = 60

# Default retry backoff: 10s, 20s, 40s, ... capped at 1h.  A RetryableJobError
# with an explicit ``seconds`` overrides it.
RETRY_BACKOFF_BASE_S = 10
RETRY_BACKOFF_MAX_S = 3600

WAIT_DEPS = "wait_deps"
PENDING = "pending"
STARTED = "started"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

STATES = [
    (WAIT_DEPS, "Waiting Dependencies"),
    (PENDING, "Pending"),
    (STARTED, "Started"),
    (DONE, "Done"),
    (FAILED, "Failed"),
    (CANCELLED, "Cancelled"),
]


def _advisory_key_sql(job_id: int) -> SQL:
    """Bigint advisory-lock key for a job id (single source for claim/reaper)."""
    return SQL("hashtextextended('ir_job:' || %s::text, 0)", job_id)


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
            },
        )


class IrJobChannel(models.Model):
    """Capacity class for background jobs.

    ``capacity`` bounds how many jobs of the channel run concurrently across
    the whole cluster (enforced by the claim query).  A channel referenced by
    jobs but absent from this table has an implicit capacity of 1.
    """

    _name = "ir.job.channel"
    _description = "Background Job Channel"
    _allow_sudo_commands = False

    name = fields.Char(required=True)
    capacity = fields.Integer(
        default=1,
        required=True,
        help="Maximum number of jobs of this channel running concurrently, "
        "across all job workers.",
    )
    active = fields.Boolean(default=True)

    _name_uniq = models.UniqueIndex("(name)", "Channel names must be unique.")
    _check_capacity = models.Constraint(
        "CHECK(capacity > 0)",
        "The channel capacity must be strictly positive.",
    )


class IrJob(models.Model):
    """A persisted method call, executed asynchronously by the job workers."""

    _name = "ir.job"
    _description = "Background Job"
    _order = "priority, create_date, id"
    _allow_sudo_commands = False

    uuid = fields.Char(readonly=True, index=True)
    channel = fields.Char(required=True, default="root", readonly=True)
    state = fields.Selection(STATES, required=True, default=PENDING, index=True)
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

    _claim_idx = models.Index(
        "(channel, priority, create_date) WHERE state = 'pending'"
    )
    _identity_uniq = models.UniqueIndex(
        "(identity_key) WHERE state IN ('wait_deps', 'pending', 'started')"
        " AND identity_key IS NOT NULL",
        "A job with the same identity key is already queued.",
    )

    @api.job(max_retries=0)
    def _job_ping(self, message: str = "") -> None:
        """Operational smoke test: verify job workers pick up and run jobs.

        ``env["ir.job"].delayed()._job_ping("hi")`` from a shell, then check
        the log (and the job row turning ``done``) to confirm the pipeline —
        enqueue, NOTIFY, claim, execute — works on a deployment.
        """
        _logger.info("ir.job ping: %s", message or "pong")

    # ------------------------------------------------------------------
    # Enqueue side (runs in the caller's transaction)
    # ------------------------------------------------------------------

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
    ) -> models.BaseModel:
        """Persist a job row for ``records.method_name(*args, **kwargs)``.

        Raw ``INSERT ... ON CONFLICT DO NOTHING`` (not ``create()``): the
        partial unique index arbitrates ``identity_key`` dedup race-free,
        which a search-then-create cannot.  Called from ``delayed()`` only —
        it is not an RPC surface, and access control is the ``@api.job``
        marker check plus the model ACL on ``ir.job`` itself.

        With ``after``, the job starts in ``wait_deps`` unless every
        dependency is already done.  The dependency-state read is not locked
        against a dependency finishing concurrently — the repair sweep in
        ``_process_jobs`` re-resolves stuck jobs on every worker pass, so a
        race delays the job by at most one pass instead of losing it.
        On an ``identity_key`` dedup hit the existing job is returned as-is:
        no new dependencies are attached.
        """
        func = getattr(type(records), method_name, None)
        job_config = getattr(func, "_job_config", None)
        if job_config is None:
            raise UserError(
                self.env._(
                    "Method %(model)s.%(method)s cannot be enqueued: it is not "
                    "declared with @api.job.",
                    model=records._name,
                    method=method_name,
                )
            )
        try:
            args_json = json.dumps(list(args))
            kwargs_json = json.dumps(dict(kwargs or {}))
        except TypeError as exc:
            raise UserError(
                self.env._(
                    "Job arguments for %(model)s.%(method)s must be "
                    "JSON-serializable: %(error)s",
                    model=records._name,
                    method=method_name,
                    error=exc,
                )
            ) from exc

        if isinstance(eta, (int, float)):
            eta = fields.Datetime.now() + timedelta(seconds=eta)

        env = self.env
        state = PENDING
        dep_ids: list[int] = []
        if after:
            if after._name != self._name:
                raise UserError(self.env._("Job dependencies must be ir.job records."))
            dep_ids = after.ids
            env.cr.execute(
                SQL(
                    "SELECT state FROM ir_job WHERE id IN %s",
                    tuple(dep_ids),
                )
            )
            dep_states = {r[0] for r in env.cr.fetchall()}
            if dep_states & {FAILED, CANCELLED}:
                raise UserError(
                    self.env._(
                        "Cannot enqueue after a failed or cancelled job; "
                        "requeue the dependency first."
                    )
                )
            if dep_states - {DONE}:
                state = WAIT_DEPS

        context = {
            key: env.context[key] for key in ALLOWED_CONTEXT_KEYS if key in env.context
        }
        now = fields.Datetime.now()
        env.cr.execute(
            SQL(
                """
                INSERT INTO ir_job (
                    uuid, channel, state, priority, eta, identity_key,
                    model_name, method_name, record_ids, args, kwargs,
                    user_id, company_id, context, retry, max_retries,
                    create_uid, create_date, write_uid, write_date
                ) VALUES (
                    gen_random_uuid()::varchar, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s::jsonb, 0, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (identity_key)
                    WHERE state IN ('wait_deps', 'pending', 'started')
                    AND identity_key IS NOT NULL
                    DO NOTHING
                RETURNING id
                """,
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
            # identity_key dedup hit — return the live twin instead.  READ
            # COMMITTED window: the twin may complete between our INSERT and
            # this SELECT; ordering by id DESC returns the twin regardless of
            # its state, which is the correct dedup answer either way.
            env.cr.execute(
                SQL(
                    "SELECT id FROM ir_job WHERE identity_key = %s"
                    " ORDER BY id DESC LIMIT 1",
                    identity_key,
                )
            )
            row = env.cr.fetchone()
        elif dep_ids:
            env.cr.execute(
                SQL(
                    "INSERT INTO ir_job_dependency (job_id, depends_on_id)"
                    " SELECT %s, dep FROM unnest(%s::int[]) AS dep",
                    row[0],
                    dep_ids,
                )
            )
        if state == PENDING:
            env.cr.postcommit.add(self._notifydb)
        return self.browse(row[0])

    @api.model
    def _notifydb(self) -> None:
        """Wake up the job workers (cross-database: they LISTEN on 'postgres')."""
        IrJob._notify_workers(self.env.cr.dbname)

    @staticmethod
    def _notify_workers(db_name: str) -> None:
        """NOTIFY the job workers of ``db_name`` (they LISTEN on 'postgres')."""
        with db.db_connect("postgres").cursor() as cr:
            cr.execute(
                SQL(
                    "SELECT %s(%s, %s)",
                    SQL.identifier(ODOO_NOTIFY_FUNCTION),
                    JOB_QUEUE_CHANNEL,
                    db_name,
                )
            )
        _logger.debug("job workers notified (%s)", db_name)

    # ------------------------------------------------------------------
    # Worker side (runs on a worker's own cursor; no request environment)
    # ------------------------------------------------------------------

    @staticmethod
    def _process_jobs(db_name: str) -> None:
        """Claim and execute every ready job of this database.

        Entry point for ``WorkerJob.process_work`` and the threaded server's
        ``job_thread`` — the ``ir.job`` counterpart of
        ``IrCron._process_jobs``, sharing its guard structure: pre-flight
        checks run on a raw cursor without loading the registry (a
        wrong-version or mid-upgrade database must not be loaded at all).
        """
        try:
            db_conn = db.db_connect(db_name)
            threading.current_thread().dbname = db_name
            with db_conn.cursor() as pre_cr:
                IrCron._check_version(pre_cr)
                pre_cr.execute(
                    "SELECT EXISTS (SELECT 1 FROM ir_module_module"
                    " WHERE state IN ('to install', 'to upgrade', 'to remove'))"
                )
                if pre_cr.fetchone()[0]:
                    _logger.debug(
                        "Skipping database %s because of modules to"
                        " install/upgrade/remove.",
                        db_name,
                    )
                    return
                # Rescue jobs of dead workers first: their corpses hold
                # channel capacity, so reaping must precede claiming.
                IrJob._reap_dead_jobs(pre_cr)
                # Repair sweep for the dependency graph: releases wait_deps
                # jobs whose dependencies all completed and cascade-cancels
                # those with a failed/cancelled dependency.  The inline
                # resolution in _run_claimed/_record_failure is the fast
                # path; this sweep guarantees enqueue-time races only delay
                # a job by one worker pass instead of stranding it.
                IrJob._resolve_dependencies(pre_cr)
                pre_cr.commit()
                pre_cr.execute(
                    "SELECT EXISTS (SELECT 1 FROM ir_job WHERE state = 'pending'"
                    " AND (eta IS NULL OR eta <= (now() AT TIME ZONE 'UTC')))"
                )
                if not pre_cr.fetchone()[0]:
                    return
            IrJob._claim_and_run_loop(db_name)
        except BadVersionError:
            _logger.warning(
                "Skipping database %s as its base version is not current.", db_name
            )
        except psycopg.errors.UndefinedTable:
            # ir_job does not exist: pre-19.0-irjob database or not an Odoo
            # database at all — nothing to process either way.
            _logger.debug("No ir_job table on database %s.", db_name)
        except db.PoolError:
            _logger.info("Skipping database %s: could not connect.", db_name)
        except Exception:
            _logger.exception("Unexpected exception in job queue for %s:", db_name)
        finally:
            if hasattr(threading.current_thread(), "dbname"):
                del threading.current_thread().dbname

    @staticmethod
    def _claim_and_run_loop(db_name: str) -> None:
        """Drain ready jobs: claim → lock → commit → execute → finalize."""
        registry = Registry(db_name).check_signaling()
        worker_ident = f"{socket.gethostname()}:{os.getpid()}"
        with registry.cursor() as cr:
            while True:
                job = IrJob._claim_next(cr, worker_ident)
                if job is None:
                    cr.rollback()  # release the claim advisory xact-lock
                    break
                # Session-level liveness lock, taken BEFORE the claim commits:
                # once 'started' is visible to reapers, the lock is already
                # held, so there is no window in which a live job looks dead.
                cr.execute(
                    SQL("SELECT pg_advisory_lock(%s)", _advisory_key_sql(job["id"]))
                )
                cr.commit()
                try:
                    # Dispatched through the registry class so per-database
                    # overrides of _run_claimed apply.
                    registry[IrJob._name]._run_claimed(cr, job)
                    cr.commit()
                except Exception as exc:
                    cr.rollback()
                    if not isinstance(exc, RetryableJobError):
                        _logger.exception(
                            "Job %s (%s.%s) failed",
                            job["id"],
                            job["model_name"],
                            job["method_name"],
                        )
                    # Registry dispatch: per-database overrides of the failure
                    # recording (and its _notify_failed hook) apply.
                    registry[IrJob._name]._record_failure(cr, job, exc)
                    cr.commit()
                finally:
                    cr.execute(
                        SQL(
                            "SELECT pg_advisory_unlock(%s)",
                            _advisory_key_sql(job["id"]),
                        )
                    )

    @staticmethod
    def _claim_next(cr, worker_ident: str) -> dict[str, Any] | None:
        """Atomically claim the next ready job, or return ``None``.

        The per-database advisory xact-lock serializes concurrent claims:
        ``SKIP LOCKED`` alone cannot prevent two workers from both observing
        a channel below capacity and over-admitting.  The lock is released at
        the caller's next commit/rollback and claims take microseconds, so
        contention is negligible.  A channel with no ``ir_job_channel`` row
        has an implicit capacity of 1.
        """
        cr.execute("SELECT pg_advisory_xact_lock(hashtextextended('ir_job_claim', 0))")
        cr.execute(
            SQL(
                """
                UPDATE ir_job
                SET state = 'started',
                    started_at = (now() AT TIME ZONE 'UTC'),
                    worker_ident = %s,
                    write_date = (now() AT TIME ZONE 'UTC')
                WHERE id = (
                    SELECT j.id
                    FROM ir_job j
                    WHERE j.state = 'pending'
                      AND (j.eta IS NULL OR j.eta <= (now() AT TIME ZONE 'UTC'))
                      AND (SELECT count(*) FROM ir_job b
                           WHERE b.channel = j.channel AND b.state = 'started')
                          < COALESCE((SELECT c.capacity FROM ir_job_channel c
                                      WHERE c.name = j.channel AND c.active), 1)
                    ORDER BY j.priority, j.create_date, j.id
                    LIMIT 1
                    FOR NO KEY UPDATE SKIP LOCKED
                )
                RETURNING id, uuid, channel, priority, model_name, method_name,
                          record_ids, args, kwargs, user_id, company_id,
                          context, retry, max_retries
                """,
                worker_ident,
            )
        )
        row = cr.fetchone()
        if row is None:
            return None
        return dict(zip([d.name for d in cr.description], row, strict=True))

    @staticmethod
    def _run_claimed(cr, job: dict[str, Any]) -> None:
        """Execute a claimed job and mark it done in the SAME transaction.

        Atomic completion: the business writes and ``state = 'done'`` commit
        together (in the caller), so a crash between them is impossible —
        re-execution can only happen when the effects were rolled back too.
        Raises on business failure; the caller rolls back and records it.
        """
        env = api.Environment(cr, job["user_id"], dict(job["context"] or {}))
        records = env[job["model_name"]].browse(job["record_ids"] or [])
        func = getattr(type(records), job["method_name"], None)
        if getattr(func, "_job_config", None) is None:
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
                " write_date = (now() AT TIME ZONE 'UTC')"
                " WHERE id = %s AND state = 'started'",
                job["id"],
            )
        )
        # Release dependents in the SAME transaction: completion and the
        # promotion of waiting jobs are atomic.  The worker's claim loop
        # picks promoted jobs up immediately; the postcommit NOTIFY covers
        # the manual-run path and other instances.
        released = IrJob._release_dependents(cr, job["id"])
        if released:
            db_name = cr.dbname
            cr.postcommit.add(lambda: IrJob._notify_workers(db_name))
        _logger.info("Job %s: done", job["id"])

    @classmethod
    def _record_failure(cls, cr, job: dict[str, Any], exc: BaseException) -> None:
        """Requeue with backoff while the retry budget lasts, else fail.

        Runs on a fresh transaction (the caller rolled the business one back).
        Every exception consumes a retry; ``RetryableJobError`` only differs
        in that it may carry an explicit delay and is not logged as an error.
        A classmethod (not staticmethod) so the registry dispatch in
        ``_claim_and_run_loop`` lets per-database overrides of
        ``_notify_failed`` apply.
        """
        retry = job["retry"]
        if retry < job["max_retries"]:
            delay = getattr(exc, "seconds", None) or min(
                RETRY_BACKOFF_BASE_S * 2**retry, RETRY_BACKOFF_MAX_S
            )
            cr.execute(
                SQL(
                    """
                    UPDATE ir_job
                    SET state = 'pending', retry = retry + 1,
                        eta = (now() AT TIME ZONE 'UTC') + %s * interval '1 second',
                        exc_name = %s, exc_message = %s, exc_info = %s,
                        started_at = NULL, worker_ident = NULL,
                        write_date = (now() AT TIME ZONE 'UTC')
                    WHERE id = %s AND state = 'started'
                    """,
                    delay,
                    type(exc).__name__,
                    str(exc)[:1000],
                    traceback.format_exc(),
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
                    traceback.format_exc(),
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
        """
        cr.execute(
            "SELECT id, retry, max_retries FROM ir_job"
            " WHERE state = 'started' AND started_at <"
            " (now() AT TIME ZONE 'UTC') - %s * interval '1 second'",
            (DEAD_JOB_GRACE_S,),
        )
        for job_id, retry, max_retries in cr.fetchall():
            cr.execute(
                SQL("SELECT pg_try_advisory_lock(%s)", _advisory_key_sql(job_id))
            )
            if not cr.fetchone()[0]:
                continue  # still alive and running
            try:
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
                _logger.warning("Job %s: reaped from a dead worker", job_id)
            finally:
                cr.execute(
                    SQL("SELECT pg_advisory_unlock(%s)", _advisory_key_sql(job_id))
                )

    # ------------------------------------------------------------------
    # Dependency graph resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _release_dependents(cr, job_id: int) -> int:
        """Promote ``wait_deps`` dependents of ``job_id`` whose every
        dependency is now done.  Returns the number of promoted jobs.

        Called inside the completing job's transaction, after its own row
        turned ``done`` (visible in-snapshot), so promotion is atomic with
        completion.
        """
        cr.execute(
            SQL(
                """
                UPDATE ir_job d
                SET state = 'pending', write_date = (now() AT TIME ZONE 'UTC')
                WHERE d.state = 'wait_deps'
                  AND d.id IN (SELECT job_id FROM ir_job_dependency
                               WHERE depends_on_id = %s)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ir_job_dependency dd
                      JOIN ir_job pj ON pj.id = dd.depends_on_id
                      WHERE dd.job_id = d.id AND pj.state != 'done'
                  )
                """,
                job_id,
            )
        )
        return cr.rowcount

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
        """
        cr.execute(
            """
            UPDATE ir_job d
            SET state = 'pending', write_date = (now() AT TIME ZONE 'UTC')
            WHERE d.state = 'wait_deps'
              AND NOT EXISTS (
                  SELECT 1
                  FROM ir_job_dependency dd
                  JOIN ir_job pj ON pj.id = dd.depends_on_id
                  WHERE dd.job_id = d.id AND pj.state != 'done'
              )
            """
        )
        promoted = cr.rowcount
        cr.execute(
            "SELECT DISTINCT depends_on_id FROM ir_job_dependency d"
            " JOIN ir_job pj ON pj.id = d.depends_on_id"
            " WHERE pj.state IN ('failed', 'cancelled')"
        )
        dead = [r[0] for r in cr.fetchall()]
        if dead:
            IrJob._cancel_dependents(cr, dead)
        if promoted:
            _logger.info("Promoted %s job(s) whose dependencies completed", promoted)

    # ------------------------------------------------------------------
    # User-facing helpers
    # ------------------------------------------------------------------

    @api.depends("model_name", "method_name")
    def _compute_display_name(self) -> None:
        for job in self:
            job.display_name = f"{job.model_name}.{job.method_name} (#{job.id})"

    def action_run_now(self) -> None:
        """Execute a pending job immediately, in the current transaction.

        The ops "Run Manually" button: claims the job by id (ignoring its
        ``eta`` and — deliberately, like ``ir.cron``'s direct trigger — the
        channel capacity) and runs it inline.  On success the job commits
        ``done`` with the request; on failure the exception propagates to the
        user and the whole transaction rolls back, leaving the job pending
        and untouched.
        """
        self.ensure_one()
        self.browse().check_access("write")
        self.env.flush_all()
        cr = self.env.cr
        cr.execute(
            SQL(
                """
                UPDATE ir_job
                SET state = 'started',
                    started_at = (now() AT TIME ZONE 'UTC'),
                    worker_ident = %s,
                    write_date = (now() AT TIME ZONE 'UTC')
                WHERE id = %s AND state = 'pending'
                RETURNING id, uuid, channel, priority, model_name, method_name,
                          record_ids, args, kwargs, user_id, company_id,
                          context, retry, max_retries
                """,
                f"manual:{self.env.uid}",
                self.id,
            )
        )
        row = cr.fetchone()
        if row is None:
            raise UserError(self.env._("Only pending jobs can be run manually."))
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
        """
        self.browse().check_access("write")
        for job in self:
            if job.state not in (FAILED, CANCELLED):
                raise UserError(
                    self.env._("Only failed or cancelled jobs can be requeued.")
                )
        for job in self:
            waiting = any(dep.state != DONE for dep in job.depends_on_ids)
            job.sudo().write(
                {
                    "state": WAIT_DEPS if waiting else PENDING,
                    "retry": 0,
                    "eta": False,
                    "done_at": False,
                }
            )
        self.env.cr.postcommit.add(self._notifydb)

    def action_cancel(self) -> None:
        """Cancel waiting/pending jobs (started jobs cannot be interrupted).

        Waiting dependents of a cancelled job are cascade-cancelled too —
        they could never start otherwise.
        """
        self.browse().check_access("write")
        for job in self:
            if job.state not in (WAIT_DEPS, PENDING):
                raise UserError(
                    self.env._("Only waiting or pending jobs can be cancelled.")
                )
        self.sudo().write({"state": CANCELLED, "done_at": fields.Datetime.now()})
        self.env.flush_all()
        type(self)._cancel_dependents(self.env.cr, self.ids)
