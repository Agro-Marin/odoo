def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_rule r
           SET domain_force = %s
          FROM ir_model_data d
         WHERE d.model = 'ir.rule'
           AND d.module = 'hr'
           AND d.name = 'ir_rule_hr_contract_multi_company'
           AND d.res_id = r.id
           AND r.domain_force = %s
        """,
        [
            "[('company_id', 'in', company_ids + [False])]",
            "[('company_id', 'in', company_ids)]",
        ],
    )
    cr.execute(
        """
        UPDATE report_paperformat p
           SET dpi = 90,
               disable_shrinking = false
          FROM ir_model_data d
         WHERE d.model = 'report.paperformat'
           AND d.module = 'hr'
           AND d.name = 'paperformat_hr_employee_badge'
           AND d.res_id = p.id
           AND p.dpi = 96
           AND p.disable_shrinking = true
        """
    )
