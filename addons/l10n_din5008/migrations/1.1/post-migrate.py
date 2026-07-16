"""Post-migration for the l10n_din5008 paperformat dpi cleanup (1.1).

Reset the wkhtmltopdf-era ``dpi=70`` on the two DIN 5008 paperformats to the
field default (this module never set ``disable_shrinking``): the XML loader
never resets fields omitted from the data file, so upgraded databases keep
the old value while fresh installs get the default (full rationale: hr's 1.2
post-migrate). Guarded on the known-old value; idempotent.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE report_paperformat p
           SET dpi = 90
          FROM ir_model_data d
         WHERE d.model = 'report.paperformat'
           AND d.module = 'l10n_din5008'
           AND d.name IN ('paperformat_euro_din_a', 'paperformat_euro_din')
           AND d.res_id = p.id
           AND p.dpi = 70
        """
    )
