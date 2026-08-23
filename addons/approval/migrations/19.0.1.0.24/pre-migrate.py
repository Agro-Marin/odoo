import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('approval_tier')")
    if not cr.fetchone()[0]:
        _logger.info("approval: no approval_tier table; nothing to convert.")
        return

    cr.execute(
        """
        SELECT id, name, active, category_id, company_id, currency_id,
               threshold_field, threshold_min, threshold_max,
               approver_required, approval_minimum
          FROM approval_tier
      ORDER BY category_id,
               (threshold_field <> 'amount'),
               threshold_min,
               id
        """,
    )
    tiers = cr.dictfetchall()

    sequence_by_category = {}
    rule_by_tier = {}
    for tier in tiers:
        category = tier["category_id"]
        sequence = sequence_by_category.get(category, 0) + 10
        sequence_by_category[category] = sequence
        cr.execute(
            """
            INSERT INTO approval_rule (
                name, active, sequence, category_id, company_id, currency_id,
                condition_field, operator, threshold, threshold_max,
                action_type, approver_required, approver_sequence,
                approval_minimum, create_uid, write_uid, create_date, write_date
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, 'between', %s, %s,
                'set_approvers', %s, 5,
                %s, 1, 1, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'
            ) RETURNING id
            """,
            (
                tier["name"],
                tier["active"],
                sequence,
                tier["category_id"],
                tier["company_id"],
                tier["currency_id"],
                tier["threshold_field"],
                tier["threshold_min"],
                tier["threshold_max"],
                tier["approver_required"],
                tier["approval_minimum"],
            ),
        )
        rule_by_tier[tier["id"]] = cr.fetchone()[0]

    for tier_id, rule_id in rule_by_tier.items():
        cr.execute(
            """
            INSERT INTO approval_rule_res_users_rel (approval_rule_id, res_users_id)
                 SELECT %s, res_users_id
                   FROM approval_tier_res_users_rel
                  WHERE approval_tier_id = %s
            ON CONFLICT DO NOTHING
            """,
            (rule_id, tier_id),
        )

    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'approval_approver' AND column_name = 'source_tier_id'
    """)
    repointed = 0
    if cr.fetchone():
        for tier_id, rule_id in rule_by_tier.items():
            cr.execute(
                """
                UPDATE approval_approver
                   SET source_rule_id = %s
                 WHERE source_tier_id = %s AND source_rule_id IS NULL
                """,
                (rule_id, tier_id),
            )
            repointed += cr.rowcount
        cr.execute("ALTER TABLE approval_approver DROP COLUMN source_tier_id")

    cr.execute("DROP TABLE IF EXISTS approval_tier_res_users_rel")
    cr.execute("DROP TABLE IF EXISTS approval_tier CASCADE")
    cr.execute(
        "DELETE FROM ir_model_data WHERE model = 'ir.model' AND name = 'model_approval_tier'"
    )
    cr.execute("DELETE FROM ir_model WHERE model = 'approval.tier'")

    _logger.info(
        "approval: converted %d tier(s) into approver-replacing rules and "
        "repointed %d approver row(s); approval_tier dropped.",
        len(rule_by_tier),
        repointed,
    )
