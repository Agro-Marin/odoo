import logging
import math
import os
import threading
import time
import typing
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Self

import psycopg
import psycopg.errors
from dateutil.relativedelta import relativedelta

from odoo import api, db, fields, models
from odoo.api import ValuesType
from odoo.exceptions import LockError, UserError
from odoo.http import serialize_exception
from odoo.libs.constants import GC_UNLINK_LIMIT
from odoo.modules import Manifest
from odoo.modules.loading import reset_modules_state
from odoo.modules.registry import Registry
from odoo.tools import SQL, str2bool

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from odoo.db import BaseCursor

_logger = logging.getLogger(__name__)

# In psycopg 3, class-40 (Transaction Rollback) errors are flat siblings under
# OperationalError — unlike psycopg 2 where they formed a hierarchy.  Catch them
# all explicitly so that ``except _TRANSACTION_ROLLBACK_ERRORS`` works like the
# old ``except TransactionRollback`` did.
_TRANSACTION_ROLLBACK_ERRORS = (
    psycopg.errors.TransactionRollback,  # 40000
    psycopg.errors.SerializationFailure,  # 40001
    psycopg.errors.DeadlockDetected,  # 40P01
    psycopg.errors.TransactionIntegrityConstraintViolation,  # 40002
    psycopg.errors.StatementCompletionUnknown,  # 40003
)

BASE_VERSION = Manifest.for_addon("base")["version"]
# How long ready jobs may keep failing while modules are stuck in a
# transient ``to install/upgrade/remove`` state before we assume the state
# is a leftover zombie and force ``reset_modules_state`` (see
# ``_check_modules_state``). Long enough to outlast a legitimate install.
MAX_FAIL_TIME = timedelta(hours=5)
MIN_RUNS_PER_JOB = 10
MIN_TIME_PER_JOB = 10  # seconds
CONSECUTIVE_TIMEOUT_FOR_FAILURE = 3
MIN_FAILURE_COUNT_BEFORE_DEACTIVATION = 5
MIN_DELTA_BEFORE_DEACTIVATION = timedelta(days=7)
# crons must satisfy both minimum thresholds before deactivation
# Autovacuum retention windows: how long ``ir.cron.trigger`` rows (of inactive
# crons) and ``ir.cron.progress`` rows are kept before garbage collection.
TRIGGER_RETENTION_PERIOD = timedelta(weeks=1)
PROGRESS_RETENTION_PERIOD = timedelta(weeks=1)

# custom function to call instead of default PostgreSQL's `pg_notify`
ODOO_NOTIFY_FUNCTION = os.getenv("ODOO_NOTIFY_FUNCTION", "pg_notify")
# Force a cron-worker wake-up (``_notifydb``) on every ir.cron change and every
# trigger creation, regardless of ``call_at``. Read once at import like
# ``ODOO_NOTIFY_FUNCTION``: this is a deployment switch, never toggled at runtime.
# Parsed through ``str2bool`` so that the documented off-values (``0``/``false``/
# ``no``/``off``) actually disable it -- plain ``bool(os.getenv(...))`` treats any
# non-empty string, including ``"0"``, as true. Unset/empty/unrecognised => off.
NOTIFY_CRON_CHANGES = str2bool(os.getenv("ODOO_NOTIFY_CRON_CHANGES", ""), default=False)


class BadVersionError(Exception):
    pass


class BadModuleStateError(Exception):
    pass


class CompletionStatus(StrEnum):
    """Completion status reported by a cron job after each execution."""

    FULLY_DONE = "fully done"
    PARTIALLY_DONE = "partially done"
    FAILED = "failed"


class IrCron(models.Model):
    """Model describing cron jobs (also called actions or tasks)."""

    # TODO: perhaps in the future we could consider a flag on ir.cron jobs
    # that would cause database wake-up even if the database has not been
    # loaded yet or was already unloaded (e.g. 'force_db_wakeup' or something)
    # See also odoo.cron
    _name = "ir.cron"
    _order = "cron_name, id"
    _description = "Scheduled Actions"
    _allow_sudo_commands = False

    _inherits = {"ir.actions.server": "ir_actions_server_id"}

    ir_actions_server_id = fields.Many2one(
        "ir.actions.server",
        "Server action",
        index=True,
        delegate=True,
        ondelete="restrict",
        required=True,
    )
    cron_name = fields.Char("Name", compute="_compute_cron_name", store=True)
    user_id = fields.Many2one(
        "res.users",
        string="Scheduler User",
        default=lambda self: self.env.user,
        required=True,
    )
    active = fields.Boolean(default=True)
    interval_number = fields.Integer(
        default=1, help="Repeat every x.", required=True, aggregator="avg"
    )
    interval_type = fields.Selection(
        [
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        string="Interval Unit",
        default="months",
        required=True,
    )
    nextcall = fields.Datetime(
        string="Next Execution Date",
        required=True,
        default=fields.Datetime.now,
        help="Next planned execution date for this job.",
    )
    lastcall = fields.Datetime(
        string="Last Execution Date",
        help="Previous time the cron ran successfully, provided to the job through the context on the `lastcall` key",
    )
    priority = fields.Integer(
        default=5,
        aggregator=None,
        help="The priority of the job, as an integer: 0 means higher priority, 10 means lower priority.",
    )
    failure_count = fields.Integer(
        default=0,
        help="The number of consecutive failures of this job. It is automatically reset on success.",
    )
    first_failure_date = fields.Datetime(
        string="First Failure Date",
        help="The first time the cron failed. It is automatically reset on success.",
    )

    _check_strictly_positive_interval = models.Constraint(
        "CHECK(interval_number > 0)",
        "The interval number must be a strictly positive number.",
    )

    @api.depends("ir_actions_server_id.name")
    def _compute_cron_name(self) -> None:
        for cron in self.with_context(lang="en_US"):
            cron.cron_name = cron.ir_actions_server_id.name

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            vals["usage"] = "ir_cron"
        if NOTIFY_CRON_CHANGES:
            self.env.cr.postcommit.add(self._notifydb)
        return super().create(vals_list)

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        # only 'code' state is supported for cron job so set it as default
        model = self
        if not model.env.context.get("default_state"):
            model = model.with_context(default_state="code")
        return super(IrCron, model).default_get(fields)

    def method_direct_trigger(self) -> dict[str, Any] | bool:
        """Run the CRON job in the current (HTTP) thread.

        The job is still ran as it would be by the scheduler: a new cursor
        is used for the execution of the job.

        :raises UserError: when the job is already running
        """
        self.ensure_one()
        self.browse().check_access("write")
        # cron will be run in a separate transaction, flush before and
        # invalidate because data will be changed by that transaction
        self.env.invalidate_all(flush=True)
        cron_cr = self.env.cr
        job = self._acquire_one_job(cron_cr, self.id, include_not_ready=True)
        if not job:
            raise UserError(self.env._("Job '%s' already executing", self.name))

        # `_run_job` records the server action's exception (if any) on the job
        # dict rather than us having to scrape it back out of the log stream.
        self._process_job(cron_cr, job)
        if exception := job.get("run_exception"):
            e = RuntimeError()
            e.__cause__ = exception
            error = {
                "code": 0,  # we don't care of this code
                "message": "Odoo Server Error",
                "data": serialize_exception(e),
            }
            return {
                "type": "ir.actions.client",
                "tag": "display_exception",
                "params": error,
            }
        return True

    @staticmethod
    def _process_jobs(db_name: str) -> None:
        """Execute every job ready to be run on this database."""
        try:
            db_conn = db.db_connect(db_name)
            threading.current_thread().dbname = db_name
            with db_conn.cursor() as cron_cr:
                # These pre-flight checks intentionally run on the base ``IrCron``
                # class with a raw cursor, NOT on the registry model: they gate
                # whether the DB is even safe to load (right code version, no
                # module mid-install). Loading ``Registry(db_name)`` to honour a
                # per-DB override here is exactly what we must avoid on a
                # wrong-version or migrating database -- so ``_check_version`` /
                # ``_get_all_ready_jobs`` / ``_check_modules_state`` are *not*
                # override points. Only ``_process_jobs_loop`` (below) loads the
                # registry and dispatches ``_process_job`` through it, so that is
                # where per-DB behaviour may be overridden.
                cls = IrCron
                cls._check_version(cron_cr)
                jobs = cls._get_all_ready_jobs(cron_cr)
                if not jobs:
                    return
                cls._check_modules_state(cron_cr, jobs)
                cls._process_jobs_loop(cron_cr, job_ids=[job["id"] for job in jobs])
        except BadVersionError:
            _logger.warning(
                "Skipping database %s as its base version is not %s.",
                db_name,
                BASE_VERSION,
            )
        except BadModuleStateError:
            _logger.warning(
                "Skipping database %s because of modules to install/upgrade/remove.",
                db_name,
            )
        except psycopg.errors.UndefinedTable:
            # The table ir_cron does not exist; this is probably not an Odoo database.
            # NOTE: UndefinedTable is a subclass of ProgrammingError, so this
            # specific handler MUST stay before the `except psycopg.ProgrammingError`
            # re-raise below — reordering would turn this warning into a hard error.
            _logger.warning("Tried to poll an undefined table on database %s.", db_name)
        except db.PoolError:
            # Connection pool could not reach the database (e.g. it was
            # just dropped).  No point retrying until the DB list refreshes.
            _logger.info("Skipping database %s: could not connect.", db_name)
        except psycopg.ProgrammingError:
            raise
        except Exception:
            _logger.exception("Unexpected exception in cron for database %s:", db_name)
        finally:
            if hasattr(threading.current_thread(), "dbname"):
                del threading.current_thread().dbname

    @staticmethod
    def _process_jobs_loop(cron_cr: BaseCursor, *, job_ids: Iterable[int] = ()) -> None:
        """Process ready jobs to run on this database.

        The `cron_cr` is used to lock the currently processed job and relased
        by committing after each job.
        """
        db_name = cron_cr.dbname
        for job_id in job_ids:
            try:
                job = IrCron._acquire_one_job(cron_cr, job_id)
            except _TRANSACTION_ROLLBACK_ERRORS:
                cron_cr.rollback()
                _logger.debug(
                    "job %s has been processed by another worker, skip", job_id
                )
                continue
            if not job:
                _logger.debug(
                    "job %s is being processed by another worker, skip", job_id
                )
                continue
            _logger.debug("job %s acquired", job_id)
            # take into account overridings of _process_job() on that database
            registry = Registry(db_name).check_signaling()
            try:
                registry[IrCron._name]._process_job(cron_cr, job)
                cron_cr.commit()
            except Exception:
                # An infra-level failure (e.g. a _reschedule_*/_add_progress
                # SQL error, not the action itself — that is caught in
                # _run_job) must not abandon the rest of the cycle. Roll back
                # to release the lock and let this job retry next cycle, then
                # continue with the remaining ready jobs.
                cron_cr.rollback()
                _logger.exception("job %s failed to process, skip", job_id)
                continue
            _logger.debug("job %s updated and released", job_id)

    @staticmethod
    def _check_version(cron_cr: BaseCursor) -> None:
        """Ensure the code version matches the database version"""
        cron_cr.execute("""
            SELECT db_version
            FROM ir_module_module
             WHERE name='base'
        """)
        # A missing ``base`` row (row is None) is as much a "not-ready" signal as a
        # NULL ``db_version``; treat both as BadModuleStateError rather than letting
        # the tuple-unpack raise an opaque TypeError up through ``_process_jobs``.
        row = cron_cr.fetchone()
        if row is None or row[0] is None:
            raise BadModuleStateError
        if row[0] != BASE_VERSION:
            raise BadVersionError

    @staticmethod
    def _check_modules_state(cr: BaseCursor, jobs: list[dict[str, Any]]) -> None:
        """Ensure no module is installing, upgrading or removing"""
        cr.execute(
            """
            SELECT COUNT(*)
            FROM ir_module_module
            WHERE state LIKE %s
            """,
            ["to %"],
        )
        (changes,) = cr.fetchone()
        if not changes:
            return

        if not jobs:
            raise BadModuleStateError

        # use the max(job['nextcall'], job['write_date']) to avoid the cron
        # reset_module_state for an ongoing module installation process
        # right after installing a module with an old 'nextcall' cron in data
        oldest = min(
            max(job["nextcall"], job["write_date"] or job["nextcall"]) for job in jobs
        )
        # Use the DB transaction clock (naive UTC) for parity with ``nextcall`` /
        # ``write_date`` and with the other time comparisons in this model.
        if cr.now() - oldest < MAX_FAIL_TIME:
            raise BadModuleStateError

        # the cron execution failed around MAX_FAIL_TIME * 60 times (1 failure
        # per minute for 5h) in which case we assume that the crons are stuck
        # because the db has zombie states and we force a call to
        # reset_module_states.
        reset_modules_state(cr.dbname)

    @staticmethod
    def _get_ready_sql_condition(cr: BaseCursor) -> SQL:
        # Correlated EXISTS rather than ``id IN (SELECT cron_id ...)``: the IN
        # form makes PostgreSQL hash the *entire* due-trigger set on every
        # evaluation -- including when acquiring a single job by id in
        # ``_acquire_one_job`` -- whereas EXISTS short-circuits on the first
        # matching trigger for the row at hand. Under a trigger backlog (e.g.
        # many partially-done jobs each re-inserting an ASAP trigger) this is
        # the difference between scanning all of ir_cron_trigger per acquire
        # and a point lookup on its cron_id index.
        return SQL(
            """
            active IS TRUE
            AND (nextcall <= %(now)s
                OR EXISTS (
                    SELECT 1
                    FROM ir_cron_trigger
                    WHERE ir_cron_trigger.cron_id = ir_cron.id
                      AND call_at <= %(now)s
                )
            )
        """,
            now=cr.now(),
        )

    @staticmethod
    def _get_all_ready_jobs(cr: BaseCursor) -> list[dict[str, Any]]:
        """Return a list of all jobs that are ready to be executed.

        Only ``id`` (dispatched to ``_process_jobs_loop``) plus ``nextcall`` and
        ``write_date`` (used by ``_check_modules_state``) are consumed here, so we
        select those three rather than ``SELECT *``: the full, up-to-date row is
        re-read under the row lock in ``_acquire_one_job`` right before each job
        runs anyway, making a wide fetch of the whole ready set pure overhead.
        """
        cr.execute(
            SQL(
                """
            SELECT id, nextcall, write_date
            FROM ir_cron
            WHERE %s
            ORDER BY failure_count, priority, id
        """,
                IrCron._get_ready_sql_condition(cr),
            )
        )
        return cr.dictfetchall()

    @staticmethod
    def _acquire_one_job(
        cr: BaseCursor, job_id: int, *, include_not_ready: bool = False
    ) -> dict[str, Any] | None:
        """
        Acquire for update the job with id ``job_id``.

        The job should not have been processed yet by the current
        worker. Another worker may process the job again, may that job
        become ready again quickly enough (e.g. self-triggering, high
        frequency, or partially done jobs).

        Note: It is possible that this function raises a
              ``psycopg.errors.SerializationFailure`` in case the job
              has been processed in another worker. In such case it is
              advised to roll back the transaction and to go on with the
              other jobs.
        """

        # The query must make sure that (i) two cron workers cannot
        # process a given job at a same time. The query must also make
        # sure that (ii) a job already processed in another worker
        # should not be processed again by this one (or at least not
        # before the job becomes ready again).
        #
        # (i) is implemented via `FOR NO KEY UPDATE SKIP LOCKED`, each
        # worker just acquire one available job at a time and lock it so
        # the other workers don't select it too.
        # (ii) is implemented via the `WHERE` statement, when a job has
        # been processed and is fully done, its nextcall is updated to a
        # date in the future and the optional triggers are removed. In
        # case a job has only been partially done, the job is left ready
        # to be acquired again by another cron worker.
        #
        # An `UPDATE` lock type is the strongest row lock, it conflicts
        # with ALL other lock types. Among them the `KEY SHARE` row lock
        # which is implicitly acquired by foreign keys to prevent the
        # referenced record from being removed while in use. Because we
        # never delete acquired cron jobs, foreign keys are safe to
        # concurrently reference cron jobs. Hence, the `NO KEY UPDATE`
        # row lock is used, it is a weaker lock that does conflict with
        # everything BUT `KEY SHARE`.
        #
        # Learn more: https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS

        where_clause = SQL("id = %s", job_id)
        if not include_not_ready:
            where_clause = SQL(
                "%s AND %s", where_clause, IrCron._get_ready_sql_condition(cr)
            )
        query = SQL(
            """
            WITH last_cron_progress AS (
                SELECT id as progress_id, cron_id, timed_out_counter, done, remaining
                FROM ir_cron_progress
                WHERE cron_id = %(cron_id)s
                ORDER BY id DESC
                LIMIT 1
            )
            SELECT *
            FROM ir_cron
            LEFT JOIN last_cron_progress lcp ON lcp.cron_id = ir_cron.id
            WHERE %(where)s
            FOR NO KEY UPDATE OF ir_cron SKIP LOCKED
        """,
            cron_id=job_id,
            where=where_clause,
        )
        try:
            cr.execute(query, log_exceptions=False)
        except _TRANSACTION_ROLLBACK_ERRORS:
            # A serialization error can occur when another cron worker
            # commits the new `nextcall` value of a cron it just ran and
            # that commit occurred just before this query. The error is
            # genuine and the job should be skipped in this cron worker.
            raise
        except psycopg.Error as exc:
            _logger.error("bad query: %s\nERROR: %s", query, exc)
            raise

        job = cr.dictfetchone()

        if not job:  # Job is already taken
            return None

        # `progress_id` is intentionally NOT coalesced: the timeout branch in
        # `_process_job` (UPDATE ... WHERE id = %(progress_id)s) is only
        # reached when `timed_out_counter >= CONSECUTIVE_TIMEOUT_FOR_FAILURE`,
        # which implies a progress row
        # (hence a non-NULL `progress_id`) exists. A NULL would yield a
        # harmless no-op UPDATE.
        for field_name in ("done", "remaining", "timed_out_counter"):
            job[field_name] = job[field_name] or 0
        return job

    def _notify_admin(self, message: str) -> None:
        """
        Notify ``message`` to some administrator.

        The base implementation only logs a warning; override it with an
        actual communication mechanism.
        """
        _logger.warning(message)

    @classmethod
    def _process_job(cls, cron_cr: BaseCursor, job: dict[str, Any]) -> None:
        """
        Execute the cron's server action in a dedicated transaction.

        In case the previous process actually timed out, the cron's
        server action is not executed and the cron is considered
        ``'failed'``.

        The server action can use the progress API via the method
        :meth:`_commit_progress` to report how many records are done
        in each batch.
        Those progress notifications are used to determine the job's
        ``CompletionStatus`` and to determine the next time the cron
        will be executed:

        - ``'fully done'``: the cron is rescheduled later, it'll be
          executed again after its regular time interval or upon a new
          trigger.

        - ``'partially done'``: the cron is rescheduled ASAP, it'll be
          executed again by this or another cron worker once the other
          ready cron jobs have been executed.

        - ``'failed'``: the cron is deactivated if it failed too many
          times over a given time span; otherwise it is rescheduled
          later.
        """
        env = api.Environment(cron_cr, job["user_id"], {})
        ir_cron = env[cls._name]

        ir_cron._clear_schedule(job)
        failed_by_timeout = (
            job["timed_out_counter"] >= CONSECUTIVE_TIMEOUT_FOR_FAILURE
            and not job["done"]
        )

        if not failed_by_timeout:
            status = cls._run_job(job)
        else:
            status = CompletionStatus.FAILED
            cron_cr.execute(
                """
                UPDATE ir_cron_progress
                SET timed_out_counter = 0
                WHERE id = %s
            """,
                (job["progress_id"],),
            )
            _logger.error("Job %r (%s) timed out", job["cron_name"], job["id"])

        ir_cron._update_failure_count(job, status)

        if status in (CompletionStatus.FULLY_DONE, CompletionStatus.FAILED):
            ir_cron._reschedule_later(job)
        elif status == CompletionStatus.PARTIALLY_DONE:
            ir_cron._reschedule_asap(job)
            if NOTIFY_CRON_CHANGES:
                cron_cr.postcommit.add(ir_cron._notifydb)  # See: `_notifydb`
        else:
            raise RuntimeError(f"unreachable {status=}")

    @staticmethod
    def _classify_outcome(
        *, success: bool, done: int, remaining: int
    ) -> CompletionStatus | None:
        """Classify a single callback iteration's result.

        Pure function of the three observable signals of one pass, with no
        side effects, so the whole decision table can be unit-tested in
        isolation from the DB, the loop and the progress record:

        - ``success``: the server action returned without raising;
        - ``done``: records processed so far (this run);
        - ``remaining``: records the action still reports as pending.

        Returns the terminal :class:`CompletionStatus`, or ``None`` to keep
        looping (either the action made partial progress, or it failed but
        committed some progress and may recover on the next pass).
        """
        match (success, bool(done), bool(remaining)):
            case (False, True, True):
                # Failed, yet committed some progress this pass; retry.
                return None
            case (False, _, _):
                # Failed with nothing committed this pass.
                return CompletionStatus.FAILED
            case (True, _, False):
                # Nothing left to process (no progress API, or remaining == 0).
                return CompletionStatus.FULLY_DONE
            case (True, False, _):
                # Records remain but none were processed this pass.
                return CompletionStatus.PARTIALLY_DONE
            case _:  # (True, True, True)
                # Processed some, more remain; keep looping.
                return None

    @staticmethod
    def _should_continue_run(
        *,
        status: CompletionStatus | None,
        loop_count: int,
        now: float,
        end_time: float,
    ) -> bool:
        """Whether :meth:`_run_job` should execute another pass.

        Pure predicate over the loop's observable state, so the batching policy
        can be unit-tested without a DB or a real clock:

        - stop immediately once the action reached a terminal ``status``;
        - otherwise keep looping until BOTH the minimum pass count
          (``MIN_RUNS_PER_JOB``) has been reached AND the time budget
          (``MIN_TIME_PER_JOB``, materialised here as ``end_time``) is spent.

        ``now`` and ``end_time`` are ``time.monotonic()`` readings (seconds).
        """
        if status is not None:
            return False
        return loop_count < MIN_RUNS_PER_JOB or now < end_time

    @classmethod
    def _run_job(cls, job: dict[str, Any]) -> CompletionStatus:
        """
        Execute the job's server action multiple times until it
        completes. The completion status is returned.

        It is considered completed when either:

        - the server action doesn't use the progress API, or returned
          and notified that all records has been processed: ``'fully done'``;

        - the server action returned and notified that there are
          remaining records to process, but this cron worker ran this
          server action 10 times already: ``'partially done'``;

        - the server action was able to commit and notify some work done,
          but later crashed due to an exception: ``'partially done'``;

        - the server action failed due to an exception and no progress
          was notified: ``'failed'``.
        """
        timed_out_counter = job["timed_out_counter"]

        with cls.pool.cursor() as job_cr:
            start_time = time.monotonic()
            env = api.Environment(
                job_cr,
                job["user_id"],
                {
                    "lastcall": job["lastcall"],
                    "cron_id": job["id"],
                    "cron_end_time": start_time + MIN_TIME_PER_JOB,
                },
            )
            cron = env[cls._name].browse(job["id"])

            status = None
            loop_count = 0
            done, remaining = 0, 0
            _logger.info("Job %r (%s) starting", job["cron_name"], job["id"])

            if not env.user.active and env.user != env.ref("base.user_root"):
                _logger.warning(
                    "Forbidden server action %r executed while the user %s is archived.",
                    job["cron_name"],
                    env.user.login,
                )
                # Setting a terminal status here short-circuits the run loop
                # below (its `while status is None` guard), so the action is
                # never executed for an archived user.
                status = CompletionStatus.FAILED

            # stop after MIN_RUNS_PER_JOB runs and MIN_TIME_PER_JOB seconds, or
            # upon full completion or failure
            while cls._should_continue_run(
                status=status,
                loop_count=loop_count,
                now=time.monotonic(),
                end_time=env.context["cron_end_time"],
            ):
                # Each pass deliberately gets its OWN ir.cron.progress row (not a
                # single reused row): the row committed just before the callback
                # is the crash-survival record whose ``timed_out_counter`` /
                # ``done`` the next acquire reads to decide ``failed_by_timeout``
                # -- a fresh row makes "the LAST attempt processed nothing"
                # detectable -- and the per-pass ``done`` values form the
                # throughput audit trail (their sum is the run's total work).
                # This costs one INSERT per real work batch; do not collapse it
                # into an UPDATE-in-place without preserving both properties.
                cron, progress = cron._add_progress(timed_out_counter=timed_out_counter)
                job_cr.commit()

                success = False
                try:
                    # signaling check and commit is done inside `_callback`
                    cron._callback(job["cron_name"], job["ir_actions_server_id"])
                    success = True
                except Exception as exc:
                    _logger.exception(
                        "Job %r (%s) server action #%s failed",
                        job["cron_name"],
                        job["id"],
                        job["ir_actions_server_id"],
                    )
                    # Surface the first failure to `method_direct_trigger`
                    # without it having to scrape the log stream.
                    job.setdefault("run_exception", exc)
                finally:
                    done, remaining = progress.done, progress.remaining
                    status = cls._classify_outcome(
                        success=success, done=done, remaining=remaining
                    )
                    if status is CompletionStatus.FULLY_DONE and progress.deactivate:
                        # Deactivation requested by the action through
                        # ``_commit_progress(deactivate=True)``. Carried as a
                        # separate flag rather than mutating ``job["active"]``:
                        # the job dict must stay the DB-authoritative row
                        # snapshot that ``_update_failure_count`` compares
                        # against to decide whether an UPDATE is needed at all
                        # -- overwriting ``active`` in place made the requested
                        # deactivation look like "no change" and the write was
                        # silently skipped.
                        job["deactivate"] = True
                    elif status is CompletionStatus.PARTIALLY_DONE and loop_count == 0:
                        # remaining records were reported but none processed on
                        # the very first pass; hopefully transient.
                        _logger.warning(
                            "Job %r (%s) processed no record",
                            job["cron_name"],
                            job["id"],
                        )

                    loop_count += 1
                    progress.timed_out_counter = 0
                    timed_out_counter = 0
                    job_cr.commit()  # ensure we have no leftovers

                    _logger.debug(
                        "Job %r (%s) processed %s records, %s records remaining",
                        job["cron_name"],
                        job["id"],
                        done,
                        remaining,
                    )

            status = status or CompletionStatus.PARTIALLY_DONE
            _logger.info(
                "Job %r (%s) %s (#loop %s; done %s; remaining %s; duration %.2fs)",
                job["cron_name"],
                job["id"],
                status,
                loop_count,
                done,
                remaining,
                time.monotonic() - start_time,
            )

        return status

    @api.model
    def _now(self) -> datetime:
        """The DB transaction clock, truncated to whole seconds.

        Shared by the scheduling writes (``_update_failure_count``,
        ``_clear_schedule``, ``_reschedule_*``) and the trigger path
        (``_trigger``/``_trigger_list``) so they all stamp -- and compare
        against -- the same second-resolution naive-UTC value drawn from the
        database rather than the process wall clock. ``_get_ready_sql_condition``
        (the reader that decides a trigger is due) uses ``cr.now()`` too, so
        producing trigger ``call_at`` values and the "is it due now" cutoff from
        one clock keeps writer and reader consistent even when the app host's
        wall clock differs from the DB's (or is not pinned to UTC because the
        startup ``time.tzset`` monkeypatch is unavailable, e.g. Windows).
        """
        return self.env.cr.now().replace(microsecond=0)

    @api.model
    def _update_failure_count(
        self, job: dict[str, Any], status: CompletionStatus
    ) -> None:
        """
        Update cron ``failure_count`` and ``first_failure_date`` given
        the job's completion status. Deactivate the cron when BOTH the
        counter reaches ``MIN_FAILURE_COUNT_BEFORE_DEACTIVATION`` AND
        the time delta reaches ``MIN_DELTA_BEFORE_DEACTIVATION``.

        On ``'fully done'`` and ``'partially done'``, the counter and
        failure date are reset.

        On ``'failed'`` the counter is increased and the first failure
        date is set if the counter was 0. In case both thresholds are
        reached, ``active`` is set to ``False`` and both values are
        reset.

        When the job requested its own deactivation (``job["deactivate"]``,
        set by :meth:`_run_job` when the action called
        ``_commit_progress(deactivate=True)``), ``active`` is set to
        ``False`` regardless of the completion status.
        """
        if status == CompletionStatus.FAILED:
            now = self._now()
            failure_count = job["failure_count"] + 1
            first_failure_date = job["first_failure_date"] or now
            active = job["active"]
            if (
                failure_count >= MIN_FAILURE_COUNT_BEFORE_DEACTIVATION
                and first_failure_date + MIN_DELTA_BEFORE_DEACTIVATION < now
            ):
                failure_count = 0
                first_failure_date = None
                active = False
                self._notify_admin(
                    self.env._(
                        "Cron job %(name)s (%(id)s) has been deactivated after failing %(count)s times. "
                        "More information can be found in the server logs around %(time)s.",
                        name=repr(job["cron_name"]),
                        id=job["id"],
                        count=MIN_FAILURE_COUNT_BEFORE_DEACTIVATION,
                        time=now,
                    )
                )
        else:
            failure_count = 0
            first_failure_date = None
            active = job["active"]

        if job.get("deactivate"):
            # Self-deactivation requested by the job itself (see `_run_job`).
            active = False

        # The common case is a healthy job succeeding with these values already
        # at their defaults; skip the write (and the resulting dead row) when
        # nothing actually changes. This fires on every successful cron tick.
        # ``job`` still holds the row exactly as read by ``_acquire_one_job``
        # (nothing mutates these three keys), so the comparison is against the
        # actual DB state, not against an in-flight copy.
        if (failure_count, first_failure_date, active) == (
            job["failure_count"],
            job["first_failure_date"],
            job["active"],
        ):
            return

        self.env.cr.execute(
            """
            UPDATE ir_cron
            SET failure_count = %s,
                first_failure_date = %s,
                active = %s
            WHERE id = %s
        """,
            [
                failure_count,
                first_failure_date,
                active,
                job["id"],
            ],
        )

    @api.model
    def _clear_schedule(self, job: dict[str, Any]) -> None:
        """Remove the due triggers for the given job."""
        now = self._now()
        self.env.cr.execute(
            """
            DELETE FROM ir_cron_trigger
            WHERE cron_id = %s
              AND call_at <= %s
        """,
            [job["id"], now],
        )

    @staticmethod
    def _compute_next_call(
        record: models.BaseModel,
        nextcall: datetime,
        now: datetime,
        interval_type: str,
        interval_number: int,
    ) -> datetime:
        """Advance ``nextcall`` by whole intervals until it is past ``now``.

        The interval is added in the scheduler user's timezone (taken from
        ``record``) so that day/week/month schedules keep the same wall-clock
        time across DST transitions -- only the absolute UTC offset shifts.
        Pure with respect to the database: ``record`` is used solely for its
        context timezone, which makes the DST arithmetic unit-testable.

        Iterating one interval at a time is required for that per-step DST
        snapping, which only makes sense for the calendar-length interval
        types (days/weeks/months). Fixed-length intervals (minutes/hours)
        take an arithmetic fast path instead: sub-day schedules have no
        wall-clock time to preserve -- their intent is a fixed absolute
        cadence -- and a long-overdue high-frequency job (e.g. a 1-minute
        cron down for weeks) would otherwise iterate hundreds of thousands
        of steps while holding the acquire row lock.
        """
        if interval_type in ("minutes", "hours"):
            interval = timedelta(**{interval_type: interval_number})
            if nextcall <= now:
                # Same postcondition as the loop below: advance by the
                # smallest whole number of intervals that puts ``nextcall``
                # strictly past ``now``. The loop runs once per pass while
                # ``nextcall <= now``, i.e. ``(now - nextcall) // interval
                # + 1`` times (the ``+ 1`` also covers the boundary
                # ``nextcall == now``, which the loop advances once).
                steps = (now - nextcall) // interval + 1
                nextcall += steps * interval
            return nextcall

        # ``interval_type`` is Selection-constrained to relativedelta's own plural
        # kwargs (minutes/hours/days/weeks/months), so build the delta directly.
        interval = relativedelta(**{interval_type: interval_number})
        while nextcall <= now:
            local = fields.Datetime.context_timestamp(record, nextcall)
            nextcall = (local + interval).astimezone(UTC).replace(tzinfo=None)
        return nextcall

    @api.model
    def _reschedule_later(self, job: dict[str, Any]) -> None:
        """
        Reschedule the job to be executed later, after its regular
        interval or upon a trigger.
        """
        now = self._now()
        nextcall = self._compute_next_call(
            self, job["nextcall"], now, job["interval_type"], job["interval_number"]
        )
        self.env.cr.execute(
            """
            UPDATE ir_cron
            SET nextcall = %s,
                lastcall = %s
            WHERE id = %s
        """,
            [nextcall, now, job["id"]],
        )

    @api.model
    def _reschedule_asap(self, job: dict[str, Any]) -> None:
        """
        Reschedule the job to be executed ASAP, after the other cron
        jobs had a chance to run.
        """
        now = self._now()
        self.env.cr.execute(
            """
            INSERT INTO ir_cron_trigger(call_at, cron_id)
            VALUES (%s, %s)
        """,
            [now, job["id"]],
        )

    def _callback(self, cron_name: str, server_action_id: int) -> None:
        """Run the method associated to a given job. It takes care of logging
        and exception handling. Note that the user running the server action
        is the user calling this method."""
        self.ensure_one()
        try:
            if self.pool is not self.pool.check_signaling():
                # the registry has changed, reload self in the new registry
                self.env.transaction.reset()

            _logger.debug(
                "cron.object.execute(%r, %d, '*', %r, %d)",
                self.env.cr.dbname,
                self.env.uid,
                cron_name,
                server_action_id,
            )
            self.env["ir.actions.server"].browse(server_action_id).run()
            self.env.flush_all()
            self.pool.signal_changes()
            self.env.cr.commit()
        except Exception:
            self.pool.reset_changes()
            self.env.cr.rollback()
            raise

    def _lock_for_update_or_raise(self, *, allow_referencing: bool = False) -> None:
        """Take the row lock guarding against concurrent cron execution, turning
        the ``LockError`` (job currently running) into a user-facing message.
        """
        try:
            self.lock_for_update(allow_referencing=allow_referencing)
        except LockError:
            raise UserError(
                self.env._(
                    "Record cannot be modified right now: "
                    "This cron task is currently being executed and may not be modified "
                    "Please try again in a few minutes"
                )
            ) from None

    def write(self, vals: dict[str, Any]) -> bool:
        self._lock_for_update_or_raise(allow_referencing=True)
        if ("nextcall" in vals or vals.get("active")) and NOTIFY_CRON_CHANGES:
            self.env.cr.postcommit.add(self._notifydb)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_unless_running(self) -> None:
        self._lock_for_update_or_raise()

    @api.model
    def toggle(self, model: str, domain: list[Any]) -> bool:
        # Prevent deactivated cron jobs from being re-enabled through side effects on
        # neutralized databases.
        if self.env["ir.config_parameter"].sudo().get_param("database.is_neutralized"):
            return True

        # Existence check only: bound the count so a large target table doesn't
        # pay for a full COUNT(*) just to yield a boolean.
        active = bool(self.env[model].search_count(domain, limit=1))
        try:
            self.lock_for_update(allow_referencing=True)
        except LockError:
            return True
        return self.write({"active": active})

    def _trigger(
        self, at: datetime | Iterable[datetime] | None = None, *, coalesce: int = 0
    ) -> Any:
        """Schedule a cron job to be executed soon independently of its
        ``nextcall`` field value.

        By default, the cron is scheduled to be executed the next time
        the cron worker wakes up, but the optional `at` argument may be
        given to delay the execution later, with a precision down to 1
        minute.

        The method may be called with a datetime or an iterable of
        datetime. The actual implementation is in :meth:`~._trigger_list`,
        which is the recommended method for overrides.

        :param at:
            When to execute the cron, at one or several moments in time
            instead of as soon as possible.
        :param coalesce: coalescing window in minutes — every trigger is
            shifted to the end of the window, limiting the number or
            frequency of wakeups for less pressing triggers.
        :return: the created triggers records
        """
        if at is None:
            at_list = [self._now()]
        elif isinstance(at, datetime):
            at_list = [at]
        else:
            at_list = list(at)
            if not all(isinstance(item, datetime) for item in at_list):
                raise TypeError("all items in 'at' must be datetime objects")

        if coalesce:
            factor = coalesce * 60
            # `at` values are naive UTC. Tag them UTC explicitly rather than
            # relying on the process TZ being pinned to UTC (which holds on
            # Linux via the startup monkeypatch, but not on platforms without
            # ``time.tzset``), so the epoch round-trip stays UTC-correct.
            at_list = [
                datetime.fromtimestamp(
                    math.ceil(dt.replace(tzinfo=UTC).timestamp() / factor) * factor,
                    UTC,
                ).replace(tzinfo=None)
                for dt in at_list
            ]

        return self._trigger_list(at_list)

    def _trigger_list(self, at_list: list[datetime]) -> Any:
        """
        Implementation of :meth:`~._trigger`.

        :param at_list: Execute the cron later, at precise moments in time.
        :return: the created triggers records
        """
        self.ensure_one()
        now = self._now()

        if not self.sudo().active:
            # skip triggers that would be ignored
            at_list = [at for at in at_list if at > now]

        if not at_list:
            return self.env["ir.cron.trigger"]

        triggers = (
            self.env["ir.cron.trigger"]
            .sudo()
            .create([{"cron_id": self.id, "call_at": at} for at in at_list])
        )
        if _logger.isEnabledFor(logging.DEBUG):
            ats = ", ".join(map(str, at_list))
            _logger.debug(
                "Job %r (%s) will execute at %s", self.sudo().name, self.id, ats
            )

        if min(at_list) <= now or NOTIFY_CRON_CHANGES:
            self.env.cr.postcommit.add(self._notifydb)
        return triggers

    @api.model
    def _notifydb(self) -> None:
        """Wake up the cron workers
        The ODOO_NOTIFY_CRON_CHANGES environment variable allows to force the notifydb on both
        IrCron modification and on trigger creation (regardless of call_at)
        """
        with db.db_connect("postgres").cursor() as cr:
            cr.execute(
                SQL(
                    "SELECT %s('cron_trigger', %s)",
                    SQL.identifier(ODOO_NOTIFY_FUNCTION),
                    self.env.cr.dbname,
                )
            )
        _logger.debug("cron workers notified")

    def _add_progress(
        self, *, timed_out_counter: int | None = None
    ) -> tuple[Self, Any]:
        """
        Create a progress record for the given cron and add it to its
        context.

        :param int | None timed_out_counter: the number of times the cron has
            consecutively timed out
        :return: a pair ``(cron, progress)``, where the progress has
            been injected inside the cron's context
        """
        progress = (
            self.env["ir.cron.progress"]
            .sudo()
            .create(
                [
                    {
                        "cron_id": self.id,
                        "remaining": 0,
                        "done": 0,
                        # we use timed_out_counter + 1 so that if the current execution
                        # times out, the counter already takes it into account
                        "timed_out_counter": (
                            0 if timed_out_counter is None else timed_out_counter + 1
                        ),
                    }
                ]
            )
        )
        return self.with_context(ir_cron_progress_id=progress.id), progress

    @api.model
    def _commit_progress(
        self,
        processed: int = 0,
        *,
        remaining: int | None = None,
        deactivate: bool = False,
    ) -> float:
        """
        Commit and log progress for the batch from a cron function.

        The number of items processed is added to the current done count.
        If you don't specify a remaining count, the number of items processed
        is subtracted from the existing remaining count.

        If called from outside the cron job, the progress function call will
        just commit.

        :param processed: number of processed items in this step
        :param remaining: set the remaining count to the given count
        :param deactivate: deactivate the cron after running it
        :return: remaining time (seconds) for the cron run
        """
        ctx = self.env.context
        progress = (
            self.env["ir.cron.progress"].sudo().browse(ctx.get("ir_cron_progress_id"))
        )
        if not progress:
            # not called during a cron, just commit
            self.env.cr.commit()
            return float("inf")
        if processed < 0:
            raise ValueError("processed must be non-negative")
        if remaining is not None and remaining < 0:
            raise ValueError("remaining must be non-negative")
        if progress.cron_id.id != ctx.get("cron_id"):
            raise ValueError("Progress on the wrong cron_id")
        if remaining is None:
            remaining = max(progress.remaining - processed, 0)
        done = progress.done + processed
        vals = {
            "remaining": remaining,
            "done": done,
        }
        if deactivate:
            vals["deactivate"] = True
        progress.write(vals)
        self.env.cr.commit()
        return max(ctx.get("cron_end_time", float("inf")) - time.monotonic(), 0)

    def action_open_parent_action(self) -> dict[str, Any]:
        return self.ir_actions_server_id.action_open_parent_action()

    def action_open_scheduled_action(self) -> dict[str, Any]:
        return self.ir_actions_server_id.action_open_scheduled_action()


class IrCronTrigger(models.Model):
    _name = "ir.cron.trigger"
    _description = "Triggered actions"
    _rec_name = "cron_id"
    _allow_sudo_commands = False

    cron_id = fields.Many2one("ir.cron", required=True, ondelete="cascade")
    # `call_at` keeps its own index: `_gc_cron_triggers` scans on call_at alone.
    call_at = fields.Datetime(index=True, required=True)

    # The ready-jobs EXISTS probe (`_get_ready_jobs_condition`) filters on
    # ``cron_id = ... AND call_at <= now``; this composite serves both that
    # probe and plain cron_id lookups (e.g. `_clear_schedule`), so a separate
    # single-column cron_id index would be redundant (its prefix covers it).
    _cron_id_call_at_idx = models.Index("(cron_id, call_at)")

    @api.autovacuum
    def _gc_cron_triggers(self) -> tuple[int, bool]:
        # active cron jobs are cleared by `_clear_schedule` when the job starts.
        # The cutoff comes from the transaction clock (`cr.now()`, always
        # available: autovacuum runs inside a cursor) like every other time
        # comparison in this file, so it is consistent with the `call_at`
        # values stamped by `_now`/`_trigger` even when the app host's wall
        # clock differs from the DB's.
        domain = [
            ("call_at", "<", self.env.cr.now() - TRIGGER_RETENTION_PERIOD),
            ("cron_id.active", "=", False),
        ]
        records = self.search(domain, limit=GC_UNLINK_LIMIT)
        records.unlink()
        # autovacuum contract: (records removed, whether more may remain)
        return len(records), len(records) == GC_UNLINK_LIMIT


class IrCronProgress(models.Model):
    _name = "ir.cron.progress"
    _description = "Progress of Scheduled Actions"
    _rec_name = "cron_id"

    cron_id = fields.Many2one("ir.cron", required=True, index=True, ondelete="cascade")
    remaining = fields.Integer(default=0)
    done = fields.Integer(default=0)
    deactivate = fields.Boolean()
    timed_out_counter = fields.Integer(default=0)

    # `IrCron._acquire_one_job` reads only the newest progress row per cron
    # (``WHERE cron_id = %s ORDER BY id DESC LIMIT 1``). The plain ``cron_id``
    # index leaves Postgres to sort/backward-scan when a cron has amassed many
    # progress rows (one is inserted per `_run_job` iteration); this composite
    # turns that read into a single index fetch on the acquire hot path.
    _cron_id_id_idx = models.Index("(cron_id, id DESC)")

    @api.autovacuum
    def _gc_cron_progress(self) -> tuple[int, bool]:
        # Transaction clock, for parity with the `create_date` values it is
        # compared against (see `_gc_cron_triggers`).
        records = self.search(
            [("create_date", "<", self.env.cr.now() - PROGRESS_RETENTION_PERIOD)],
            limit=GC_UNLINK_LIMIT,
        )
        records.unlink()
        # autovacuum contract: (records removed, whether more may remain)
        return len(records), len(records) == GC_UNLINK_LIMIT
