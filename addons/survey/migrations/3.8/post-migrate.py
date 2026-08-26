def migrate(cr, version):
    cr.execute(
        """
        UPDATE report_paperformat p
           SET dpi = 90,
               disable_shrinking = false
          FROM ir_model_data d
         WHERE d.model = 'report.paperformat'
           AND d.module = 'survey'
           AND d.name = 'paperformat_survey_certification'
           AND d.res_id = p.id
           AND p.dpi = 96
           AND p.disable_shrinking = true
        """
    )
