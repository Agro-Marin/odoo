import collections
import inspect
import logging
import random
import time
from typing import Any

from odoo import api, models
from odoo.exceptions import AccessDenied
from odoo.modules.registry import CACHES_BY_KEY
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

MAX_VACUUM_RUNTIME = 3600


def is_autovacuum(func: object) -> bool:
    return callable(func) and getattr(func, "_autovacuum", False)


class IrAutovacuum(models.AbstractModel):
    _name = "ir.autovacuum"
    _description = "Automatic Vacuum"

    def _run_vacuum_cleaner(self) -> None:
        if not self.env.is_admin() or not self.env.context.get("cron_id"):
            raise AccessDenied

        all_methods = [
            (model, attr, func, "not started")
            for model in self.env.values()
            for attr, func in inspect.getmembers(model.__class__, is_autovacuum)
        ]
        random.shuffle(all_methods)
        queue = collections.deque(all_methods)
        vacuum_start = time.monotonic()
        hard_deadline = self.env.context.get("cron_hard_deadline")
        calls = 0
        deferred = []
        while queue:
            if (
                calls
                and hard_deadline is not None
                and time.monotonic() >= hard_deadline
            ):
                deferred.extend(
                    (model._name, attr, remaining)
                    for model, attr, _f, remaining in queue
                )
                break
            model, attr, func, _remaining = queue.pop()
            _logger.debug("Calling %s.%s()", model, attr)
            calls += 1
            try:
                start_time = time.monotonic()
                result = func(model)
                self.env["ir.cron"]._commit_progress()
                if remaining := self._get_remaining_work(model, attr, result):
                    if time.monotonic() - vacuum_start >= MAX_VACUUM_RUNTIME:
                        deferred.append((model._name, attr, remaining))
                    else:
                        queue.appendleft((model, attr, func, remaining))
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
                "Autovacuum exceeded its wall-clock budget; deferring "
                "remaining work to the next run: %s",
                ", ".join(
                    f"{name}.{attr} (remaining: {remaining!r})"
                    for name, attr, remaining in deferred
                ),
            )
            self.env["ir.cron"]._commit_progress(remaining=len(deferred))

    @staticmethod
    def _get_remaining_work(model: models.BaseModel, attr: str, result: Any) -> Any:
        if result is None:
            return None
        if not (isinstance(result, tuple) and len(result) == 2):
            _logger.warning(
                "%s.%s returned %r; an autovacuum reports (done, remaining) "
                "or None, so this result is ignored",
                model._name,
                attr,
                result,
            )
            return None
        func_done, func_remaining = result
        _logger.debug(
            "%s.%s  vacuumed %r records, remaining %r",
            model,
            attr,
            func_done,
            func_remaining,
        )
        return func_remaining

    @api.autovacuum
    def _gc_orm_signaling(self) -> None:
        for signal in ["registry", *CACHES_BY_KEY]:
            table = f"orm_signaling_{signal}"
            self.env.cr.execute(
                SQL(
                    "DELETE FROM %s WHERE id < (SELECT max(id)-9 FROM %s) AND date < NOW() - interval '1 hours'",
                    SQL.identifier(table),
                    SQL.identifier(table),
                )
            )
