"""Post-migration for hr's 1.2 data fixes.

1. ``ir_rule_hr_contract_multi_company`` had its ``domain_force`` fixed to
   keep company-less versions visible (``company_ids + [False]``), but the
   record lives inside ``<data noupdate="1">`` in ``security/hr_security.xml``,
   so a module update never rewrites it: existing databases silently keep the
   old domain and the security fix never lands.

2. ``paperformat_hr_employee_badge`` had its wkhtmltopdf-era
   ``dpi``/``disable_shrinking`` values removed from
   ``data/report_paperformat.xml`` (they only affect the Web Studio HTML
   preview zoom, meaningless here). The record is NOT noupdate, but Odoo's
   XML data loader only writes ``<field>`` tags present in the CURRENT file —
   omitting a field does not reset it, so an upgraded database keeps the old
   ``dpi=96``/``disable_shrinking=True`` forever while a fresh install gets
   the field defaults (``dpi=90``, ``disable_shrinking=False``).

Both fixes force the new value directly, but only where the record still
carries the known-old value, so a deliberate local customization is left
untouched.

Idempotent: each WHERE clause matches nothing once the value is rewritten.
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
