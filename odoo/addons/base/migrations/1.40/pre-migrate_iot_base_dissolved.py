"""Pre-migration: ``iot_base`` is gone, its three client files now live in ``iot``.

``iot_base`` held the browser-side longpolling client and nothing else: no
models, no data files, no records of any kind. It sat in community only so that
community ``point_of_sale`` could bundle its assets for an enterprise module to
patch, and ``point_of_sale`` itself imported nothing from it. The files moved
into ``iot``, which moved from ``enterprise/`` to ``odoo/addons/`` at the same
time and kept its name, so no other module row and no ``ir_model_data`` row
changes hands.

This runs in ``base`` because the row has to go before the graph is assembled.
Left alone, the loader finds ``iot_base`` installed and absent from disk, warns
``not installable, skipped``, and then fails the load with ``Some modules have
inconsistent states after upgrade``, on that run and on every run after it. The
state it is stuck in is ``to upgrade``, which nothing can ever clear because
there is no code left to upgrade it with.

Measured on a rehearsal database built from the pre-split tree: ``iot_base``
owned 0 ``ir_model_data`` rows and, once ``point_of_sale`` dropped it, 0
dependency rows, so deleting the row takes no record with it.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = "iot_base"


def migrate(cr, version):
    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (MODULE,))
    row = cr.fetchone()
    if not row:
        return
    module_id, state = row

    cr.execute("SELECT count(*) FROM ir_model_data WHERE module = %s", (MODULE,))
    owned = cr.fetchone()[0]
    if owned:
        # Never seen: the module shipped no data file. If a database somehow has
        # rows here they name records this migration must not orphan, because
        # _process_end deletes the record behind an xml id whose module is gone.
        raise ValueError(
            f"{MODULE} unexpectedly owns {owned} ir_model_data row(s); "
            f"repoint them to 'iot' before dropping the module row"
        )

    cr.execute(
        "DELETE FROM ir_module_module_dependency WHERE name = %s OR module_id = %s",
        (MODULE, module_id),
    )
    cr.execute("DELETE FROM ir_module_module_exclusion WHERE name = %s", (MODULE,))
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))
    _logger.info("dropped the %s module row, which was %s", MODULE, state)
