import collections
import inspect
import logging
import random
import time

from odoo import api, models
from odoo.exceptions import AccessDenied
from odoo.modules.registry import _CACHES_BY_KEY
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

MAX_VACUUM_RUNTIME = 3600
"""Wall-clock budget (seconds) for one ``_run_vacuum_cleaner`` run.

Once exceeded, methods reporting remaining work are no longer re-enqueued
(the backlog is deferred to the next daily run); already-queued first-pass
methods still execute, so every method gets at least one batch.
"""


def is_autovacuum(func: object) -> bool:
    """Return whether ``func`` is an autovacuum method."""
    return callable(func) and getattr(func, "_autovacuum", False)


class IrAutovacuum(models.AbstractModel):
    """Helper model to the ``@api.autovacuum`` method decorator."""

    _name = "ir.autovacuum"
    _description = "Automatic Vacuum"

    def _run_vacuum_cleaner(self) -> None:
        """Clean up the database by safely calling every ``@api.autovacuum`` method.

        Invariants (IAVAC-M1) -- load-bearing, do not weaken:

        - **Access gate**: requires ``is_admin()`` and a ``cron_id`` in context,
          else ``AccessDenied`` -- no ad-hoc invocation outside the cron.
        - **Per-method isolation**: each method commits on success; on failure
          the cursor is rolled back and the ORM cache invalidated in isolation.
          One failing method must NOT abort the rest nor roll back committed work.
        - **Re-queue contract**: a method may return ``(done, remaining)``; a
          truthy ``remaining`` requeues it. A ``None`` return runs it once.
        - **Wall-clock budget**: past ``MAX_VACUUM_RUNTIME`` seconds re-enqueueing
          stops (first-pass methods still run) so a backlog can't make the daily
          vacuum unbounded. The deferral is only logged -- partial progress is
          still NOT reported (odoo#265091).
        """
        if not self.env.is_admin() or not self.env.context.get("cron_id"):
            raise AccessDenied

        all_methods = [
            (model, attr, func)
            for model in self.env.values()
            for attr, func in inspect.getmembers(model.__class__, is_autovacuum)
        ]
        # shuffle so one blocking method never consistently starves the rest
        random.shuffle(all_methods)
        queue = collections.deque(all_methods)
        vacuum_start = time.monotonic()
        deferred = []
        # Commit per method for isolation but do NOT report progress counts --
        # partial progress would let the scheduler retry, re-running all methods
        # (odoo#265091).
        while queue:
            model, attr, func = queue.pop()
            _logger.debug("Calling %s.%s()", model, attr)
            try:
                start_time = time.monotonic()
                result = func(model)
                self.env["ir.cron"]._commit_progress()
                if isinstance(result, tuple) and len(result) == 2:
                    func_done, func_remaining = result
                    _logger.debug(
                        "%s.%s  vacuumed %r records, remaining %r",
                        model,
                        attr,
                        func_done,
                        func_remaining,
                    )
                    if func_remaining:
                        if time.monotonic() - vacuum_start >= MAX_VACUUM_RUNTIME:
                            # Budget exhausted: stop RE-enqueueing only; first-pass
                            # methods keep running, the remainder waits for next run.
                            deferred.append((model._name, attr, func_remaining))
                        else:
                            # IAVAC-C2: appendleft + pop (right end) is intentional --
                            # a perpetually-"remaining" method is re-enqueued LEFT and
                            # thus processed LAST each cycle, deferring it behind fresh
                            # work. Do NOT "fix" to append(); that starves the queue.
                            queue.appendleft((model, attr, func))
                _logger.debug(
                    "%s.%s  took %.2fs",
                    model,
                    attr,
                    time.monotonic() - start_time,
                )
            except Exception:
                _logger.exception("Failed %s.%s()", model, attr)
                self.env.cr.rollback()
                self.env.invalidate_all()
        if deferred:
            _logger.warning(
                "Autovacuum exceeded its %ss wall-clock budget; deferring "
                "remaining work to the next run: %s",
                MAX_VACUUM_RUNTIME,
                ", ".join(
                    f"{name}.{attr} (remaining: {remaining!r})"
                    for name, attr, remaining in deferred
                ),
            )

    @api.autovacuum
    def _gc_orm_signaling(self) -> None:
        for signal in ["registry", *_CACHES_BY_KEY]:
            table = f"orm_signaling_{signal}"
            # Keep the last 10 entries per signal plus everything from the last
            # hour: small enough for performance, yet a useful recent history.
            self.env.cr.execute(
                SQL(
                    "DELETE FROM %s WHERE id < (SELECT max(id)-9 FROM %s) AND date < NOW() - interval '1 hours'",
                    SQL.identifier(table),
                    SQL.identifier(table),
                )
            )
