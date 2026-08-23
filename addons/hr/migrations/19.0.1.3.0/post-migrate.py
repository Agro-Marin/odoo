import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)

# Personal attributes that moved from hr.version (per-version, duplicated by
# create_version) to hr.employee (one value per person). Every one of them is a
# plain stored column on both tables, so the harvest is a single UPDATE ... FROM.
# allowed_country_state_ids is absent on purpose: it is a non-stored compute.
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
    """Harvest the personal attributes off each employee's current version.

    post-migrate is the last stage in which the hr_version columns can be read:
    ir.model.data._process_end drops them right after, because the fields are no
    longer declared. See coding_guidelines.rst 12.2.

    An employee whose versions disagree loses the historical values -- that
    divergence is the corruption this move exists to end, and the current
    version is the only reading the UI ever showed. The count is logged rather
    than resolved, so an operator can audit it against a pre-upgrade dump.

    :param cr: database cursor
    :param version: module version being upgraded from
    """
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
