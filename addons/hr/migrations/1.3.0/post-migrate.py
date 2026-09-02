import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)

MOVED_COLUMNS = (
    "country_id",
    "identification_id",
    "ssnid",
    "passport_id",
    "passport_expiration_date",
    "sex",
    "private_street",
    "private_street2",
    "private_city",
    "private_zip",
    "private_state_id",
    "private_country_id",
    "distance_home_work",
    "km_home_work",
    "distance_home_work_unit",
    "marital",
    "spouse_complete_name",
    "spouse_birthdate",
    "children",
)


def migrate(cr, version):
    if not version:
        return

    columns = [
        c
        for c in MOVED_COLUMNS
        if column_exists(cr, "hr_version", c) and column_exists(cr, "hr_employee", c)
    ]
    if not columns:
        _logger.warning(
            "hr: no personal columns left on hr_version, nothing to harvest"
        )
        return

    divergent = " OR ".join(f"v.{c} IS DISTINCT FROM o.{c}" for c in columns)
    cr.execute(f"""
        SELECT COUNT(DISTINCT v.employee_id)
          FROM hr_version v
          JOIN hr_employee e ON e.id = v.employee_id
          JOIN hr_version o ON o.id = e.current_version_id
         WHERE v.id != o.id AND ({divergent})
    """)
    conflicts = cr.fetchone()[0]
    if conflicts:
        _logger.warning(
            "hr: %s employee(s) had personal data differing between versions; "
            "kept the current version's values and discarded the rest",
            conflicts,
        )

    assignments = ", ".join(f"{c} = v.{c}" for c in columns)
    cr.execute(f"""
        UPDATE hr_employee e
           SET {assignments}
          FROM hr_version v
         WHERE v.id = e.current_version_id
    """)
    _logger.info(
        "hr: moved %s personal column(s) from hr.version onto %s employee(s)",
        len(columns),
        cr.rowcount,
    )
