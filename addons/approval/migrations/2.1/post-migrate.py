import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Keep every existing category deciding the way it did.

    19.0.2.1.0 refuses a request's owner as its approver unless the category
    allows it, and new categories do not. A category that already existed may
    have been relied on for exactly that -- an administrator approving the
    business trip they filed -- so it is marked allowing, and tightening it is
    a visible decision on its form rather than a silent change on upgrade.
    """
    cr.execute("UPDATE approval_category SET allow_self_approval = TRUE")
    _logger.info(
        "approval 19.0.2.1.0: %d existing categor(ies) keep allowing self-approval.",
        cr.rowcount,
    )
