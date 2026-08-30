import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_TABLE = "res_partner"
_COLUMN = "company_name"


def _link_to_existing_companies(cr):
    cr.execute(
        """
        UPDATE res_partner child
           SET parent_id = parent.id
          FROM res_partner parent
         WHERE child.parent_id IS NULL
           AND btrim(COALESCE(child.company_name, '')) <> ''
           AND child.id <> parent.id
           AND parent.is_company
           AND parent.active
           AND parent.parent_id IS NULL
           AND btrim(parent.name) = btrim(child.company_name)
           AND parent.company_id IS NOT DISTINCT FROM child.company_id
        """
    )
    return cr.rowcount


def _create_missing_companies(cr):
    cr.execute(
        """
        WITH promoted AS (
            INSERT INTO res_partner (
                name, is_company, active, type, company_id,
                create_uid, write_uid, create_date, write_date
            )
            SELECT DISTINCT
                   btrim(child.company_name), true, true, 'contact', child.company_id,
                   1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
              FROM res_partner child
             WHERE child.parent_id IS NULL
               AND btrim(COALESCE(child.company_name, '')) <> ''
            RETURNING id, name, company_id
        )
        UPDATE res_partner child
           SET parent_id = promoted.id
          FROM promoted
         WHERE child.parent_id IS NULL
           AND btrim(child.company_name) = promoted.name
           AND child.company_id IS NOT DISTINCT FROM promoted.company_id
        """
    )
    return cr.rowcount


def migrate(cr, version):
    if not version:
        return
    if not schema.column_exists(cr, _TABLE, _COLUMN):
        return

    cr.execute(
        """
        SELECT count(*) FROM res_partner
         WHERE btrim(COALESCE(company_name, '')) <> ''
        """
    )
    held = cr.fetchone()[0]
    if not held:
        cr.execute(f'ALTER TABLE {_TABLE} DROP COLUMN "{_COLUMN}"')
        return

    cr.execute(
        """
        SELECT count(*) FROM res_partner
         WHERE btrim(COALESCE(company_name, '')) <> ''
           AND parent_id IS NOT NULL
        """
    )
    superseded = cr.fetchone()[0]

    linked = _link_to_existing_companies(cr)
    created = _create_missing_companies(cr)

    cr.execute(f'ALTER TABLE {_TABLE} DROP COLUMN "{_COLUMN}"')

    _logger.info(
        "base 1.24: promoted res.partner.company_name into parent companies -- "
        "%s contact(s) held a company name, %s linked to a company that already "
        "existed, %s linked to one created here, %s already had a parent and "
        "kept it",
        held,
        linked,
        created,
        superseded,
    )
