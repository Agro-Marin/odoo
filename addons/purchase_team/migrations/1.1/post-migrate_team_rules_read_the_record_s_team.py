import logging

from odoo.addons.base.models.ir_access_convert import rewrite_converted_domain

_logger = logging.getLogger(__name__)

# a purchase team rule reads the record's own team, not the teams its owner belongs to
# (the user's decision, P4 T2 option B); a noupdate row still holding the old
# domain is rewritten, one an administrator changed is left as it is
REWRITES = (
    (
        "purchase_order_team_rule",
        "['|', '|', ('user_id', '=', False), ('user_id.purchase_team_ids', 'in', user.purchase_team_ids.ids), ('team_id', 'in', user.purchase_team_ids.ids)]",
        "['|', ('user_id', '=', False), ('team_id', 'in', user.purchase_team_ids.ids)]",
    ),
    (
        "purchase_order_line_team_rule",
        "['|', '|', ('order_id.user_id', '=', False), ('order_id.user_id.purchase_team_ids', 'in', user.purchase_team_ids.ids), ('order_id.team_id', 'in', user.purchase_team_ids.ids)]",
        "['|', ('order_id.user_id', '=', False), ('order_id.team_id', 'in', user.purchase_team_ids.ids)]",
    ),
    (
        "purchase_report_team_rule",
        "['|', '|', ('user_id', '=', False), ('user_id.purchase_team_ids', 'in', user.purchase_team_ids.ids), ('team_id', 'in', user.purchase_team_ids.ids)]",
        "['|', ('user_id', '=', False), ('team_id', 'in', user.purchase_team_ids.ids)]",
    ),
)


def migrate(cr, version):
    if not version:
        return
    for name, old, new in REWRITES:
        rewrite_converted_domain(cr, "purchase_team", name, new, old, logger=_logger)
