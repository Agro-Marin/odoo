r"""Pre-migration: ``account.analytic.distribution.model`` now requires a distribution.

A distribution model exists only to carry a distribution and apply it to matching
records. One without a distribution matches partners, categories or companies and
then contributes nothing, so it is indistinguishable from a row nobody finished
creating -- and ``_get_distribution`` pays to fetch it on every call.

Making the field ``required`` puts a ``NOT NULL`` on the column, and ``ALTER TABLE``
fails outright if any row still holds NULL. So the empty rows have to go before the
registry tries to add the constraint, which is why this runs ``pre``.

The rows are deleted rather than repaired because there is nothing to repair them
with: a distribution cannot be invented from a partner or a company, and any value
this script guessed would silently start applying itself to real records. Deleting
is also what the model already means -- an empty distribution model has never had an
effect on anything.

``{}`` needs no separate handling: ``Json.convert_to_cache``
(``odoo/orm/fields/misc.py:111-115``) maps every falsy value to ``None``, so an empty
mapping was already stored as NULL and this one condition catches both.

The statement is idempotent: once the rows are gone the ``WHERE`` matches nothing.
"""

import logging

_logger = logging.getLogger(__name__)

TABLE = "account_analytic_distribution_model"
COLUMN = "analytic_distribution"


def migrate(cr, version):
    """Delete distribution models that carry no distribution.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    cr.execute(
        f"""
        DELETE FROM {TABLE}
              WHERE {COLUMN} IS NULL
          RETURNING id
        """
    )
    if deleted := cr.fetchall():
        _logger.info(
            "analytic: deleted %s distribution model(s) with no distribution: %s",
            len(deleted),
            ", ".join(str(row[0]) for row in deleted),
        )
