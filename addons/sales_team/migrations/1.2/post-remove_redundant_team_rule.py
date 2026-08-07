"""Drop crm_rule_team_salesteam, made redundant by the leader-aware rule.

``crm_rule_personal_salesteam`` now carries the member-OR-responsible domain,
and ``group_sale_salesman_team`` implies ``group_sale_salesman``, so the two
rules selected for a team user are OR-ed and behave as one.

Removing the record from the data file is not enough: it is a ``noupdate``
record, and Odoo deliberately keeps ``noupdate`` orphans on upgrade (they may
have been customised). The copy left behind is inert only for as long as both
domains agree -- the day someone tightens the surviving rule, this one keeps
granting the old, broader access without appearing anywhere in the module.
"""


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM ir_rule
              WHERE id IN (SELECT res_id
                             FROM ir_model_data
                            WHERE module = 'sales_team'
                              AND name = 'crm_rule_team_salesteam'
                              AND model = 'ir.rule')
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
              WHERE module = 'sales_team'
                AND name = 'crm_rule_team_salesteam'
        """
    )
