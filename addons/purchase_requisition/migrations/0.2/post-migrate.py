import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE product_supplierinfo AS supplierinfo
           SET date_start = requisition.date_start,
               date_end = requisition.date_end
          FROM purchase_requisition_line AS requisition_line
          JOIN purchase_requisition AS requisition
            ON requisition.id = requisition_line.requisition_id
         WHERE supplierinfo.purchase_requisition_line_id = requisition_line.id
           AND requisition.requisition_type = 'blanket_order'
           AND supplierinfo.date_start IS NULL
           AND supplierinfo.date_end IS NULL
           AND (requisition.date_start IS NOT NULL OR requisition.date_end IS NOT NULL)
        """
    )
    _logger.info(
        "purchase_requisition: dated %s agreement vendor price(s)", cr.rowcount
    )
