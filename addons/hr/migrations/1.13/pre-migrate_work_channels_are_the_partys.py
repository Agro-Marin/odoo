import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    for column, target in (
        ("work_email", "email"),
        ("work_phone", "phone"),
        ("mobile_phone", "mobile"),
    ):
        cr.execute(
            f"""
            UPDATE res_partner p
               SET {target} = e.{column}
              FROM hr_employee e
             WHERE e.partner_id = p.id
               AND e.{column} IS NOT NULL
               AND e.{column} <> ''
               AND (p.{target} IS NULL OR p.{target} = '')
            """
        )
        _logger.info(
            "work channels: %s parties took the employee's %s", cr.rowcount, column
        )
        cr.execute(
            f"""
            SELECT e.id, e.{column}, p.{target}
              FROM hr_employee e
              JOIN res_partner p ON p.id = e.partner_id
             WHERE e.{column} IS NOT NULL AND e.{column} <> ''
               AND p.{target} IS NOT NULL AND p.{target} <> e.{column}
            """
        )
        for employee_id, own, party in cr.fetchall():
            _logger.warning(
                "work channels: employee %s kept its own %s %r, the party's is %r; the party's wins",
                employee_id,
                column,
                own,
                party,
            )
