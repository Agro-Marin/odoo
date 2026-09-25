"""Every cron is anchored at its next execution date.

1.112 counts a cron's executions from `schedule_anchor` instead of from the
nextcall of the run that just ended, so that a daily or longer cron whose local
time falls in a daylight saving gap no longer drifts an hour for good. The
pending execution is the only start a cron from before 1.112 has; one that
already drifted keeps the time of day it drifted to until its nextcall is set
again. A cron anchored already is left alone, so a second run changes nothing.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "UPDATE ir_cron SET schedule_anchor = nextcall WHERE schedule_anchor IS NULL"
    )
    _logger.info("base 1.112: %s crons anchored at their next execution", cr.rowcount)
