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
from odoo.api import SUPERUSER_ID, ValuesType
from odoo.exceptions import LockError, UserError
from odoo.http import serialize_exception
from odoo.models import GC_UNLINK_LIMIT
from odoo.modules import Manifest
from odoo.modules.loading import reset_modules_state
from odoo.modules.registry import Registry
from odoo.tools import SQL, config, str2bool
from odoo.tools.constants import CRON_TRIGGER_CHANNEL

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from odoo.db import BaseCursor

_logger = logging.getLogger(__name__)

_TRANSACTION_ROLLBACK_ERRORS = (
    psycopg.errors.TransactionRollback,
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
    psycopg.errors.TransactionIntegrityConstraintViolation,
    psycopg.errors.StatementCompletionUnknown,
)

BASE_VERSION = Manifest.for_addon("base")["version"]
MAX_FAIL_TIME = timedelta(hours=5)
MIN_RUNS_PER_JOB = 10
MIN_TIME_PER_JOB = 10
RUN_BUDGET_RATIO = 0.8
CONSECUTIVE_TIMEOUT_FOR_FAILURE = 3
MIN_FAILURE_COUNT_BEFORE_DEACTIVATION = 5
MIN_DELTA_BEFORE_DEACTIVATION = timedelta(days=7)
TRIGGER_RETENTION_PERIOD = timedelta(weeks=1)
PROGRESS_RETENTION_PERIOD = timedelta(weeks=1)

ODOO_NOTIFY_FUNCTION = os.getenv("ODOO_NOTIFY_FUNCTION", "pg_notify")
NOTIFY_CRON_CHANGES = str2bool(os.getenv("ODOO_NOTIFY_CRON_CHANGES", ""), default=False)


def worker_real_time_budget() -> float:
    budget = config["limit_time_real_cron"]
    if budget < 0:
        budget = config["limit_time_real"]
    return max(budget, 0)


def notify_channel(channel: str, db_name: str) -> None:
    with db.db_connect("postgres").cursor() as cr:
        cr.execute(
            SQL(
                "SELECT %s(%s, %s)",
                SQL.identifier(ODOO_NOTIFY_FUNCTION),
                channel,
                db_name,
            )
        )
    _logger.debug("%s workers notified (%s)", channel, db_name)


class BadVersionError(Exception):
    pass


class BadModuleStateError(Exception):
    pass


class CompletionStatus(StrEnum):
    FULLY_DONE = "fully done"
    PARTIALLY_DONE = "partially done"
    FAILED = "failed"


class IrCron(models.Model):
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
        help="Previous time the cron ran to completion (whether it finished or failed), provided to the job through the context on the `lastcall` key",
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
            self.env.cr.postcommit.add(self._notify_trigger_channel)
        return super().create(vals_list)

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        model = self
        if not model.env.context.get("default_state"):
            model = model.with_context(default_state="code")
        return super(IrCron, model).default_get(fields)

    def method_direct_trigger(self) -> dict[str, Any] | bool:
        self.ensure_one()
        self.browse().check_access("write")
        self.env.invalidate_all(flush=True)
        cron_cr = self.env.cr
        job = self._acquire_job(cron_cr, self.id, include_not_ready=True)
        if not job:
            raise UserError(self.env._("Job '%s' already executing", self.name))

        self._run_job(cron_cr, job)
        if exception := job.get("run_exception"):
            e = RuntimeError()
            e.__cause__ = exception
            error = {
                "code": 0,
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
        previous_dbname = getattr(threading.current_thread(), "dbname", None)
        try:
            db_conn = db.db_connect(db_name)
            threading.current_thread().dbname = db_name
            with db_conn.cursor() as cron_cr:
                cls = IrCron
                cls._check_version(cron_cr)
                jobs = cls._get_jobs_ready(cron_cr)
                if not jobs:
                    return
                cls._check_modules_state(cron_cr, jobs)
                cls._run_jobs_until_deadline(
                    cron_cr,
                    job_ids=[job["id"] for job in jobs],
                    deadline=cls._get_deadline_pass(),
                )
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
            _logger.warning("Tried to poll an undefined table on database %s.", db_name)
        except db.PoolError:
            _logger.info("Skipping database %s: could not connect.", db_name)
        except psycopg.ProgrammingError:
            raise
        except Exception:
            _logger.exception("Unexpected exception in cron for database %s:", db_name)
        finally:
            if previous_dbname is None:
                if hasattr(threading.current_thread(), "dbname"):
                    del threading.current_thread().dbname
            else:
                threading.current_thread().dbname = previous_dbname

    @staticmethod
    def _get_deadline_pass() -> float | None:
        budget = worker_real_time_budget()
        return time.monotonic() + budget * RUN_BUDGET_RATIO if budget else None

    @staticmethod
    def _run_jobs_until_deadline(
        cron_cr: BaseCursor,
        *,
        job_ids: Iterable[int] = (),
        deadline: float | None = None,
    ) -> bool:
        db_name = cron_cr.dbname
        job_ids = list(job_ids)
        for index, job_id in enumerate(job_ids):
            if deadline is not None and time.monotonic() >= deadline:
                _logger.warning(
                    "Cron pass on %s yielded on its time budget with %s job(s)"
                    " left to run; notifying",
                    db_name,
                    len(job_ids) - index,
                )
                notify_channel(CRON_TRIGGER_CHANNEL, db_name)
                return True
            try:
                job = IrCron._acquire_job(cron_cr, job_id)
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
            registry = Registry(db_name).check_signaling()
            try:
                registry[IrCron._name]._run_job(cron_cr, job, deadline=deadline)
                cron_cr.commit()
            except Exception:
                cron_cr.rollback()
                _logger.exception("job %s failed to process, skip", job_id)
                continue
            _logger.debug("job %s updated and released", job_id)
        return False

    @staticmethod
    def _check_version(cron_cr: BaseCursor) -> None:
        cron_cr.execute("""
            SELECT db_version
            FROM ir_module_module
             WHERE name='base'
        """)
        row = cron_cr.fetchone()
        if row is None or row[0] is None:
            raise BadModuleStateError
        if row[0] != BASE_VERSION:
            raise BadVersionError

    @staticmethod
    def _is_any_module_changing(cr: BaseCursor) -> bool:
        cr.execute(
            "SELECT EXISTS (SELECT 1 FROM ir_module_module WHERE state LIKE %s)",
            ["to %"],
        )
        return cr.fetchone()[0]

    @staticmethod
    def _check_modules_state(cr: BaseCursor, jobs: list[dict[str, Any]]) -> None:
        if not IrCron._is_any_module_changing(cr):
            return

        if not jobs:
            raise BadModuleStateError

        oldest = min(
            max(job["nextcall"], job["write_date"] or job["nextcall"]) for job in jobs
        )
        if cr.now() - oldest < MAX_FAIL_TIME:
            raise BadModuleStateError

        reset_modules_state(cr.dbname)

    @staticmethod
    def _get_sql_condition_ready(cr: BaseCursor) -> SQL:
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
    def _get_jobs_ready(cr: BaseCursor) -> list[dict[str, Any]]:
        cr.execute(
            SQL(
                """
            SELECT id, nextcall, write_date
            FROM ir_cron
            WHERE %s
            ORDER BY failure_count, priority, id
        """,
                IrCron._get_sql_condition_ready(cr),
            )
        )
        return cr.dictfetchall()

    @staticmethod
    def _acquire_job(
        cr: BaseCursor, job_id: int, *, include_not_ready: bool = False
    ) -> dict[str, Any] | None:

        where_clause = SQL("id = %s", job_id)
        if not include_not_ready:
            where_clause = SQL(
                "%s AND %s", where_clause, IrCron._get_sql_condition_ready(cr)
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
            cr.execute(query, log_exceptions=False, prepare=False)
        except _TRANSACTION_ROLLBACK_ERRORS:
            raise
        except psycopg.Error as exc:
            _logger.error("bad query: %s\nERROR: %s", query, exc)
            raise

        job = cr.dictfetchone()

        if not job:
            return None

        for field_name in ("done", "remaining", "timed_out_counter"):
            job[field_name] = job[field_name] or 0
        return job

    def _notify_admin(self, message: str) -> None:
        _logger.warning(message)

    @classmethod
    def _run_job(
        cls,
        cron_cr: BaseCursor,
        job: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> None:
        env = api.Environment(cron_cr, job["user_id"], {})
        ir_cron = env[cls._name]

        ir_cron._remove_triggers_due(job)
        failed_by_timeout = (
            job["timed_out_counter"] >= CONSECUTIVE_TIMEOUT_FOR_FAILURE
            and not job["done"]
        )

        if not failed_by_timeout:
            status = cls._run_job_within_budget(job, deadline=deadline)
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
            ir_cron._reschedule_job_later(job)
        elif status == CompletionStatus.PARTIALLY_DONE:
            ir_cron._reschedule_job_asap(job)
            if NOTIFY_CRON_CHANGES:
                cron_cr.postcommit.add(ir_cron._notify_trigger_channel)
        else:
            raise RuntimeError(f"unreachable {status=}")

    @staticmethod
    def _resolve_completion_status(
        *, success: bool, done: int, remaining: int
    ) -> CompletionStatus | None:
        match (success, bool(done), bool(remaining)):
            case (False, True, True):
                return None
            case (False, _, _):
                return CompletionStatus.FAILED
            case (True, _, False):
                return CompletionStatus.FULLY_DONE
            case (True, False, _):
                return CompletionStatus.PARTIALLY_DONE
            case _:
                return None

    @staticmethod
    def _can_keep_running(
        *,
        status: CompletionStatus | None,
        loop_count: int,
        now: float,
        end_time: float,
        hard_deadline: float | None = None,
    ) -> bool:
        if status is not None:
            return False
        if hard_deadline is not None and loop_count and now >= hard_deadline:
            return False
        return loop_count < MIN_RUNS_PER_JOB or now < end_time

    @staticmethod
    def _get_deadline_run(start_time: float) -> float | None:
        budget = worker_real_time_budget()
        return start_time + budget * RUN_BUDGET_RATIO if budget else None

    @classmethod
    def _run_job_within_budget(
        cls, job: dict[str, Any], *, deadline: float | None = None
    ) -> CompletionStatus:
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
            hard_deadline = (
                deadline if deadline is not None else cls._get_deadline_run(start_time)
            )
            _logger.info("Job %r (%s) starting", job["cron_name"], job["id"])

            if not env.user.active and env.uid != SUPERUSER_ID:
                _logger.warning(
                    "Forbidden server action %r executed while the user %s is archived.",
                    job["cron_name"],
                    env.user.login,
                )
                status = CompletionStatus.FAILED

            while cls._can_keep_running(
                status=status,
                loop_count=loop_count,
                now=time.monotonic(),
                end_time=env.context["cron_end_time"],
                hard_deadline=hard_deadline,
            ):
                cron, progress = cron._add_progress(timed_out_counter=timed_out_counter)
                job_cr.commit()

                success = False
                try:
                    cron._run_server_action(
                        job["cron_name"], job["ir_actions_server_id"]
                    )
                    success = True
                except Exception as exc:
                    _logger.exception(
                        "Job %r (%s) server action #%s failed",
                        job["cron_name"],
                        job["id"],
                        job["ir_actions_server_id"],
                    )
                    job.setdefault("run_exception", exc)
                finally:
                    done, remaining = progress.done, progress.remaining
                    status = cls._resolve_completion_status(
                        success=success, done=done, remaining=remaining
                    )
                    if status is CompletionStatus.FULLY_DONE and progress.deactivate:
                        job["deactivate"] = True
                    elif status is CompletionStatus.PARTIALLY_DONE and loop_count == 0:
                        _logger.warning(
                            "Job %r (%s) processed no record",
                            job["cron_name"],
                            job["id"],
                        )

                    loop_count += 1
                    progress.timed_out_counter = 0
                    timed_out_counter = 0
                    job_cr.commit()

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
    def _get_now(self) -> datetime:
        return self.env.cr.now().replace(microsecond=0)

    @api.model
    def _update_failure_count(
        self, job: dict[str, Any], status: CompletionStatus
    ) -> None:
        if status == CompletionStatus.FAILED:
            now = self._get_now()
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
            active = False

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
    def _remove_triggers_due(self, job: dict[str, Any]) -> None:
        now = self._get_now()
        self.env.cr.execute(
            """
            DELETE FROM ir_cron_trigger
            WHERE cron_id = %s
              AND call_at <= %s
        """,
            [job["id"], now],
        )

    @staticmethod
    def _get_next_call(
        record: models.BaseModel,
        nextcall: datetime,
        now: datetime,
        interval_type: str,
        interval_number: int,
    ) -> datetime:
        if interval_type in ("minutes", "hours"):
            interval = timedelta(**{interval_type: interval_number})
            if nextcall <= now:
                steps = (now - nextcall) // interval + 1
                nextcall += steps * interval
            return nextcall

        interval = relativedelta(**{interval_type: interval_number})
        while nextcall <= now:
            local = fields.Datetime.context_timestamp(record, nextcall)
            nextcall = (local + interval).astimezone(UTC).replace(tzinfo=None)
        return nextcall

    @api.model
    def _reschedule_job_later(self, job: dict[str, Any]) -> None:
        now = self._get_now()
        nextcall = self._get_next_call(
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
    def _reschedule_job_asap(self, job: dict[str, Any]) -> None:
        now = self._get_now()
        self.env.cr.execute(
            """
            INSERT INTO ir_cron_trigger(call_at, cron_id)
            VALUES (%s, %s)
        """,
            [now, job["id"]],
        )

    def _run_server_action(self, cron_name: str, server_action_id: int) -> None:
        self.ensure_one()
        try:
            if self.pool is not self.pool.check_signaling():
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
            self.env.cr.postcommit.add(self._notify_trigger_channel)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_running(self) -> None:
        self._lock_for_update_or_raise()

    @api.model
    def toggle(self, model: str, domain: list[Any]) -> bool:
        if self.env["ir.config_parameter"].sudo().get_param("database.is_neutralized"):
            return True

        active = bool(self.env[model].search_count(domain, limit=1))
        try:
            self.lock_for_update(allow_referencing=True)
        except LockError:
            return True
        return self.write({"active": active})

    def _trigger(
        self, at: datetime | Iterable[datetime] | None = None, *, coalesce: int = 0
    ) -> Any:
        if at is None:
            at_list = [self._get_now()]
        elif isinstance(at, datetime):
            at_list = [at]
        else:
            at_list = list(at)
            if not all(isinstance(item, datetime) for item in at_list):
                raise TypeError("all items in 'at' must be datetime objects")

        if coalesce:
            factor = coalesce * 60
            at_list = [
                datetime.fromtimestamp(
                    math.ceil(dt.replace(tzinfo=UTC).timestamp() / factor) * factor,
                    UTC,
                ).replace(tzinfo=None)
                for dt in at_list
            ]

        return self._add_triggers(at_list)

    def _add_triggers(self, at_list: list[datetime]) -> Any:
        self.ensure_one()
        now = self._get_now()

        if not self.sudo().active:
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
            self.env.cr.postcommit.add(self._notify_trigger_channel)
        return triggers

    @api.model
    def _notify_trigger_channel(self) -> None:
        notify_channel(CRON_TRIGGER_CHANNEL, self.env.cr.dbname)

    def _add_progress(
        self, *, timed_out_counter: int | None = None
    ) -> tuple[Self, Any]:
        progress = (
            self.env["ir.cron.progress"]
            .sudo()
            .create(
                [
                    {
                        "cron_id": self.id,
                        "remaining": 0,
                        "done": 0,
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
        ctx = self.env.context
        progress = (
            self.env["ir.cron.progress"].sudo().browse(ctx.get("ir_cron_progress_id"))
        )
        if not progress:
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
    call_at = fields.Datetime(index=True, required=True)

    _cron_id_call_at_idx = models.Index("(cron_id, call_at)")

    @api.autovacuum
    def _gc_cron_triggers(self) -> tuple[int, bool]:
        domain = [
            ("call_at", "<", self.env.cr.now() - TRIGGER_RETENTION_PERIOD),
            ("cron_id.active", "=", False),
        ]
        records = self.search(domain, limit=GC_UNLINK_LIMIT)
        records.unlink()
        return len(records), len(records) == GC_UNLINK_LIMIT


class IrCronProgress(models.Model):
    _name = "ir.cron.progress"
    _description = "Progress of Scheduled Actions"
    _rec_name = "cron_id"
    _allow_sudo_commands = False

    cron_id = fields.Many2one("ir.cron", required=True, index=True, ondelete="cascade")
    remaining = fields.Integer(default=0)
    done = fields.Integer(default=0)
    deactivate = fields.Boolean()
    timed_out_counter = fields.Integer(default=0)

    _cron_id_id_idx = models.Index("(cron_id, id DESC)")
    _create_date_idx = models.Index("(create_date)")

    @api.autovacuum
    def _gc_cron_progress(self) -> tuple[int, bool]:
        records = self.search(
            [("create_date", "<", self.env.cr.now() - PROGRESS_RETENTION_PERIOD)],
            limit=GC_UNLINK_LIMIT,
        )
        full_batch = len(records) == GC_UNLINK_LIMIT
        self.env.cr.execute(
            "SELECT max(id) FROM ir_cron_progress"
            " WHERE cron_id = ANY(%s) GROUP BY cron_id",
            [records.cron_id.ids],
        )
        records -= self.browse(row[0] for row in self.env.cr.fetchall())
        records.unlink()
        return len(records), full_batch
