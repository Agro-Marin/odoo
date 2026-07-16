"""Post-migration for the hr.version multi-company rule domain (1.2).

``ir_rule_hr_contract_multi_company`` had its ``domain_force`` fixed to keep
company-less versions visible (``company_ids + [False]``), but the record
lives inside ``<data noupdate="1">`` in ``security/hr_security.xml``, so a
module update never rewrites it: existing databases silently keep the old
domain and the security fix never lands.

Force the new domain directly, but only where the rule still carries the
known-old value, so a deliberate local customization is left untouched.

Idempotent: the WHERE clause matches nothing once the domain is rewritten.
"""


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
