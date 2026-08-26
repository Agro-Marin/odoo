import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Four CHECK constraints land on ir_mail_server with this version. PostgreSQL
    # refuses to add one that existing rows already violate, and Odoo answers that
    # by logging the failure and carrying on -- which would leave the guard absent
    # on exactly the databases that proved they needed it. Repair the rows first.
    #
    # A server with no host was never usable: it takes part in from_filter
    # selection like any other and then raises "Missing SMTP Server" on every mail
    # routed to it. Archive it rather than invent a transport for it -- mail then
    # leaves through a server that works, and the record is still there to fix.
    cr.execute(
        """
        UPDATE ir_mail_server
           SET active = FALSE
         WHERE active
           AND smtp_authentication != 'cli'
           AND COALESCE(smtp_host, '') = ''
     RETURNING name
        """
    )
    if archived := [row[0] for row in cr.fetchall()]:
        _logger.warning(
            "Archived %d outgoing mail server(s) saved without an SMTP server "
            "address, which could never have delivered: %s",
            len(archived),
            ", ".join(archived),
        )

    cr.execute(
        """
        UPDATE ir_mail_server
           SET smtp_port = CASE
                   WHEN smtp_encryption IN ('ssl', 'ssl_strict') THEN 465
                   ELSE 25
               END
         WHERE smtp_authentication != 'cli'
           AND (smtp_port IS NULL OR smtp_port < 1 OR smtp_port > 65535)
     RETURNING name
        """
    )
    if reset := [row[0] for row in cr.fetchall()]:
        _logger.warning(
            "Reset the SMTP port of %d outgoing mail server(s) that held a value "
            "outside 1-65535: %s",
            len(reset),
            ", ".join(reset),
        )

    # 0 is the documented "fall back to base.default_max_email_size"; a negative
    # ceiling turned every attachment on that server into a link, silently.
    cr.execute(
        """
        UPDATE ir_mail_server
           SET max_email_size = 0
         WHERE max_email_size < 0
     RETURNING name
        """
    )
    if cleared := [row[0] for row in cr.fetchall()]:
        _logger.warning(
            "Cleared the negative maximum email size of %d outgoing mail "
            "server(s), which was stripping every attachment: %s",
            len(cleared),
            ", ".join(cleared),
        )
