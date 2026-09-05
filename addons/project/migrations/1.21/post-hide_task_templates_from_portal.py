RULES = [
    "project_task_rule_portal",
    "project_task_rule_portal_project_sharing",
]

CLAUSE = "('has_template_ancestor', '=', False),"

ANCHOR = "('project_id.privacy_visibility', 'in', ['invited_users', 'portal']),"


def migrate(cr, version):
    # The two portal rules on project.task live in a noupdate block, so the
    # new clause that hides task templates never reaches a database that
    # already has them.  Patch the stored domains, leaving alone any rule an
    # integrator has rewritten past recognition.
    cr.execute(
        """
        SELECT r.id, r.domain_force
          FROM ir_rule r
          JOIN ir_model_data d
            ON d.model = 'ir.rule' AND d.res_id = r.id
         WHERE d.module = 'project' AND d.name = ANY(%s)
        """,
        [RULES],
    )
    for rule_id, domain in cr.fetchall():
        if not domain or CLAUSE in domain or ANCHOR not in domain:
            continue
        cr.execute(
            "UPDATE ir_rule SET domain_force = %s WHERE id = %s",
            [domain.replace(ANCHOR, f"{ANCHOR}\n            {CLAUSE}", 1), rule_id],
        )
