"""Odoo-coupled constants with no more specific home.

Moved out of ``odoo/libs/constants.py`` on 2026-08-09: ``libs/`` is the
Odoo-**agnostic** layer, and every one of these names is framework vocabulary.
The two channel names are a protocol shared between the listener in
``odoo/service/`` and the notifier in ``addons/base``, so neither package owns
them alone.

Asset-pipeline constants went to :mod:`odoo.tools.assets.constants`, and the
two ORM tuning limits to :mod:`odoo.orm.primitives`, beside the batch sizes
that were already there.
"""

__all__ = [
    "CRON_TRIGGER_CHANNEL",
    "JOB_QUEUE_CHANNEL",
    "SUPPORTED_DEBUGGER",
]

CRON_TRIGGER_CHANNEL = "cron_trigger"
"""PostgreSQL NOTIFY channel waking the ``ir.cron`` workers."""

JOB_QUEUE_CHANNEL = "job_queue"
"""PostgreSQL NOTIFY channel waking the ``ir.job`` workers."""

SUPPORTED_DEBUGGER = {"pdb", "ipdb", "wdb", "pudb"}
