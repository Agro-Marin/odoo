r"""Pre-migration: ``fiscal_year_search`` is now ``from_last_fiscal_year``.

``account.analytic.line`` carried a search-only Boolean whose name said only that
it existed to be searched. Under ADR-0049 the canonical spelling of its hook was
therefore ``_search_fiscal_year_search``, and the stutter is the symptom rather
than the defect: the name described the mechanism, which the declaration already
states two lines down in ``store=False`` and ``search=``.

The field is true for a line dated on or after the start of the previous fiscal
year, and the one filter that uses it has always been labelled "From last fiscal
year", so the label is where the name came from.

Nothing of this module's own data moves -- the field is ``store=False``, so there
is no column. What moves is any stored domain naming it, and a domain naming a
field the registry no longer has raises when the domain is READ rather than when
the module is upgraded, so an unrewritten favourite fails later and elsewhere. The
one shipped reference lives in ``account``'s analytic line search view and is
reloaded from XML by the upgrade itself; these statements exist for the artifacts
users made.

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

OLD = "fiscal_year_search"
NEW = "from_last_fiscal_year"
MODEL = "account.analytic.line"


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
    """Repoint stored domains from the old field name to the new one.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

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
         WHERE ({_matches("domain")}
                OR {_matches("context")}
                OR {_matches("sort")})
           AND model_id = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")}
         WHERE ({_matches("domain")} OR {_matches("context")})
           AND res_model = %s
        """,
        (MODEL,),
    )
