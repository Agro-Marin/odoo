_OLD = "action_open_documents"
_NEW = "action_view_documents"
_MODELS = ("product.template", "product.product")


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        rf"""
        UPDATE ir_ui_view
           SET arch_db = regexp_replace(
                   arch_db::text, '\y{_OLD}\y', '{_NEW}', 'g'
               )::jsonb
         WHERE model = ANY(%s)
           AND arch_db::text ~ '\y{_OLD}\y'
        """,
        (list(_MODELS),),
    )

    cr.execute(
        rf"""
        UPDATE ir_act_server s
           SET code = regexp_replace(s.code, '\y{_OLD}\y', '{_NEW}', 'g')
          FROM ir_model m
         WHERE m.id = s.model_id
           AND m.model = ANY(%s)
           AND s.code ~ '\y{_OLD}\y'
        """,
        (list(_MODELS),),
    )
