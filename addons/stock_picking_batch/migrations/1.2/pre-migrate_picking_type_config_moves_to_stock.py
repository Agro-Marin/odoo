import logging

_logger = logging.getLogger(__name__)

MOVED_FIELDS = [
    "auto_batch",
    "batch_group_by_partner",
    "batch_group_by_destination",
    "batch_group_by_src_loc",
    "batch_group_by_dest_loc",
    "wave_group_by_product",
    "wave_group_by_category",
    "wave_category_ids",
    "wave_group_by_location",
    "wave_location_ids",
    "batch_max_lines",
    "batch_max_pickings",
    "batch_auto_confirm",
    "batch_properties_definition",
]


def migrate(cr, version):
    cr.execute(
        """
            UPDATE ir_model_data d
               SET module = 'stock'
              FROM ir_model_fields f, ir_model m
             WHERE d.module = 'stock_picking_batch'
               AND d.model = 'ir.model.fields'
               AND d.res_id = f.id
               AND f.model_id = m.id
               AND m.model = 'stock.picking.type'
               AND f.name = ANY(%s)
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data e
                    WHERE e.module = 'stock'
                      AND e.name = d.name
                      AND e.model = 'ir.model.fields'
               )
        """,
        (MOVED_FIELDS,),
    )
    _logger.info("repointed %s operation-type fields at stock", cr.rowcount)
