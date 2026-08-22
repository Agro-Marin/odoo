import logging

_logger = logging.getLogger(__name__)

MODEL = "stock.picking.type"


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM ir_attachment
              WHERE res_model = %s
                 OR id IN (SELECT a.id
                             FROM ir_attachment a
                             JOIN message_attachment_rel r ON r.attachment_id = a.id
                             JOIN mail_message m ON m.id = r.message_id
                            WHERE m.model = %s)
        """,
        [MODEL, MODEL],
    )
    cr.execute("DELETE FROM mail_followers WHERE res_model = %s", [MODEL])
    cr.execute("DELETE FROM mail_message WHERE model = %s", [MODEL])
    _logger.info("stock: dropped %s orphaned mail messages for %s", cr.rowcount, MODEL)
