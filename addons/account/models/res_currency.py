from dataclasses import dataclass

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL, date_utils

# Column layout of the currency table, declared once so every builder and the
# CREATE TEMPORARY TABLE statement stay in lock-step. Changing the schema is a
# single edit here instead of five parallel edits across the SQL fragments.
CURRENCY_TABLE_COLUMNS = (
    "company_id",
    "period_key",
    "date_from",
    "date_next",
    "rate_type",
    "rate",
)

# Rate types materialised in the currency table. Simple single-period
# conversions only need 'current'; CTA reports additionally need 'historical'
# and 'average' rates for the equity/P&L translation rules.
SIMPLE_RATE_TYPES = ("current",)
CTA_RATE_TYPES = ("current", "historical", "average")


@dataclass(frozen=True, slots=True)
class CurrencyTableScope:
    """Immutable bundle of parameters shared by every per-period currency-table builder."""

    # main_company_id is the root company that owns the ``res.currency.rate``
    # records; other_company_ids is the guaranteed non-empty set of companies
    # whose amounts must be converted. Bundling them keeps each builder's
    # signature small and makes it impossible for one builder to be handed a
    # different company set than another within the same table build.
    main_company_id: int
    other_company_ids: tuple


class ResCurrency(models.Model):
    _inherit = "res.currency"

    def _get_fiscal_country_codes(self):
        return ",".join(self.env.companies.mapped("account_fiscal_country_id.code"))

    display_rounding_warning = fields.Boolean(
        string="Display Rounding Warning",
        compute="_compute_display_rounding_warning",
        help="The warning informs a rounding factor change might be dangerous on res.currency's form view.",
    )
    fiscal_country_codes = fields.Char(store=False, default=_get_fiscal_country_codes)

    @api.depends("rounding")
    def _compute_display_rounding_warning(self):
        for record in self:
            record.display_rounding_warning = bool(record._origin) and (
                record._origin.rounding != record.rounding
            )

    def write(self, vals):
        if "rounding" in vals:
            # The risk being guarded against is *losing* decimal places on a
            # currency already used in the ledger — not any change to the raw
            # rounding factor. Those are not equivalent: decimal_places is
            # ceil(log10(1/rounding)), so e.g. 0.01 -> 0.05 keeps 2 places and
            # must stay allowed. Compare the derived place count, not the factor.
            new_decimal_places = self._decimal_places_for_rounding(vals["rounding"])
            for record in self:
                if (
                    new_decimal_places < record.decimal_places
                    and record._has_accounting_entries()
                ):
                    raise UserError(
                        _(
                            "You cannot reduce the number of decimal places of a currency which has already been used to make accounting entries."
                        )
                    )

        return super().write(vals)

    def _decimal_places_for_rounding(self, rounding):
        """Return the number of decimal places a given ``rounding`` factor implies, without writing it."""
        # Delegate to _compute_decimal_places via an in-memory record so the
        # log10 formula lives in exactly one place (base).
        return self.new({"rounding": rounding}).decimal_places

    def _has_accounting_entries(self):
        """Returns True iff this currency has been used to generate (hence, round)
        some move lines (either as their foreign currency, or as the main currency).
        """
        self.ensure_one()
        # limit=1: this is an existence check, not a tally — stop at the first hit
        # instead of counting every matching move line on the whole ledger.
        return bool(
            self.env["account.move.line"]
            .sudo()
            .search_count(
                [
                    "|",
                    ("currency_id", "=", self.id),
                    ("company_currency_id", "=", self.id),
                ],
                limit=1,
            )
        )

    def _get_simple_currency_table(self, companies) -> SQL:
        """Create the currency table and return its definition for the simple case:
        reports converting amounts with only the current rates, in a single period.
        """
        if self._check_currency_table_monocurrency(companies):
            return self._get_monocurrency_currency_table_sql(companies)

        self._create_currency_table(
            companies, [("period", None, fields.Date.context_today(self))]
        )
        return SQL("account_currency_table")

    def _check_currency_table_monocurrency(self, companies):
        """Return whether the provided companies' data can be displayed with a monocurrency currency table."""
        # If so, _get_monocurrency_currency_table_sql suffices to join the currency table (a bunch of
        # VALUES injected directly in the join). Otherwise a full temporary table is needed, built by
        # _create_currency_table.
        return len(companies.currency_id) == 1

    def _currency_table_rate_types(self, use_cta_rates):
        """Rate types to materialise: the CTA set (current/historical/average) when
        CTA translation is requested, otherwise just the current rate.
        """
        return CTA_RATE_TYPES if use_cta_rates else SIMPLE_RATE_TYPES

    def _currency_table_unit_rows(self, companies, use_cta_rates) -> list[SQL]:
        """VALUES rows setting every requested rate to 1 for the given companies."""
        # Shared by the monocurrency shortcut and by the "domestic" builder (companies
        # sharing the main company's currency): in both cases no conversion is needed,
        # so the query shape is identical to the multi-currency case with rate = 1.
        return [
            SQL(
                "(%(company_id)s, CAST(NULL AS VARCHAR), CAST(NULL AS DATE), CAST(NULL AS DATE), %(rate_type)s, 1)",
                company_id=company.id,
                rate_type=rate_type,
            )
            for company in companies
            for rate_type in self._currency_table_rate_types(use_cta_rates)
        ]

    def _get_monocurrency_currency_table_sql(self, companies, use_cta_rates=False):
        """Return a simplified currency table (a few VALUES, no temporary table) for data expressed in a single currency, to be used in a JOIN."""
        # Every rate is 1 (everything is in the same currency). Keeping the same query shape as the
        # multi-currency case lets callers join the returned table identically for both cases.
        return SQL(
            "(VALUES %(rows)s) AS account_currency_table(%(columns)s)",
            rows=SQL(", ").join(
                self._currency_table_unit_rows(companies, use_cta_rates)
            ),
            columns=SQL(", ").join(
                SQL.identifier(col) for col in CURRENCY_TABLE_COLUMNS
            ),
        )

    def _create_currency_table(self, companies, date_periods, use_cta_rates=False):
        """Create a temporary table of currency rates for aggregating amounts of companies with different main currencies in a reporting query.

        :param companies: The res.company objects to generate rates for.
        :param date_periods: List of tuples in the form (period_key, date_from, date_to), containing each of the periods to generate rates for, where:
                             - period_key is a unique string identifier used to differentiate the periods
                             - date_from is the date the period starts at ; it can be None if the period want to consider everything from the beginning
                             - date_to is the date the periods ends at
        :param use_cta_rates: Boolean parameter, enabling the computation of CTA rates. If True, 'current', 'average' and 'historical' rates will be
                        computed for all companies, for all periods. Else, only 'current' will be computed.
        """
        # These rates are computed from the res.currency.rate objects defined for self.env.company.
        # The currency table consists of the following columns:
        #   - company_id: The id of the company whose amounts can be converted with this rate.
        #   - period_key: The key corresponding to the period this rate is valid for. (see date_periods)
        #   - date_from: Only set for rate_type 'historical'. The starting date for this rate.
        #   - date_next: Only set for rate_type 'historical'. The date of the next rate. So, the rate applies until one day before date_next.
        #   - rate_type: 'historical', 'current' or 'average'
        #       - 'historical' means the rate is to be used to convert operations at the date they were made; they each
        #          directly correspond to the res.currency.rate objects of the active company
        #       - 'current' means this rate is the most recent rate within the period. This rate is unique per (company_id, period_key).
        #       - 'average' means this rate is the average rate for the period. This rate is unique per (company_id, period_key).
        #   - rate: The rate to apply, as a decimal factor to apply directly to the value to convert, provided it is expressed in the
        #           main currency of the company referred to by company_id.
        main_company = self.env.company
        domestic_currency_companies = companies.filtered(
            lambda x: x.currency_id == main_company.currency_id
        )
        other_companies = companies - domestic_currency_companies

        table_builders = []
        if domestic_currency_companies:
            table_builders.append(
                self._get_table_builder_domestic_currency(
                    domestic_currency_companies, use_cta_rates
                )
            )

        # The per-period builders only concern companies whose currency differs
        # from the main one. When there are none, skipping them is not merely an
        # optimisation: their `WHERE company_id IN %s` would render an empty
        # `IN ()` and raise a SQL syntax error. Domestic companies already get a
        # period-agnostic rate of 1 from the builder above.
        if other_companies:
            scope = CurrencyTableScope(
                main_company_id=main_company.root_id.id,
                other_company_ids=tuple(other_companies.ids),
            )
            last_date_to = None
            for period_key, date_from, date_to in date_periods:
                main_company_unit_factor = main_company.currency_id._get_rates(
                    main_company, date_to
                )[main_company.currency_id.id]

                table_builders.append(
                    self._get_table_builder_current(
                        scope, period_key, date_to, main_company_unit_factor
                    )
                )

                if use_cta_rates:
                    table_builders += [
                        self._get_table_builder_historical(
                            scope, date_to, main_company_unit_factor, last_date_to
                        ),
                        self._get_table_builder_average(
                            scope,
                            period_key,
                            date_from,
                            date_to,
                            main_company_unit_factor,
                        ),
                    ]

                last_date_to = date_to

        currency_table_build_query = SQL(" UNION ALL ").join(
            SQL("(%s)", builder) for builder in table_builders
        )
        cr = self.env.cr
        cr.execute(SQL("DROP TABLE IF EXISTS account_currency_table"))
        cr.execute(
            SQL(
                """CREATE TEMPORARY TABLE
                account_currency_table (%(columns)s)
                ON COMMIT DROP
                AS (%(query)s)""",
                columns=SQL(", ").join(
                    SQL.identifier(col) for col in CURRENCY_TABLE_COLUMNS
                ),
                query=currency_table_build_query,
            )
        )
        cr.execute(
            SQL(
                "CREATE INDEX account_currency_table_index ON account_currency_table (company_id, rate_type, date_from, date_next)"
            )
        )
        cr.execute(SQL("ANALYZE account_currency_table"))

    def _get_table_builder_domestic_currency(self, companies, use_cta_rates) -> SQL:
        """Returns a query building one rate of each appropriate type equal to 1 for each of the provided companies. Those companies should be
        the ones sharing the same currency as self.env.company.
        """
        return SQL(
            "SELECT * FROM (VALUES %(rows)s) AS domestic_rates",
            rows=SQL(", ").join(
                self._currency_table_unit_rows(companies, use_cta_rates)
            ),
        )

    def _get_table_builder_current(
        self,
        scope: CurrencyTableScope,
        period_key,
        date_to,
        main_company_unit_factor,
    ) -> SQL:
        return SQL(
            """
                SELECT DISTINCT ON (other_company.id)
                    other_company.id,
                    %(period_key)s,
                    CAST(NULL AS DATE),
                    CAST(NULL AS DATE),
                    'current',
                    CASE WHEN rate.id IS NOT NULL THEN %(main_company_unit_factor)s / rate.rate ELSE 1 END
                FROM res_company other_company
                LEFT JOIN res_currency_rate rate
                    ON rate.currency_id = other_company.currency_id
                    AND rate.name <= %(date_to)s
                    AND rate.company_id = %(main_company_id)s
                WHERE
                    other_company.id IN %(other_company_ids)s
                ORDER BY other_company.id, rate.name DESC
            """,
            # NB: when a company's currency has no rate on or before date_to the
            # LEFT JOIN yields NULL and the rate defaults to 1 (parity). This
            # intentionally differs from res.currency._get_rates, which falls back
            # to the *earliest* known rate. Neither is objectively correct (there
            # is simply no rate for that date); keep them aligned only via a
            # deliberate, test-backed change — reports depend on this behaviour.
            period_key=period_key,
            main_company_id=scope.main_company_id,
            other_company_ids=scope.other_company_ids,
            date_to=date_to,
            main_company_unit_factor=main_company_unit_factor,
        )

    def _get_table_builder_historical(
        self,
        scope: CurrencyTableScope,
        date_to,
        main_company_unit_factor,
        date_exclude,
    ) -> SQL:
        return SQL(
            """
                SELECT
                    other_company.id,
                    CAST(NULL AS VARCHAR),
                    rate.name,
                    LAG(rate.name, 1) OVER (PARTITION BY other_company.id, rate.currency_id ORDER BY rate.name DESC),
                    'historical',
                    %(main_company_unit_factor)s / rate.rate
                FROM res_company other_company
                JOIN res_currency_rate rate
                    ON rate.currency_id = other_company.currency_id
                WHERE
                    other_company.id IN %(other_company_ids)s
                    AND rate.company_id = %(main_company_id)s
                    AND rate.name <= %(date_to)s
                    %(exclusion_condition)s
            """,
            main_company_id=scope.main_company_id,
            other_company_ids=scope.other_company_ids,
            main_company_unit_factor=main_company_unit_factor,
            date_to=date_to,
            exclusion_condition=SQL(
                "AND rate.name > %(date_exclude)s", date_exclude=date_exclude
            )
            if date_exclude
            else SQL(),
        )

    def _get_table_builder_average(
        self,
        scope: CurrencyTableScope,
        period_key,
        date_from,
        date_to,
        main_company_unit_factor,
    ) -> SQL:
        if not date_from:
            # When there is no start date, we want to compute the average rate on the current year only
            date_from = date_utils.start_of(fields.Date.from_string(date_to), "year")

        return SQL(
            """
                SELECT
                    rate_with_days.other_company_id,
                    %(period_key)s,
                    CAST(NULL AS DATE),
                    CAST(NULL AS DATE),
                    'average',
                    SUM(%(main_company_unit_factor)s / rate_with_days.rate * rate_with_days.number_of_days) / SUM(rate_with_days.number_of_days)
                FROM (
                    SELECT
                        other_company.id as other_company_id,
                        rate.rate AS rate,
                        EXTRACT (
                            'Day' FROM COALESCE(
                                LEAD(rate.name, 1) OVER (PARTITION BY other_company.id, rate.currency_id ORDER BY rate.name ASC)::TIMESTAMP,
                                %(date_to)s::TIMESTAMP + INTERVAL '1' DAY
                            ) - rate.name::TIMESTAMP
                        ) AS number_of_days
                    FROM res_company other_company
                    JOIN res_currency_rate rate
                        ON rate.currency_id = other_company.currency_id
                    WHERE
                    rate.name <= %(date_to)s
                    AND rate.name >= %(date_from)s
                    AND other_company.id IN %(other_company_ids)s
                    AND rate.company_id = %(main_company_id)s

                    UNION ALL

                    (
                        SELECT DISTINCT ON (other_company.id)
                            other_company.id as other_company_id,
                            COALESCE(out_period_rate.rate, 1.0) AS rate,
                            EXTRACT('Day' FROM COALESCE(in_period_rate.name::TIMESTAMP, %(date_to)s::TIMESTAMP + INTERVAL '1' DAY) - %(date_from)s::TIMESTAMP) AS number_of_days

                        FROM res_company other_company

                        LEFT JOIN res_currency_rate in_period_rate
                            ON in_period_rate.currency_id = other_company.currency_id
                            AND in_period_rate.name <= %(date_to)s
                            AND in_period_rate.name >= %(date_from)s
                            AND in_period_rate.company_id = %(main_company_id)s

                        LEFT JOIN res_currency_rate out_period_rate
                            ON out_period_rate.currency_id = other_company.currency_id
                            AND out_period_rate.company_id = %(main_company_id)s
                            AND out_period_rate.name < %(date_from)s

                        WHERE
                        other_company.id IN %(other_company_ids)s
                        ORDER BY other_company.id, in_period_rate.name ASC, out_period_rate.name DESC
                    )
                ) rate_with_days
                GROUP BY rate_with_days.other_company_id
            """,
            period_key=period_key,
            main_company_id=scope.main_company_id,
            other_company_ids=scope.other_company_ids,
            date_from=date_from,
            date_to=date_to,
            main_company_unit_factor=main_company_unit_factor,
        )
