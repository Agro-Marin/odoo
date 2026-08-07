import logging

from odoo import SUPERUSER_ID, api
from odoo.fields import Command

_logger = logging.getLogger(__name__)

# Same noupdate situation as gamification's own security file. The two
# hr.group_hr_user rules are left alone: that group is the HR bridge, not a tier
# this app owns.
RULE_GROUPS = {
    "hr_gamification.hr_gamification_badge_base_user_owned_access": (
        "gamification.group_gamification_user",
    ),
    "hr_gamification.hr_gamification_badge_base_user_not_owned_access": (
        "gamification.group_gamification_user",
    ),
}


def migrate(cr, version):
    """Re-point hr_gamification's noupdate badge.user rules onto the app group.

    :param cr: database cursor
    :param version: module version being upgraded from
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    for rule_xmlid, group_xmlids in RULE_GROUPS.items():
        rule = env.ref(rule_xmlid, raise_if_not_found=False)
        if not rule:
            _logger.warning("t24520: rule %s not found, skipped", rule_xmlid)
            continue
        rule.groups = [Command.set([env.ref(x).id for x in group_xmlids])]
        _logger.info("t24520: rule %s re-pointed to %s", rule_xmlid, group_xmlids)
