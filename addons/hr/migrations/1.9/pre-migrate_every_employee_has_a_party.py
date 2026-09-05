import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        WITH created AS (
            INSERT INTO res_partner
                (name, active, type, is_company, company_id,
                 create_uid, write_uid, create_date, write_date)
            SELECT e.name, TRUE, 'contact', FALSE, NULL,
                   1, 1, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'
              FROM hr_employee e
             WHERE e.work_contact_id IS NULL
             ORDER BY e.id
         RETURNING id
        ), targets AS (
            SELECT e.id AS employee_id,
                   ROW_NUMBER() OVER (ORDER BY e.id) AS rn
              FROM hr_employee e
             WHERE e.work_contact_id IS NULL
        ), partners AS (
            SELECT id AS partner_id, ROW_NUMBER() OVER (ORDER BY id) AS rn
              FROM created
        )
        UPDATE hr_employee e
           SET work_contact_id = p.partner_id
          FROM targets t
          JOIN partners p ON p.rn = t.rn
         WHERE e.id = t.employee_id
        """
    )
    _logger.info("%s employees without a work contact were given one", cr.rowcount)
    cr.execute(
        """
        UPDATE res_partner p
           SET lang = e.lang
          FROM hr_employee e
         WHERE e.work_contact_id = p.id AND p.lang IS NULL AND e.lang IS NOT NULL
        """
    )
    _logger.info("%s work contacts took the employee's language", cr.rowcount)
