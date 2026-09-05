def migrate(cr, version):
    cr.execute("""
      UPDATE ir_rule r
        SET domain_force = '[("employee_id.user_id", "=", user.id), ("state", "=", "confirm")]'
        FROM ir_model_data d
        WHERE d.res_id = r.id
          AND d.model = 'ir.rule'
          AND d.module = 'hr_holidays'
          AND d.name = 'hr_leav_allocation_rule_employee_unlink'
          AND r.domain_force LIKE '%''draft''%'
    """)
