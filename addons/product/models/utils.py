# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import tools


def unlink_where_possible(records, delete):
    """Delete what can be deleted in ``records``, and report the rest.

    Product master data is routinely referenced by documents that must not be
    rewritten (variants on confirmed order lines, stock moves, ...), so deleting
    it is best-effort: callers archive whatever the database refuses. Which
    records those are is only knowable by asking, hence the savepoint.

    The batch is attempted as a whole and halved only when it fails, so the
    common case -- nothing is blocked -- costs a single statement. The attribute
    models used to open one savepoint per record unconditionally, which measured
    843 queries and 242 ``SAVEPOINT`` statements to delete 120 perfectly
    deletable values, against 7 queries for one batch attempt.

    Deleting nothing and archiving afterwards is deliberate: callers archive the
    returned recordset once, after every deletion has been attempted, so that
    archiving (which for these models cascades into value and variant updates)
    never runs part-way through and changes what the remaining attempts see.

    :param records: the recordset to delete
    :param delete: callable taking a sub-recordset and deleting it, e.g.
        ``lambda rs: super(MyModel, rs).unlink()`` -- supplied by the caller so
        that the right ``super()`` in its own MRO is used
    :returns: the sub-recordset that could not be deleted
    """
    if not records:
        return records
    try:
        with records.env.cr.savepoint(), tools.mute_logger("odoo.db"):
            delete(records)
    except Exception:
        # Every kind of exception is caught on purpose: the point is that the
        # operation does not fail, whatever the database (or a Python
        # constraint) objected to.
        if len(records) == 1:
            return records
        middle = len(records) // 2
        return unlink_where_possible(records[:middle], delete) | (
            unlink_where_possible(records[middle:], delete)
        )
    return records.browse()
