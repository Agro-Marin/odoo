"""Normalise `base_import.mapping.column_name` to its lookup form.

Column names are now stored stripped and lower-cased, through the same helper
`_get_mapping_suggestion` uses to look them up (`_normalize_column_name`). They
previously went in verbatim while the lookup lower-cased, so a header carrying
the surrounding whitespace spreadsheet exports routinely produce never matched
the mapping the user had just taught the system.

Rows written before that change keep their original case. The lookup normalises
on read, so they still resolve -- but two rows differing only in case or padding
("Name", "name ") are distinct under `_column_unique_per_model` while collapsing
to one key on read, so which one wins is arbitrary. Fold them here: keep the
most recently written row, which is the one the suggestion code would have
picked anyway.
"""


def migrate(cr, version):
    # Collapse rows that only differ by case/padding, before normalising makes
    # them violate the unique constraint. Newest wins.
    cr.execute("""
        DELETE FROM base_import_mapping
              WHERE id NOT IN (
                    SELECT max(id)
                      FROM base_import_mapping
                     GROUP BY res_model, lower(btrim(column_name))
                    )
    """)
    deleted = cr.rowcount

    cr.execute("""
        UPDATE base_import_mapping
           SET column_name = lower(btrim(column_name))
         WHERE column_name <> lower(btrim(column_name))
    """)
    normalized = cr.rowcount

    if deleted or normalized:
        from logging import getLogger
        getLogger(__name__).info(
            "base_import.mapping: normalized %s column names and removed %s "
            "case/whitespace-duplicate rows",
            normalized, deleted,
        )
