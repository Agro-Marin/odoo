"""TransientModel: temporary records auto-cleaned after a configurable period."""

import datetime

from odoo.libs.constants import GC_UNLINK_LIMIT
from odoo.tools import SQL, config, lazy_classproperty

from .. import decorators as api
from .base import Model

# Floor on the age threshold for transient vacuum.  Rows used within the last
# 5 minutes are never deleted, so a max_hours setting of 0 (disabled) does
# not cause every row to be vacuumed on its first cron tick.
_TRANSIENT_VACUUM_MIN_AGE_SECONDS = 300


class TransientModel(Model):
    """Model super-class for transient records, meant to be temporarily
    persistent, and regularly vacuum-cleaned.

    A TransientModel has a simplified access rights management, all users can
    create new records, and may only access the records they created. The
    superuser has unrestricted access to all TransientModel records.
    """

    _auto: bool = True  # automatically create database backend
    _register: bool = (
        False  # not visible in ORM registry, meant to be python-inherited only
    )
    _abstract = False  # not abstract
    _transient = True  # transient

    # default values for _transient_vacuum()
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
        """Clean the transient records.

        Unlinks old records whenever the :attr:`_transient_max_count` or
        :attr:`_transient_max_hours` conditions (if any) are reached. Actual
        cleaning happens at most once every 5 minutes, so the method is safe to
        call frequently (e.g. on every record creation). Rows used within the
        last 5 minutes are never deleted.
        """
        has_remaining = False
        if self._transient_max_hours:
            # Age-based expiration
            has_remaining |= self._transient_clean_rows_older_than(
                self._transient_max_hours * 60 * 60
            )

        if self._transient_max_count:
            # Count-based expiration
            has_remaining |= self._transient_clean_old_rows(self._transient_max_count)
        # autovacuum contract: (model name to log, whether rows remain)
        return self._name, has_remaining

    def _transient_clean_old_rows(self, max_count: int) -> bool:
        # Check how many rows we have in the table
        self.env.cr.execute(SQL("SELECT count(*) FROM %s", SQL.identifier(self._table)))
        [count] = self.env.cr.fetchone()
        if count > max_count:
            return self._transient_clean_rows_older_than(_TRANSIENT_VACUUM_MIN_AGE_SECONDS)
        return False

    def _transient_clean_rows_older_than(self, seconds: int) -> bool:
        # Never delete rows used in last 5 minutes
        seconds = max(seconds, _TRANSIENT_VACUUM_MIN_AGE_SECONDS)
        now = self.env.cr.now()
        domain = [("write_date", "<", now - datetime.timedelta(seconds=seconds))]
        records = self.sudo().search(domain, limit=GC_UNLINK_LIMIT)
        records.unlink()
        return len(records) == GC_UNLINK_LIMIT
