r"""Pre-migration: ``elligible_for_accrual_rate`` is spelled ``eligible_for_accrual_rate``.

The field was misspelled with a double L on both models that declare it,
``hr.leave.type`` and ``resource.calendar.leaves``. Its own label read "Eligible
for Accrual Rate" from the day it landed, so this is a typo in the identifier and
never a deliberate spelling -- which is why the compute answering for it was
already named ``_compute_eligible_for_accrual_rate`` and read as the mismatch under
ADR-0049. Correcting the identifier makes the hook right where renaming the hook
would have propagated the typo.

Unlike the sibling renames in stock, mrp, repair and account, this field is
``store=True``, so a column moves on each of the two tables. The rename is done
here, before the ORM reaches the schema: left to it, the new name would be created
as an empty column and every existing value silently lost, which for a boolean
driving accrual computation means every time-off type quietly falls back to False.

Stored references move too -- user-edited view arch, saved filters, window actions
and server-action code -- since a domain naming a field the registry no longer has
raises when the domain is READ, not when the module is upgraded.

The guards make every statement idempotent: the columns are renamed only while the
old name is present and the new one is not, and the text rewrites stop matching
once a row is rewritten.
"""

from odoo.db.schema import column_exists

OLD = "elligible_for_accrual_rate"
NEW = "eligible_for_accrual_rate"
TABLES = ("hr_leave_type", "resource_calendar_leaves")
MODELS = ("hr.leave.type", "resource.calendar.leaves")


def _rewrite(expr):
    """SQL rewriting the token whole-word in ``expr``.

    :param str expr: SQL expression (column or cast) to rewrite
    :return: SQL expression with the rename applied
    :rtype: str
    """
    return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"


def _matches(expr):
    """SQL guard true when ``expr`` still names the old field.

    :param str expr: SQL expression (column or cast) to test
    :return: SQL boolean expression
    :rtype: str
    """
    return rf"{expr} ~ '\y{OLD}\y'"


def migrate(cr, version):
    """Rename the two stored columns and repoint stored references.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    for table in TABLES:
        if column_exists(cr, table, OLD) and not column_exists(cr, table, NEW):
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{OLD}" TO "{NEW}"')

    cr.execute(
        """
        UPDATE ir_model_fields SET name = %s
         WHERE name = %s AND model = ANY(%s)
        """,
        (NEW, OLD, list(MODELS)),
    )
    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite("arch_db::text")}::jsonb
         WHERE {_matches("arch_db::text")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")},
               sort = {_rewrite("sort")}
         WHERE {_matches("domain")}
            OR {_matches("context")}
            OR {_matches("sort")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")}
         WHERE {_matches("domain")} OR {_matches("context")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_act_server
           SET code = {_rewrite("code")}
         WHERE {_matches("code")}
        """
    )
