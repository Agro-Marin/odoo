"""Push manufacturer info down to the lone variant of templates that hold none.

Carried over from ``product_manufacturer``'s own ``19.0.1.2.0`` pre-migration
when that module was dissolved into this one. It ran there because the compute
had just been taught to see archived variants, and a template whose only variant
is archived -- or whose values never reached the variant at all -- would then be
read as empty and cleared. A database still stamped below ``19.0.1.2.0`` never
got that repair and would meet the same compute here for the first time, so the
backfill has to survive the fold.

It is idempotent: it only writes variants holding nothing at all, from templates
holding something, and only where the template has exactly one variant.

The column guard is what makes it safe on the overwhelming majority of
databases, which never had ``product_manufacturer`` and reach this script with
the columns about to be created by the registry rather than already present.
"""

import logging

_logger = logging.getLogger(__name__)

_HAS_COLUMNS = """
    SELECT count(*) FROM information_schema.columns
     WHERE table_name IN ('product_product', 'product_template')
       AND column_name = 'manufacturer_id'
"""

_BACKFILL_VARIANTS = """
    UPDATE product_product AS pp
       SET manufacturer_id = pt.manufacturer_id,
           manufacturer_pname = pt.manufacturer_pname,
           manufacturer_pref = pt.manufacturer_pref,
           manufacturer_purl = pt.manufacturer_purl
      FROM product_template AS pt
     WHERE pp.product_tmpl_id = pt.id
       AND pp.manufacturer_id IS NULL
       AND pp.manufacturer_pname IS NULL
       AND pp.manufacturer_pref IS NULL
       AND pp.manufacturer_purl IS NULL
       AND (pt.manufacturer_id IS NOT NULL
            OR pt.manufacturer_pname IS NOT NULL
            OR pt.manufacturer_pref IS NOT NULL
            OR pt.manufacturer_purl IS NOT NULL)
       AND (SELECT count(*) FROM product_product AS p2
             WHERE p2.product_tmpl_id = pt.id) = 1
"""


def migrate(cr, version):
    cr.execute(_HAS_COLUMNS)
    if cr.fetchone()[0] != 2:
        return
    cr.execute(_BACKFILL_VARIANTS)
    _logger.info(
        "pushed manufacturer info down to %s variant(s) that held none, so the "
        "compute cannot clear the template value",
        cr.rowcount,
    )
