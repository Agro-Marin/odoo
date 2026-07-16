"""Post-migration for the event paperformat dpi/disable_shrinking cleanup (1.10).

Reset the wkhtmltopdf-era ``dpi``/``disable_shrinking`` on the two event
paperformats to the field defaults: the XML loader never resets fields
omitted from the data file, so upgraded databases keep the old values while
fresh installs get the defaults (full rationale: hr's 1.2 post-migrate).
Guarded on the known-old values; idempotent.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE report_paperformat p
           SET dpi = 90,
               disable_shrinking = false
          FROM ir_model_data d
         WHERE d.model = 'report.paperformat'
           AND d.module = 'event'
           AND d.name IN ('paperformat_event_badge', 'paperformat_event_full_page_ticket')
           AND d.res_id = p.id
           AND p.dpi = 96
           AND p.disable_shrinking = true
        """
    )
