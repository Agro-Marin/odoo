import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Keep telling every member of a security group that already asked them.

    19.0.2.2.0 treats a security group as a queue: members decide from To Review
    and nobody gets a personal activity. Existing group categories keep asking
    each member until someone turns it off on the category.
    """
    cr.execute(
        "UPDATE approval_category SET notify_pool_members = TRUE "
        "WHERE group_approval = 'exclusive'"
    )
    _logger.info(
        "approval 19.0.2.2.0: %d group categor(ies) keep notifying every member.",
        cr.rowcount,
    )
