"""Pre-migration: ``mail_enterprise`` is gone, dissolved into ``mail``.

The bridge kept only what needs ``web_mobile``, and that went to ``mail_mobile``,
which already exists and is installed in its own right. So no row changes hands
and nothing is renamed: the module simply stops existing.

This runs in ``base`` because the row has to go before the graph is assembled.
Left alone, the loader finds ``mail_enterprise`` installed and absent from disk
and the load ends on ``Some modules have inconsistent states after upgrade``,
with the row stuck at ``to upgrade`` on that run and every run after it. Nothing
clears that state, because there is no code left to upgrade it with, and a
database with any module pending stops ``ir_cron`` and ``ir_job`` outright.

Unlike ``iot_base``, this module is not empty: it owns three ``ir_model_data``
rows, all of them auto-generated for ``publisher_warranty.contract`` -- the
model and its ``id`` and ``display_name`` fields. Every one is a duplicate.
``mail`` declares that model in ``models/update.py`` and owns the same three
xml ids, and so does ``website_mail``, because each module that touches a model
gets its own row for the generated ids. Dropping this module's copies orphans
nothing, and the guard below refuses to drop any row that is not in fact
duplicated somewhere else.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = "mail_enterprise"


def migrate(cr, version):
    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (MODULE,))
    row = cr.fetchone()
    if not row:
        return
    module_id, state = row

    # Only rows whose record is claimed by at least one surviving module. A row
    # that is the sole owner of its record must not be deleted here: _process_end
    # would find the record with no xml id and the record itself would go.
    cr.execute(
        """
            DELETE FROM ir_model_data d
                  WHERE d.module = %s
                    AND EXISTS (
                        SELECT 1 FROM ir_model_data o
                         WHERE o.module != %s
                           AND o.model = d.model
                           AND o.res_id = d.res_id
                    )
        """,
        (MODULE, MODULE),
    )
    dropped = cr.rowcount

    cr.execute("SELECT count(*) FROM ir_model_data WHERE module = %s", (MODULE,))
    kept = cr.fetchone()[0]
    if kept:
        cr.execute(
            "SELECT model, name FROM ir_model_data WHERE module = %s ORDER BY name",
            (MODULE,),
        )
        raise ValueError(
            f"{MODULE} still owns {kept} ir_model_data row(s) that no surviving "
            f"module claims: {cr.fetchall()}; repoint them before dropping the "
            f"module row"
        )

    cr.execute(
        "DELETE FROM ir_module_module_dependency WHERE name = %s OR module_id = %s",
        (MODULE, module_id),
    )
    cr.execute("DELETE FROM ir_module_module_exclusion WHERE name = %s", (MODULE,))
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))
    _logger.info(
        "dropped the %s module row, which was %s, and %s duplicated xml id(s)",
        MODULE,
        state,
        dropped,
    )
