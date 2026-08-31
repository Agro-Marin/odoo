r"""Pre-migration: absorb ``stock_blocked_location`` into ``stock``.

The blocking feature is no longer a separate addon -- its fields, groups,
enforcement and views now ship inside ``stock`` itself. The columns are
untouched (same table, same names), so all that has to move is ownership.

It runs from ``base`` rather than from ``stock`` because a module row naming a
directory that no longer exists is fatal earlier than ``stock``'s own
pre-migration: ``module_graph.extend`` drops the missing module *and everything
that depends on it*, so ``marin`` would silently stop loading. ``base`` is
loaded and migrated before the graph is extended with any other module, which is
the only point where deleting the row still prevents that.

The three inherited views must be **deleted**, not re-homed. Their arch adds
``block_type`` to a form that now declares it natively, so a survivor makes the
combined arch carry the field twice and the upgrade fails on view validation --
and ``_process_end`` only garbage-collects them *after* the data files load,
which is too late.

Every statement is idempotent: each guard stops matching once its row is gone.
"""

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

ABSORBED = "stock_blocked_location"
ABSORBER = "stock"

DROPPED_VIEWS = (
    "view_stock_location_search_blocked",
    "view_stock_location_tree_blocked",
    "view_stock_location_form_blocked",
)


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return
    if not _is_installed(cr):
        return
    _drop_inherited_views(cr)
    _rehome_model_data(cr)
    _rehome_reflection(cr)
    _drop_module(cr)


def _is_installed(cr: "Cursor") -> bool:
    cr.execute("SELECT 1 FROM ir_module_module WHERE name = %s", (ABSORBED,))
    return bool(cr.fetchone())


def _drop_inherited_views(cr: "Cursor") -> None:
    cr.execute(
        """
        DELETE FROM ir_ui_view
         WHERE id IN (SELECT res_id FROM ir_model_data
                       WHERE module = %s AND model = 'ir.ui.view'
                         AND name = ANY(%s))
        """,
        (ABSORBED, list(DROPPED_VIEWS)),
    )
    dropped = cr.rowcount
    cr.execute(
        "DELETE FROM ir_model_data"
        " WHERE module = %s AND model = 'ir.ui.view' AND name = ANY(%s)",
        (ABSORBED, list(DROPPED_VIEWS)),
    )
    _logger.info("stock_blocked_location: dropped %d inherited view(s)", dropped)


def _rehome_model_data(cr: "Cursor") -> None:
    # ir_model_data is UNIQUE (module, name); a name stock already owns wins,
    # so the absorbed duplicate goes rather than blocking the rename.
    cr.execute(
        """
        DELETE FROM ir_model_data d
         WHERE d.module = %s
           AND EXISTS (SELECT 1 FROM ir_model_data o
                        WHERE o.module = %s AND o.name = d.name)
        """,
        (ABSORBED, ABSORBER),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s",
        (ABSORBER, ABSORBED),
    )
    _logger.info("stock_blocked_location: re-homed %d xml id(s) to stock", cr.rowcount)


def _rehome_reflection(cr: "Cursor") -> None:
    # ir_model_constraint.module and ir_model_relation.module both cascade on
    # delete, so anything left pointing at the absorbed module would vanish with
    # it and have to be reflected again on the next boot.
    for table, unique_by in (
        ("ir_model_constraint", "name"),
        ("ir_model_relation", "name"),
    ):
        cr.execute(
            f"""
            DELETE FROM {table} r
             USING ir_module_module absorbed, ir_module_module absorber
             WHERE r.module = absorbed.id
               AND absorbed.name = %s AND absorber.name = %s
               AND EXISTS (SELECT 1 FROM {table} o
                            WHERE o.module = absorber.id
                              AND o.{unique_by} = r.{unique_by})
            """,
            (ABSORBED, ABSORBER),
        )
        cr.execute(
            f"""
            UPDATE {table} r
               SET module = absorber.id
              FROM ir_module_module absorbed, ir_module_module absorber
             WHERE r.module = absorbed.id
               AND absorbed.name = %s AND absorber.name = %s
            """,
            (ABSORBED, ABSORBER),
        )


def _drop_module(cr: "Cursor") -> None:
    cr.execute("DELETE FROM ir_module_module_dependency WHERE name = %s", (ABSORBED,))
    cr.execute("DELETE FROM ir_module_module_exclusion WHERE name = %s", (ABSORBED,))
    cr.execute(
        "DELETE FROM ir_model_data"
        " WHERE module = 'base' AND model = 'ir.module.module' AND name = %s",
        (f"module_{ABSORBED}",),
    )
    cr.execute("DELETE FROM ir_module_module WHERE name = %s", (ABSORBED,))
    _logger.info("stock_blocked_location: module row removed, absorbed into stock")
