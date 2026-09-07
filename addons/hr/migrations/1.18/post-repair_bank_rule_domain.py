"""Rewrite the bank-account record rule that a `noupdate` kept on a dead field.

`ir_rule_res_partner_bank_internal_users` is declared under `noupdate="1"`, so
no upgrade rewrites it once it exists. When `res.partner.bank.partner_id` became
`partner_ids`, the XML was updated and the stored rule was not, leaving every
internal user reading a bank account against a field that no longer exists:

    ValueError: Invalid field res.partner.bank.partner_id
                in condition ('partner_id.employee_ids', '=', False)

It surfaces only where the rule is evaluated -- an invoice form, a partner's
bank tab -- which is why it read as an intermittent fault rather than a broken
rule. Repairing the row is the whole fix; the rule's meaning is unchanged.
"""

import logging

_logger = logging.getLogger(__name__)

XMLID = ("hr", "ir_rule_res_partner_bank_internal_users")
CORRECT = "[('partner_ids.employee_ids', '=', False)]"


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE ir_rule rule
           SET domain_force = %s
          FROM ir_model_data data
         WHERE data.model = 'ir.rule'
           AND data.res_id = rule.id
           AND data.module = %s
           AND data.name = %s
           AND rule.domain_force LIKE %s
        """,
        (CORRECT, XMLID[0], XMLID[1], "%partner_id.employee_ids%"),
    )
    if cr.rowcount:
        _logger.info(
            "hr: repaired %s.%s, which still filtered on the removed "
            "res.partner.bank.partner_id",
            *XMLID,
        )
