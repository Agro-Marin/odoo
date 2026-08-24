from odoo import api, models
from odoo.tools import SQL, Query


def _sql_affecting_base_tax_ids(alias: SQL, line_id: SQL) -> SQL:
    """
    This table builds a reference table based on the tax_ids field, with the following changes:
      - flatten the group of taxes
      - exclude the taxes having 'is_base_affected' set to False.
    Those allow to match only base_line_1 when finding the base lines of tax_line_1, as we need to find
    base lines having a 'affecting_base_tax_ids' ending with [10_affect_base, 20], not only containing
    '10_affect_base'. Otherwise, base_line_2/3 would also be matched.
    In our example, as all the taxes are set to be affected by previous ones affecting the base, the
    result is similar to the table 'account_move_line_account_tax_rel':
    Id                 Tax_ids
    -------------------------------------------
    base_line_1        [10_affect_base, 20]
    base_line_2        [10_affect_base, 5]
    base_line_3        [10_affect_base, 5]
    """
    return SQL(
        """
        LEFT JOIN LATERAL (
            SELECT ARRAY_AGG(sub.tax_id ORDER BY sub.sequence, sub.tax_id) AS tax_ids
            FROM (
                SELECT
                    COALESCE(filiation.child_tax, affecting_tax.id) AS tax_id,
                    affecting_tax.sequence
                FROM account_move_line_account_tax_rel tax_rel
                JOIN account_tax affecting_tax ON
                    affecting_tax.id = tax_rel.account_tax_id
                LEFT JOIN account_tax_filiation_rel filiation ON
                    filiation.parent_tax = affecting_tax.id
                    AND affecting_tax.amount_type = 'group'
                WHERE affecting_tax.is_base_affected
                AND tax_rel.account_move_line_id = %(line_id)s
            ) AS sub
        ) %(alias)s ON TRUE""",
        alias=alias,
        line_id=line_id,
    )


def _sql_taxable_base(sign_of: SQL, amount: SQL) -> SQL:
    # a fixed-amount tax is spread over quantity, not over the base; the sign comes from the
    # base LINE even where the summed amount is a dispatched share of it
    return SQL(
        """CASE WHEN tax.amount_type = 'fixed'
            THEN CASE WHEN %(sign_of)s < 0 THEN -1 ELSE 1 END * ABS(COALESCE(base_line.quantity, 1.0))
            ELSE %(amount)s
            END""",
        sign_of=sign_of,
        amount=amount,
    )


def _sql_taxable_base_window(
    sign_of: SQL, amount: SQL, suffix: SQL, partition: SQL, order: SQL
) -> SQL:
    return SQL(
        """SUM(%(taxable_base)s)
               OVER (PARTITION BY %(partition)s ORDER BY %(order)s) AS cumulated_base_amount%(suffix)s,
           SUM(%(taxable_base)s)
               OVER (PARTITION BY %(partition)s) AS total_base_amount%(suffix)s""",
        taxable_base=_sql_taxable_base(sign_of, amount),
        suffix=suffix,
        partition=partition,
        order=order,
    )


def _sql_prorata_share(
    cumulated: SQL, total_base: SQL, total_amount: SQL, precision: SQL
) -> SQL:
    return SQL(
        """ROUND(
            COALESCE(SIGN(%(cumulated)s) * %(total_amount)s * ABS(%(cumulated)s) / NULLIF(%(total_base)s, 0.0), 0.0),
            %(precision)s
        )""",
        cumulated=cumulated,
        total_base=total_base,
        total_amount=total_amount,
        precision=precision,
    )


def _sql_dispatched_amount(share: SQL, partition: SQL, order: SQL) -> SQL:
    """Dispatch the last cents: each row takes the delta of the rounded cumulated prorata.

    ``order`` must be a total order over the partition — the same one the cumulated sum was
    built with. Ties there leave the LAG picking an arbitrary peer, which both misallocates
    the rows and breaks the telescoping that makes them add up to ``total_amount``.
    """
    return SQL(
        "%(share)s - LAG(%(share)s, 1, 0.0) OVER (PARTITION BY %(partition)s ORDER BY %(order)s)",
        share=share,
        partition=partition,
        order=order,
    )


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.model
    def _get_query_tax_details_from_domain(self, domain, fallback: bool = True) -> SQL:
        return self._get_query_tax_details(self._search(domain), fallback=fallback)

    @api.model
    def _get_base_tax_line_mapping_conditions(self) -> list[SQL]:
        return []

    @api.model
    def _get_query_tax_details(self, query: Query, fallback: bool = True) -> SQL:
        table_references = query.from_clause
        search_condition = query.where_clause

        if fallback:
            fallback_query = SQL(
                """
                UNION ALL

                SELECT
                    account_move_line.id AS tax_line_id,
                    base_line.id AS base_line_id,
                    base_line.id AS src_line_id,
                    base_line.balance AS base_amount,
                    base_line.amount_currency AS base_amount_currency,
                    TRUE AS is_fallback
                FROM %(table_references)s
                JOIN account_move_line_account_tax_rel tax_rel ON
                    tax_rel.account_tax_id = COALESCE(account_move_line.group_tax_id, account_move_line.tax_line_id)
                JOIN account_move_line base_line ON
                    base_line.id = tax_rel.account_move_line_id
                    AND base_line.tax_repartition_line_id IS NULL
                    AND base_line.move_id = account_move_line.move_id
                    AND base_line.currency_id = account_move_line.currency_id
                LEFT JOIN mapped_tax_lines ON
                    mapped_tax_lines.tax_line_id = account_move_line.id
                LEFT JOIN mapped_base_taxes ON
                    mapped_base_taxes.base_line_id = base_line.id
                    AND mapped_base_taxes.matched_tax_id = account_move_line.tax_line_id
                WHERE (
                    /* this tax line matched nothing at all -- the historical all-or-nothing
                       case, where approximating every one of its base lines is the best
                       available answer */
                    mapped_tax_lines.tax_line_id IS NULL
                    /* or it matched some base lines but not this one, and no sibling tax
                       line of the same tax covers it either. Without the sibling test a
                       tax split across two tax lines -- by analytic distribution, or by the
                       sign of the base on a misc entry -- would have every base line
                       counted under both of them. */
                    OR mapped_base_taxes.base_line_id IS NULL
                )
                AND %(search_condition)s
                """,
                table_references=table_references,
                search_condition=search_condition,
            )
            fallback_lookups = SQL(
                """
                mapped_tax_lines AS (
                    SELECT DISTINCT tax_line_id FROM base_tax_line_mapping
                ),
                mapped_base_taxes AS (
                    SELECT DISTINCT base_line_id, matched_tax_id FROM base_tax_line_mapping
                ),"""
            )
        else:
            fallback_query = SQL()
            fallback_lookups = SQL()

        # Both dispatch steps walk their rows in the same total order they accumulated them in.
        dispatch_window_partition = SQL("tax_line.id, account_move_line.id")
        dispatch_window_order = SQL("tax_line.tax_line_id, base_line.id")
        dispatch_partition = SQL("sub.tax_line_id, sub.src_line_id")
        dispatch_order = SQL("sub.tax_id, sub.base_line_id")

        final_window_partition = SQL("tax_line.id")
        final_window_order = SQL(
            "tax_line.tax_line_id, sub.base_line_id, sub.src_line_id"
        )
        final_partition = SQL("sub.tax_line_id")
        final_order = SQL("sub.tax_id, sub.base_line_id, sub.src_line_id")

        return SQL(
            """
            /*
            As example to explain the different parts of the query, we'll consider a move with the following lines:
            Name            Tax_line_id         Tax_ids                 Debit       Credit      Base lines
            ---------------------------------------------------------------------------------------------------
            base_line_1                         10_affect_base, 20      1000
            base_line_2                         10_affect_base, 5       2000
            base_line_3                         10_affect_base, 5       3000
            tax_line_1      10_affect_base      20                                  100         base_line_1
            tax_line_2      20                                                      220         base_line_1
            tax_line_3      10_affect_base      5                                   500         base_line_2/3
            tax_line_4      5                                                       275         base_line_2/3
            */

            WITH base_tax_line_mapping AS (

                /*
                Create the mapping of each tax lines with their corresponding base lines.

                In the example, it will give the following values:
                    base_line_id     tax_line_id    base_amount
                    -------------------------------------------
                    base_line_1      tax_line_1         1000
                    base_line_1      tax_line_2         1000
                    base_line_2      tax_line_3         2000
                    base_line_2      tax_line_4         2000
                    base_line_3      tax_line_3         3000
                    base_line_3      tax_line_4         3000
                */

                SELECT
                    account_move_line.id AS tax_line_id,
                    base_line.id AS base_line_id,
                    base_line.balance AS base_amount,
                    base_line.amount_currency AS base_amount_currency,

                    /* which tax matched this pair, so the fallback can ask whether a base
                       line is already covered by SOME tax line of that tax rather than only
                       by the one it is currently looking at */
                    account_move_line.tax_line_id AS matched_tax_id

                FROM %(table_references)s
                JOIN account_tax_repartition_line tax_rep ON
                    tax_rep.id = account_move_line.tax_repartition_line_id
                JOIN account_tax tax ON
                    tax.id = account_move_line.tax_line_id
                JOIN account_move_line_account_tax_rel tax_rel ON
                    tax_rel.account_tax_id = COALESCE(account_move_line.group_tax_id, account_move_line.tax_line_id)
                JOIN account_move move ON
                    move.id = account_move_line.move_id
                JOIN account_move_line base_line ON
                    base_line.id = tax_rel.account_move_line_id
                    AND base_line.tax_repartition_line_id IS NULL
                    AND base_line.move_id = account_move_line.move_id
                    AND (
                        move.move_type != 'entry'
                        OR (tax.tax_exigibility = 'on_payment' AND tax.cash_basis_transition_account_id IS NOT NULL)
                        OR sign(account_move_line.balance) = sign(base_line.balance * tax.amount * tax_rep.factor_percent)
                    )
                    AND COALESCE(base_line.partner_id, 0) = COALESCE(account_move_line.partner_id, 0)
                    AND base_line.currency_id = account_move_line.currency_id
                    -- a tax line whose company currency went missing cannot be priced, and
                    -- every downstream CTE drops it; excluded here so it cannot serve as the
                    -- src of another tax line's dispatch either
                    AND account_move_line.company_currency_id IS NOT NULL
                    AND (
                        COALESCE(tax_rep.account_id, base_line.account_id) = account_move_line.account_id
                        OR (tax.tax_exigibility = 'on_payment' AND tax.cash_basis_transition_account_id IS NOT NULL)
                    )
                    AND (
                        (tax.analytic IS NOT TRUE AND tax_rep.use_in_tax_closing IS TRUE)
                        OR (base_line.analytic_distribution IS NULL AND account_move_line.analytic_distribution IS NULL)
                        OR base_line.analytic_distribution = account_move_line.analytic_distribution
                    )
                    %(extra_conditions)s
                %(tax_line_tax_ids)s
                %(base_line_tax_ids)s
                WHERE account_move_line.tax_repartition_line_id IS NOT NULL
                    AND %(search_condition)s
                    AND (
                        -- keeping only the rows from affecting_base_tax_lines that end with the same taxes applied (see comment in tax_line_tax_ids)
                        NOT tax.include_base_amount
                        OR base_line_tax_ids.tax_ids[ARRAY_LENGTH(base_line_tax_ids.tax_ids, 1) - COALESCE(ARRAY_LENGTH(tax_line_tax_ids.tax_ids, 1), 0):ARRAY_LENGTH(base_line_tax_ids.tax_ids, 1)]
                            = ARRAY[account_move_line.tax_line_id] || COALESCE(tax_line_tax_ids.tax_ids, ARRAY[]::INTEGER[])
                    )
            ),


            %(fallback_lookups)s

            tax_amount_affecting_base_to_dispatch AS (

                /*
                Computes the total amount to dispatch in case of tax lines affecting the base of subsequent taxes.
                Such tax lines are an additional base amount for others lines, that will be truly dispatch in next
                CTE.

                In the example:
                    - tax_line_1 is an additional base of 100.0 from base_line_1 for tax_line_2.
                    - tax_line_3 is an additional base of 2/5 * 500.0 = 200.0 from base_line_2 for tax_line_4.
                    - tax_line_3 is an additional base of 3/5 * 500.0 = 300.0 from base_line_3 for tax_line_4.

                    src_line_id    base_line_id     tax_line_id    total_base_amount
                    -------------------------------------------------------------
                    tax_line_1     base_line_1      tax_line_2         1000
                    tax_line_3     base_line_2      tax_line_4         5000
                    tax_line_3     base_line_3      tax_line_4         5000
                */

                SELECT
                    tax_line.id AS tax_line_id,
                    base_line.id AS base_line_id,
                    account_move_line.id AS src_line_id,

                    comp_curr.decimal_places AS comp_curr_prec,
                    curr.decimal_places AS curr_prec,

                    tax_line.tax_line_id AS tax_id,

                    %(company_base_window)s,
                    account_move_line.balance AS total_tax_amount,

                    %(foreign_base_window)s,
                    account_move_line.amount_currency AS total_tax_amount_currency

                FROM %(table_references)s
                JOIN account_tax tax_include_base_amount ON
                    tax_include_base_amount.include_base_amount
                    AND tax_include_base_amount.id = account_move_line.tax_line_id
                JOIN base_tax_line_mapping base_tax_line_mapping ON
                    base_tax_line_mapping.tax_line_id = account_move_line.id
                JOIN account_move_line_account_tax_rel tax_rel ON
                    tax_rel.account_move_line_id = base_tax_line_mapping.tax_line_id
                JOIN account_tax tax ON
                    tax.id = tax_rel.account_tax_id
                JOIN account_move_line tax_line ON
                    -- same-move is implied by base_tax_line_mapping, which only pairs a tax
                    -- line with base lines of its own move; stated so the planner reaches
                    -- tax_line by index instead of filtering the mapping against itself
                    tax_line.move_id = account_move_line.move_id
                    AND tax_line.tax_line_id = tax_rel.account_tax_id
                JOIN res_currency curr ON
                    curr.id = tax_line.currency_id
                JOIN res_currency comp_curr ON
                    comp_curr.id = tax_line.company_currency_id
                JOIN account_move_line base_line ON
                    base_line.id = base_tax_line_mapping.base_line_id
                WHERE %(search_condition)s
                /* the downstream tax line has to be one the mapping already paired with this
                   base line. Nothing is read from that row, only its existence -- spelled as
                   EXISTS rather than a join so PostgreSQL may plan it as a semi-join; joining
                   the CTE a second time makes it materialise the pairs and nest-loop them. */
                AND EXISTS (
                    SELECT 1
                    FROM base_tax_line_mapping tax_line_matching
                    WHERE tax_line_matching.tax_line_id = tax_line.id
                      AND tax_line_matching.base_line_id = base_tax_line_mapping.base_line_id
                )
            ),


            base_tax_matching_base_amounts AS (

                /*
                Build here the full mapping tax lines <=> base lines containing the final base amounts.
                This is done in a 3-parts union.

                Note: src_line_id is used only to build a unique ID.
                */

                /*
                PART 1: raw mapping computed in base_tax_line_mapping.
                */

                SELECT
                    tax_line_id,
                    base_line_id,
                    base_line_id AS src_line_id,
                    base_amount,
                    base_amount_currency,
                    FALSE AS is_fallback
                FROM base_tax_line_mapping

                UNION ALL

                /*
                PART 2: Dispatch the tax amount of tax lines affecting the base of subsequent ones, using
                tax_amount_affecting_base_to_dispatch.

                This will effectively add the following rows:
                base_line_id    tax_line_id     src_line_id     base_amount
                -------------------------------------------------------------
                base_line_1     tax_line_2      tax_line_1      100
                base_line_2     tax_line_4      tax_line_3      200
                base_line_3     tax_line_4      tax_line_3      300
                */

                SELECT
                    sub.tax_line_id,
                    sub.base_line_id,
                    sub.src_line_id,
                    %(dispatched_base_amount)s AS base_amount,
                    %(dispatched_base_amount_currency)s AS base_amount_currency,
                    FALSE AS is_fallback
                FROM tax_amount_affecting_base_to_dispatch sub

                /*
                PART 3: In case of the matching failed because the configuration changed or some journal entries
                have been imported, construct a simple mapping as a fallback. The pairs themselves are built from
                'tax_ids' and 'tax_line_id' alone, so they are an approximation rather than an exact mapping; which
                of them to emit is decided against base_tax_line_mapping, per (tax line, base line) rather than per
                tax line, so a tax line that matched only some of its base lines still gets the rest approximated.
                Every row from here carries is_fallback = TRUE.

                Skipped if the 'fallback' method parameter is False.
                */
                %(fallback_query)s
            ),


            base_tax_matching_all_amounts AS (

                /*
                Complete base_tax_matching_base_amounts with the tax amounts (prorata):
                base_line_id    tax_line_id     src_line_id     base_amount     tax_amount
                --------------------------------------------------------------------------
                base_line_1     tax_line_1      base_line_1     1000            100
                base_line_1     tax_line_2      base_line_1     1000            (1000 / 1100) * 220 = 200
                base_line_1     tax_line_2      tax_line_1      100             (100 / 1100) * 220 = 20
                base_line_2     tax_line_3      base_line_2     2000            (2000 / 5000) * 500 = 200
                base_line_2     tax_line_4      base_line_2     2000            (2000 / 5500) * 275 = 100
                base_line_2     tax_line_4      tax_line_3      200             (200 / 5500) * 275 = 10
                base_line_3     tax_line_3      base_line_3     3000            (3000 / 5000) * 500 = 300
                base_line_3     tax_line_4      base_line_3     3000            (3000 / 5500) * 275 = 150
                base_line_3     tax_line_4      tax_line_3      300             (300 / 5500) * 275 = 15
                */

                SELECT
                    sub.tax_line_id,
                    sub.base_line_id,
                    sub.src_line_id,
                    sub.is_fallback,

                    tax_line.tax_line_id AS tax_id,
                    tax_line.group_tax_id,
                    tax_line.tax_repartition_line_id,

                    tax_line.company_id,
                    tax_line.display_type,
                    comp_curr.id AS company_currency_id,
                    comp_curr.decimal_places AS comp_curr_prec,
                    curr.id AS currency_id,
                    curr.decimal_places AS curr_prec,
                    (
                        tax.tax_exigibility != 'on_payment'
                        OR tax_move.tax_cash_basis_rec_id IS NOT NULL
                        OR tax_move.always_tax_exigible
                    ) AS tax_exigible,
                    base_line.account_id AS base_account_id,

                    sub.base_amount,
                    %(company_base_window_final)s,
                    tax_line.balance AS total_tax_amount,

                    sub.base_amount_currency,
                    %(foreign_base_window_final)s,
                    tax_line.amount_currency AS total_tax_amount_currency

                FROM base_tax_matching_base_amounts sub
                JOIN account_move_line tax_line ON
                    tax_line.id = sub.tax_line_id
                JOIN account_move tax_move ON
                    tax_move.id = tax_line.move_id
                JOIN account_move_line base_line ON
                    base_line.id = sub.base_line_id
                JOIN account_tax tax ON
                    tax.id = tax_line.tax_line_id
                JOIN res_currency curr ON
                    curr.id = tax_line.currency_id
                JOIN res_currency comp_curr ON
                    comp_curr.id = tax_line.company_currency_id

            )


           /* Final select that makes sure to deal with rounding errors, using LAG to dispatch the last cents. */

            SELECT
                sub.tax_line_id || '-' || sub.base_line_id || '-' || sub.src_line_id AS id,

                sub.base_line_id,
                sub.tax_line_id,
                sub.display_type,
                sub.src_line_id,
                sub.is_fallback,

                sub.tax_id,
                sub.group_tax_id,
                sub.tax_exigible,
                sub.base_account_id,
                sub.tax_repartition_line_id,

                sub.base_amount,
                COALESCE(%(final_tax_amount)s, 0.0) AS tax_amount,

                sub.base_amount_currency,
                COALESCE(%(final_tax_amount_currency)s, 0.0) AS tax_amount_currency
            FROM base_tax_matching_all_amounts sub
            """,
            extra_conditions=SQL("").join(
                SQL(" AND %s", condition)
                for condition in self._get_base_tax_line_mapping_conditions()
            ),
            search_condition=search_condition,
            table_references=table_references,
            fallback_query=fallback_query,
            fallback_lookups=fallback_lookups,
            tax_line_tax_ids=_sql_affecting_base_tax_ids(
                SQL("tax_line_tax_ids"), SQL("account_move_line.id")
            ),
            base_line_tax_ids=_sql_affecting_base_tax_ids(
                SQL("base_line_tax_ids"), SQL("base_line.id")
            ),
            company_base_window=_sql_taxable_base_window(
                SQL("base_line.balance"),
                SQL("base_line.balance"),
                SQL(""),
                dispatch_window_partition,
                dispatch_window_order,
            ),
            foreign_base_window=_sql_taxable_base_window(
                SQL("base_line.amount_currency"),
                SQL("base_line.amount_currency"),
                SQL("_currency"),
                dispatch_window_partition,
                dispatch_window_order,
            ),
            dispatched_base_amount=_sql_dispatched_amount(
                _sql_prorata_share(
                    SQL("sub.cumulated_base_amount"),
                    SQL("sub.total_base_amount"),
                    SQL("sub.total_tax_amount"),
                    SQL("sub.comp_curr_prec"),
                ),
                dispatch_partition,
                dispatch_order,
            ),
            dispatched_base_amount_currency=_sql_dispatched_amount(
                _sql_prorata_share(
                    SQL("sub.cumulated_base_amount_currency"),
                    SQL("sub.total_base_amount_currency"),
                    SQL("sub.total_tax_amount_currency"),
                    SQL("sub.curr_prec"),
                ),
                dispatch_partition,
                dispatch_order,
            ),
            company_base_window_final=_sql_taxable_base_window(
                SQL("base_line.balance"),
                SQL("sub.base_amount"),
                SQL(""),
                final_window_partition,
                final_window_order,
            ),
            foreign_base_window_final=_sql_taxable_base_window(
                SQL("base_line.amount_currency"),
                SQL("sub.base_amount_currency"),
                SQL("_currency"),
                final_window_partition,
                final_window_order,
            ),
            final_tax_amount=_sql_dispatched_amount(
                _sql_prorata_share(
                    SQL("sub.cumulated_base_amount"),
                    SQL("sub.total_base_amount"),
                    SQL("sub.total_tax_amount"),
                    SQL("sub.comp_curr_prec"),
                ),
                final_partition,
                final_order,
            ),
            final_tax_amount_currency=_sql_dispatched_amount(
                _sql_prorata_share(
                    SQL("sub.cumulated_base_amount_currency"),
                    SQL("sub.total_base_amount_currency"),
                    SQL("sub.total_tax_amount_currency"),
                    SQL("sub.curr_prec"),
                ),
                final_partition,
                final_order,
            ),
        )
