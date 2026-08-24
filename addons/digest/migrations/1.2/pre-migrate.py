# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

_logger = logging.getLogger(__name__)

#: The four QWeb templates that shipped under `<data noupdate="1">`.
_TEMPLATES = (
    "digest_mail_layout",
    "digest_mail_main",
    "digest_section_mobile",
    "digest_tool_kpi",
)


def migrate(cr, version):
    """Let the digest email templates update with the module again.

    They were declared under `noupdate="1"`, so `ir_model_data.noupdate` was
    stamped true when they were first created and **no fix to the digest email
    ever reached a database that already had it**: the loader reads the stored
    flag, not the manifest, so dropping `noupdate` from the XML only helps a
    fresh install. Measured on a database installed from the old code and then
    upgraded, with the data file confirmed loaded both times:

        stored flag   XML noupdate   data file loaded   arch updated
        true          removed        yes                NO
        false         removed        yes                yes

    `pre-migrate` runs before the data files load, so clearing the flag here
    lets the very same upgrade apply the new arch.

    Only rows still carrying the flag are touched, so a database where someone
    deliberately cleared it is left alone.
    """
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'digest'
           AND model = 'ir.ui.view'
           AND name = ANY(%s)
           AND noupdate
        """,
        (list(_TEMPLATES),),
    )
    if cr.rowcount:
        _logger.info(
            "digest: %d email template(s) released from noupdate; they now "
            "update with the module, as mail's own layouts always have",
            cr.rowcount,
        )
