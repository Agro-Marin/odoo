"""Pre-migration: ``product_manufacturer`` is gone, dissolved into ``product``.

The module was four fields on ``product.product``, their mirrors on
``product.template``, three fields and an action on ``res.partner``, and six
views. Nothing in it needed a module of its own -- ``product`` already owns the
template/variant mirror machinery the four fields ride on
(``_compute_template_field_from_variant_field`` and ``_set_product_variant_field``)
and already extends ``res.partner``. So every declaration moved into ``product``
under the same field names, and no column changes shape.

This runs in ``base`` rather than in ``product`` because two things have to
happen before the graph is assembled:

  * the module row has to go. Left alone, the loader finds ``product_manufacturer``
    installed and absent from disk and the load ends on ``Some modules have
    inconsistent states after upgrade``, with the row stuck at ``to upgrade`` on
    that run and every run after it. Nothing clears that state, because there is
    no code left to upgrade it with, and a database with any module pending
    stops ``ir_cron`` and ``ir_job`` outright.

  * the ``ir_model_data`` rows have to change hands BEFORE ``product`` loads its
    data files. Nine of them name records that ``product`` now declares, and
    twelve more are the auto-generated ``ir.model.fields`` rows behind the seven
    new columns. An orphaned field xmlid is the expensive one: ``_process_end``
    deletes the RECORD behind an orphaned xmlid, and for an ``ir.model.fields``
    row that drops the column. ``c26be9c73604`` measured 54 columns of stock data
    lost that way on a run exiting 0.

Every row is therefore repointed rather than deleted, with three exceptions
listed in SUPERSEDED below.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = "product_manufacturer"
TARGET = "product"

# Records that keep existing under `product` but cannot keep their name. The
# first two collided head-on: the module declared `view_product_template_search`
# and `view_product_template_form`, which are the ids of the very views in
# `product` they inherited, and inside one module the second <record> would
# become an update of the base view rather than a new one. The other four are
# renamed to `product`'s own naming, since nothing outside the module reads them
# by name except `agromarin/product_asset`'s Manufacturers menu, updated in the
# same commit.
RENAMED = {
    "manufacturer_view_search": "view_partner_manufacturer_search",
    "manufacturer_view_tree": "view_partner_manufacturer_list",
    "manufacturer_view_kanban": "view_partner_manufacturer_kanban",
    "manufacturer_view_form": "view_partner_manufacturer_form",
    "manufacturer_action": "action_partner_manufacturers",
    "view_partner_form": "view_partner_form_manufacturer",
}

# The three inheriting views whose arch is now inline in the view they used to
# inherit -- `product` cannot sensibly ship a view of its own that patches its
# own base view. They are deleted here rather than left to `_process_end`,
# because reaping runs at the END of the load and until then the base form would
# carry the manufacturer group twice.
#
# `ir_ui_view_inherit_id_fkey` is RESTRICT, not CASCADE, so a view another view
# inherits cannot be dropped; the guard below refuses rather than taking the
# whole migration down with a RestrictViolation. Nothing in this workspace
# inherits any of the three, but a database may carry a studio or hand-made view
# that does, and that is a decision for whoever owns it.
SUPERSEDED = (
    "view_product_template_search",
    "view_product_template_form",
    "product_variant_easy_edit_view",
)


def migrate(cr, version):
    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (MODULE,))
    row = cr.fetchone()
    if not row:
        return
    module_id, state = row

    _drop_superseded_views(cr)

    for old_name, new_name in RENAMED.items():
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE module = %s AND name = %s",
            (new_name, MODULE, old_name),
        )

    _drop_duplicate_rows(cr)
    _refuse_remaining_collisions(cr)

    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s", (TARGET, MODULE)
    )
    _logger.info("repointed %s xml id(s) from %s to %s", cr.rowcount, MODULE, TARGET)

    cr.execute(
        "DELETE FROM ir_model_data "
        "WHERE module = 'base' AND model = 'ir.module.module' AND res_id = %s",
        (module_id,),
    )
    cr.execute(
        "DELETE FROM ir_module_module_dependency WHERE name = %s OR module_id = %s",
        (MODULE, module_id),
    )
    cr.execute("DELETE FROM ir_module_module_exclusion WHERE name = %s", (MODULE,))
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))
    _logger.info("dropped the %s module row, which was %s", MODULE, state)


def _drop_superseded_views(cr):
    # `= ANY(%s)` with a list, never `IN %s`: psycopg 3 binds server-side, so the
    # placeholder reaches PostgreSQL as $2 and `IN $2` is a syntax error.
    names = list(SUPERSEDED)
    cr.execute(
        """
        SELECT d.name, count(v.id)
          FROM ir_model_data d
          JOIN ir_ui_view v ON v.inherit_id = d.res_id
         WHERE d.module = %s AND d.model = 'ir.ui.view' AND d.name = ANY(%s)
         GROUP BY d.name
        """,
        (MODULE, names),
    )
    inherited = cr.fetchall()
    if inherited:
        raise ValueError(
            f"{MODULE} views {inherited} are inherited by other views; "
            f"ir_ui_view_inherit_id_fkey is RESTRICT, so they cannot be dropped. "
            f"Repoint or delete the inheriting views first."
        )

    cr.execute(
        """
        DELETE FROM ir_ui_view
              WHERE id IN (SELECT res_id
                             FROM ir_model_data
                            WHERE module = %s AND model = 'ir.ui.view'
                              AND name = ANY(%s))
        """,
        (MODULE, names),
    )
    deleted = cr.rowcount
    cr.execute(
        "DELETE FROM ir_model_data "
        "WHERE module = %s AND model = 'ir.ui.view' AND name = ANY(%s)",
        (MODULE, names),
    )
    _logger.info("dropped %s superseded view(s), now inline in %s", deleted, TARGET)


def _drop_duplicate_rows(cr):
    # Every module that touches a model gets its own auto-generated row for that
    # model's xml id, so `model_res_partner`, `model_product_product` and
    # `model_product_template` exist under both names and point at one record.
    # Only rows that duplicate a `product` row record-for-record are dropped.
    cr.execute(
        """
        DELETE FROM ir_model_data d
              WHERE d.module = %s
                AND EXISTS (SELECT 1
                              FROM ir_model_data o
                             WHERE o.module = %s
                               AND o.name = d.name
                               AND o.model = d.model
                               AND o.res_id = d.res_id)
        """,
        (MODULE, TARGET),
    )
    _logger.info("dropped %s xml id(s) %s already owns", cr.rowcount, TARGET)


def _refuse_remaining_collisions(cr):
    # A name still owned by both modules would now name two different records,
    # and the repointing UPDATE would die on ir_model_data's uniqueness index
    # with nothing said about which name. Fail with the names instead.
    cr.execute(
        """
        SELECT d.name FROM ir_model_data d
         WHERE d.module = %s
           AND EXISTS (SELECT 1 FROM ir_model_data o
                        WHERE o.module = %s AND o.name = d.name)
         ORDER BY d.name
        """,
        (MODULE, TARGET),
    )
    clashing = [name for (name,) in cr.fetchall()]
    if clashing:
        raise ValueError(
            f"{MODULE} and {TARGET} both own {clashing}, naming different "
            f"records; add them to RENAMED before repointing"
        )
