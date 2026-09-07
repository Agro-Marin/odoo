"""Pre-migration: the inheriting views that still name a field this release removes.

A view's combined arch is built by applying *every* extension view of its root,
so one stale child poisons the validation of each of its siblings, not just of
itself. That validation fires the moment any view in the tree is written --
which happens while the field's own module loads its view files, before the
modules owning the other children are upgraded and can replace their archs. The
run aborts with "Element cannot be located in parent view" or "Field ... does
not exist", naming a view whose source was corrected in this very release.

The cleanup therefore cannot live in the module that removes the field: by the
time that module runs, the tree has already been validated. It lives here
because `base` is the only module guaranteed to load before all of them, which
is why this one list spans several modules' fields.

Only views carrying an xmlid are dropped, since those are the ones a module
puts back from corrected source later in the same run. A hand-made view is
reported and left alone.
"""

import logging

_logger = logging.getLogger(__name__)

REMOVED_FIELDS = (
    # a phone number and a bank account became records every contact can share
    ("res.partner", "phone"),
    ("res.partner", "mobile"),
    ("res.users", "work_phone"),
    ("res.users", "mobile_phone"),
    ("res.users", "private_phone"),
    ("res.users", "emergency_phone"),
    ("res.bank", "phone"),
    ("res.partner.bank", "partner_id"),
    ("res.partner.bank", "bank_phone"),
    ("res.partner", "duplicate_bank_partner_ids"),
    ("crm.lead", "phone"),
    ("event.registration", "phone"),
    ("project.task", "partner_phone"),
    ("pos.order", "mobile"),
    ("hr.applicant", "partner_phone_sanitized"),
    ("product.msds", "emergency_phone"),
    ("res.partner", "msds_emergency_phone"),
    # the employee's work channels are its party's
    ("hr.employee", "work_phone"),
    ("hr.employee", "mobile_phone"),
    ("hr.employee", "private_phone"),
    ("hr.employee", "emergency_phone"),
    # an asset lot carries a resource.asset
    ("account.asset", "asset_type_kind"),
    ("account.return.type", "payment_partner_id"),
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
