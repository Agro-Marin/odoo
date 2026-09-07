"""Pre-migration: the stale views that still name a field this version removes.

A view is validated the moment the root it inherits from is rewritten. That
happens while ``base`` loads its own view files, which is long before the module
owning the *inheriting* view is upgraded and can replace its arch. So a child
that still names one of the removed fields aborts the upgrade with "Element
cannot be located in parent view", even though its own source was corrected in
the same commit.

Dropping the stale children here lets each module recreate its view from
corrected source later in the same run. Only views carrying an xmlid are
dropped, because those are the ones a module can put back; anything hand-made
is reported and left alone for a human to look at.
"""

import logging

_logger = logging.getLogger(__name__)

REMOVED_FIELDS = (
    ("res.partner", "phone"),
    ("res.partner", "mobile"),
    ("res.bank", "phone"),
    ("res.partner.bank", "partner_id"),
)


def migrate(cr, version):
    if not version:
        return
    for model, field in REMOVED_FIELDS:
        cr.execute(
            """
            WITH RECURSIVE stale AS (
                SELECT v.id, 0 AS depth
                  FROM ir_ui_view v
                 WHERE v.inherit_id IS NOT NULL AND v.model = %s
                   AND EXISTS (
                       SELECT 1 FROM jsonb_each_text(v.arch_db) arch
                        WHERE arch.value ~ %s
                   )
                 UNION ALL
                SELECT child.id, stale.depth + 1
                  FROM ir_ui_view child
                  JOIN stale ON child.inherit_id = stale.id
            )
            SELECT stale.id, max(stale.depth), max(data.module || '.' || data.name)
              FROM stale
              LEFT JOIN ir_model_data data
                     ON data.model = 'ir.ui.view' AND data.res_id = stale.id
             GROUP BY stale.id
             ORDER BY max(stale.depth) DESC
            """,
            (model, 'name=[\'"]%s[\'"]' % field),
        )
        rows = cr.fetchall()
        doomed = []
        for view_id, _depth, xmlid in rows:
            if xmlid:
                doomed.append(view_id)
            else:
                _logger.warning(
                    "stale views: view %s on %s names the removed field %s and "
                    "carries no xmlid, so nothing would put it back; left in place",
                    view_id,
                    model,
                    field,
                )
        if not doomed:
            continue
        # Deepest first: ir_ui_view.inherit_id is ON DELETE RESTRICT.
        for view_id in doomed:
            cr.execute("DELETE FROM ir_model_data WHERE model = 'ir.ui.view' AND res_id = %s", (view_id,))
            cr.execute("DELETE FROM ir_ui_view WHERE id = %s", (view_id,))
        _logger.info(
            "stale views: dropped %s inheriting views that still named %s.%s; "
            "their modules recreate them from corrected source",
            len(doomed),
            model,
            field,
        )
