"""Make `base_import.mapping` satisfy its new NOT NULL + UNIQUE constraints.

Two kinds of rows predate them and would make the constraints fail to apply
(Odoo warns and skips rather than aborting, so the table would silently stay
unconstrained):

* rows with a NULL ``field_name`` -- ``execute_import`` used to store one for
  every column the user explicitly left *unmapped*. They can never produce a
  suggestion, they accumulate on every import, and nothing vacuums them.
* duplicate ``(res_model, column_name)`` pairs -- there was no unique
  constraint and concurrent imports race between the SELECT and the INSERT.
  Keep the most recently written row, which is the one the suggestion code
  would have picked anyway.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM base_import_mapping
              WHERE field_name IS NULL
                 OR res_model IS NULL
                 OR column_name IS NULL
    """)
    deleted_unmapped = cr.rowcount

    cr.execute("""
        DELETE FROM base_import_mapping
              WHERE id NOT IN (
                    SELECT max(id)
                      FROM base_import_mapping
                     GROUP BY res_model, column_name
                    )
    """)
    deleted_duplicates = cr.rowcount

    if deleted_unmapped or deleted_duplicates:
        from logging import getLogger
        getLogger(__name__).info(
            "base_import.mapping: removed %s unmapped-column rows and %s "
            "duplicate (res_model, column_name) rows",
            deleted_unmapped, deleted_duplicates,
        )
