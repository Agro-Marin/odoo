import logging

from odoo import SUPERUSER_ID, api
from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)

LEGACY_SOURCE = "document.document.document_token"


def migrate(cr, version):
    if not version:
        return
    _traceback_authors_become_members(cr)
    if not column_exists(cr, "document_document", "document_token"):
        return
    # every document whose link is on keeps its URL until a year after the
    # upgrade (decision C1): the token it was shared
    # with becomes a link row holding its hash, and a new link the server can
    # show again is issued beside it with the same expiry
    cr.execute(
        """
        INSERT INTO access_link (
            res_model, res_id, role, audience, token_hash, token_hint, date_to,
            cause, legacy_source, company_id, use_count, expiry_waived,
            create_uid, create_date, write_uid, write_date
        )
        SELECT 'document.document', d.id, d.access_via_link, 'anyone',
               encode(sha256(convert_to(d.document_token, 'UTF8')), 'hex'),
               left(d.document_token, 4),
               (now() AT TIME ZONE 'UTC') + interval '365 days',
               'migration', %s, d.company_id, 0, false,
               %s, now() AT TIME ZONE 'UTC',
               %s, now() AT TIME ZONE 'UTC'
          FROM document_document d
         WHERE d.access_via_link <> 'none'
           AND length(d.document_token) >= 16
           AND NOT EXISTS (
                SELECT 1 FROM access_link l
                 WHERE l.res_model = 'document.document'
                   AND l.res_id = d.id
                   AND l.legacy_source = %s
           )
        RETURNING res_id, date_to
        """,
        [LEGACY_SOURCE, SUPERUSER_ID, SUPERUSER_ID, LEGACY_SOURCE],
    )
    carried = cr.fetchall()
    env = api.Environment(cr, SUPERUSER_ID, {})
    documents = env["document.document"].with_context(active_test=False)
    for res_id, date_to in carried:
        documents.browse(res_id)._sync_document_links(date_to=date_to)
    cr.execute(
        "SELECT count(*) FROM document_document "
        "WHERE access_via_link <> 'none' AND length(document_token) < 16"
    )
    [too_short] = cr.fetchone()
    cr.execute("ALTER TABLE document_document DROP COLUMN document_token")
    _logger.info(
        "document: %s shared link(s) carried over as access.link rows until %s; "
        "%s token(s) too short to be a capability dropped",
        len(carried),
        carried[0][1] if carried else "-",
        too_short,
    )


def _traceback_authors_become_members(cr):
    # a visit no longer grants: the error reports their authors reached only
    # through the visit of their own link stay theirs as a view membership;
    # anyone else who visited one keeps the link, not the report
    cr.execute(
        """
        UPDATE document_access a
           SET role = 'view'
          FROM document_document d
          JOIN res_users u ON u.id = d.create_uid
          JOIN ir_config_parameter p ON p.key = 'document.support_folder'
         WHERE a.document_id = d.id
           AND a.role IS NULL
           AND a.partner_id = u.partner_id
           AND d.folder_id::text = p.value
        """
    )
    _logger.info(
        "document: %s error report(s) kept by their author as a member", cr.rowcount
    )
