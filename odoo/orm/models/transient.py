import datetime

from odoo.tools import SQL, config, lazy_classproperty

from .. import decorators as api
from ..primitives import GC_UNLINK_LIMIT
from .base import Model

_TRANSIENT_VACUUM_MIN_AGE_SECONDS = 300


class TransientModel(Model):
    _auto: bool = True
    _register: bool = False
    _abstract = False
    _transient = True

    _transient_max_count = lazy_classproperty(
        lambda _: int(config.get("osv_memory_count_limit"))
    )
    "maximum number of transient records, unlimited if ``0``"
    _transient_max_hours = lazy_classproperty(
        lambda _: float(config.get("transient_age_limit"))
    )
    "maximum idle lifetime (in hours), unlimited if ``0``"

    @api.autovacuum
    def _transient_vacuum(self) -> tuple[str, bool]:
        has_remaining = False
        if self._transient_max_hours:
            has_remaining |= self._transient_clean_rows_older_than(
                self._transient_max_hours * 60 * 60
            )

        if self._transient_max_count:
            has_remaining |= self._transient_clean_old_rows(self._transient_max_count)
        return self._name, has_remaining

    def _transient_clean_old_rows(self, max_count: int) -> bool:
        self.env.cr.execute(SQL("SELECT count(*) FROM %s", SQL.identifier(self._table)))
        [count] = self.env.cr.fetchone()
        if count > max_count:
            return self._transient_clean_rows_older_than(
                _TRANSIENT_VACUUM_MIN_AGE_SECONDS
            )
        return False

    def _transient_clean_rows_older_than(self, seconds: int) -> bool:
        seconds = max(seconds, _TRANSIENT_VACUUM_MIN_AGE_SECONDS)
        now = self.env.cr.now()
        domain = [("write_date", "<", now - datetime.timedelta(seconds=seconds))]
        records = self.sudo().search(domain, limit=GC_UNLINK_LIMIT)
        records.unlink()
        return len(records) == GC_UNLINK_LIMIT
