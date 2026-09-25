import logging

from odoo.addons.base.models.ir_access_convert import rewrite_converted_domain

_logger = logging.getLogger(__name__)

# a sale team rule reads the record's own team, not the teams its owner belongs to
# (the user's decision, P4 T2 option B); a noupdate row still holding the old
# domain is rewritten, one an administrator changed is left as it is
REWRITES = (
    (
        "account_invoice_send_single_rule_see_team",
        "[('move_id.move_type', 'in', ('out_invoice', 'out_refund')), '|', ('move_id.invoice_user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('move_id.invoice_user_id', '=', False)]",
        "[('move_id.move_type', 'in', ('out_invoice', 'out_refund')), '|', ('move_id.team_id', 'in', user.sale_team_ids.ids), ('move_id.invoice_user_id', '=', False)]",
    ),
    (
        "account_invoice_send_batch_rule_see_team",
        "[('move_ids.move_type', 'in', ('out_invoice', 'out_refund')), '|', ('move_ids.invoice_user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('move_ids.invoice_user_id', '=', False)]",
        "[('move_ids.move_type', 'in', ('out_invoice', 'out_refund')), '|', ('move_ids.team_id', 'in', user.sale_team_ids.ids), ('move_ids.invoice_user_id', '=', False)]",
    ),
    (
        "account_invoice_rule_see_team",
        "[('move_type', 'in', ('out_invoice', 'out_refund')), '|', ('invoice_user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('invoice_user_id', '=', False)]",
        "[('move_type', 'in', ('out_invoice', 'out_refund')), '|', ('team_id', 'in', user.sale_team_ids.ids), ('invoice_user_id', '=', False)]",
    ),
    (
        "account_invoice_line_rule_see_team",
        "[('move_id.move_type', 'in', ('out_invoice', 'out_refund')), '|', ('move_id.invoice_user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('move_id.invoice_user_id', '=', False)]",
        "[('move_id.move_type', 'in', ('out_invoice', 'out_refund')), '|', ('move_id.team_id', 'in', user.sale_team_ids.ids), ('move_id.invoice_user_id', '=', False)]",
    ),
    (
        "sale_order_team_rule",
        "['|', ('user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('user_id', '=', False)]",
        "['|', ('team_id', 'in', user.sale_team_ids.ids), ('user_id', '=', False)]",
    ),
    (
        "sale_order_line_team_rule",
        "['|', ('user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('user_id', '=', False)]",
        "['|', ('order_id.team_id', 'in', user.sale_team_ids.ids), ('user_id', '=', False)]",
    ),
    (
        "sale_order_report_team_rule",
        "['|', ('user_id.sale_team_ids', 'in', user.sale_team_ids.ids), ('user_id', '=', False)]",
        "['|', ('team_id', 'in', user.sale_team_ids.ids), ('user_id', '=', False)]",
    ),
)


def migrate(cr, version):
    if not version:
        return
    for name, old, new in REWRITES:
        rewrite_converted_domain(cr, "sale_team", name, new, old, logger=_logger)
