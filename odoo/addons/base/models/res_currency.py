import logging
import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Self

from num2words import num2words

if TYPE_CHECKING:
    from lxml import etree

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL, ormcache, parse_date

_logger = logging.getLogger(__name__)

# Total digits in the Float ``digits`` tuple. 69 is the IEEE 754 double upper
# bound — effectively no limit on integer digits.
_CURRENCY_TOTAL_DIGITS = 69

# RCUR-M1: ``env.cr.cache`` key of the transaction-scoped rate-history memo::
#
#     {(currency_id, company_root_id):
#         ((specific_dates, specific_values), (global_dates, global_values))}
#
# Populated by ``_get_rates_from_memo``, dropped by
# ``ResCurrencyRate.create/write/unlink``. ``cr.cache`` is transaction-local
# (cleared on rollback/reset), so cross-transaction staleness cannot occur.
RATE_HISTORY_CACHE_KEY = "res_currency_rate_history"


class ResCurrency(models.Model):
    _name = "res.currency"
    _description = "Currency"
    _rec_names_search = ["name", "full_name"]
    _order = "active desc, name"

    # 'code' column was removed in v6.0; 'name' now holds the ISO code.
    name = fields.Char(
        string="Currency",
        size=3,
        required=True,
        help="Currency Code (ISO 4217)",
    )
    iso_numeric = fields.Integer(
        string="Currency numeric code.",
        help="Currency Numeric Code (ISO 4217).",
    )
    full_name = fields.Char(string="Name")
    symbol = fields.Char(
        help="Currency sign, to be used when printing amounts.", required=True
    )
    rate = fields.Float(
        compute="_compute_current_rate",
        string="Current Rate",
        digits=0,
        help="The rate of the currency to the currency of rate 1.",
    )
    inverse_rate = fields.Float(
        compute="_compute_current_rate",
        digits=0,
        readonly=True,
        help="The currency of rate 1 to the rate of the currency.",
    )
    rate_string = fields.Char(compute="_compute_current_rate")
    rate_ids = fields.One2many("res.currency.rate", "currency_id", string="Rates")
    rounding = fields.Float(
        string="Rounding Factor",
        digits=(12, 6),
        default=0.01,
        help="Amounts in this currency are rounded off to the nearest multiple of the rounding factor.",
    )
    decimal_places = fields.Integer(
        compute="_compute_decimal_places",
        store=True,
        help="Decimal places taken into account for operations on amounts in this currency. It is determined by the rounding factor.",
    )
    active = fields.Boolean(default=True)
    position = fields.Selection(
        [("after", "After Amount"), ("before", "Before Amount")],
        default="after",
        string="Symbol Position",
        help="Determines where the currency symbol should be placed after or before the amount.",
    )
    date = fields.Date(compute="_compute_date")
    currency_unit_label = fields.Char(string="Currency Unit", translate=True)
    currency_subunit_label = fields.Char(string="Currency Subunit", translate=True)
    is_current_company_currency = fields.Boolean(
        compute="_compute_is_current_company_currency"
    )

    _unique_name = models.Constraint(
        "unique (name)",
        "The currency code must be unique!",
    )
    _rounding_gt_zero = models.Constraint(
        "CHECK (rounding>0)",
        "The rounding factor must be greater than 0!",
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        self._toggle_group_multi_currency()
        # invalidate cache for get_all_currencies
        self.env.registry.clear_cache("stable")
        return res

    def unlink(self) -> bool:
        res = super().unlink()
        self._toggle_group_multi_currency()
        # invalidate cache for get_all_currencies
        self.env.registry.clear_cache("stable")
        return res

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if vals.keys() & {"active", "name", "position", "symbol", "rounding"}:
            # invalidate cache for get_all_currencies
            self.env.registry.clear_cache("stable")
        if "active" not in vals:
            return res
        self._toggle_group_multi_currency()
        return res

    @api.model
    def _toggle_group_multi_currency(self) -> None:
        """Activate group_multi_currency when >1 active currency, deactivate otherwise."""
        active_currency_count = self.search_count([("active", "=", True)])
        if active_currency_count > 1:
            self._activate_group_multi_currency()
        else:
            self._deactivate_group_multi_currency()

    @api.model
    def _activate_group_multi_currency(self) -> None:
        group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        group_mc = self.env.ref("base.group_multi_currency", raise_if_not_found=False)
        if group_user and group_mc:
            group_user.sudo()._apply_group(group_mc)

    @api.model
    def _deactivate_group_multi_currency(self) -> None:
        group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        group_mc = self.env.ref("base.group_multi_currency", raise_if_not_found=False)
        if group_user and group_mc:
            group_user.sudo()._remove_group(group_mc.sudo())

    @api.constrains("active")
    def _check_company_currency_stays_active(self) -> None:
        if self.env.context.get("install_mode") or self.env.context.get(
            "force_deactivate"
        ):
            # install_mode: at install the "active" field of a currency added to a
            #   company still evaluates False despite being auto-set True on add.
            # force_deactivate: allows deactivating a currency in tests for
            #   non-multi-currency behaviours.
            return

        currencies = self.filtered(lambda c: not c.active)
        if self.env["res.company"].search_count(
            [("currency_id", "in", currencies.ids)], limit=1
        ):
            raise UserError(
                self.env._(
                    "This currency is set on a company and therefore cannot be deactivated."
                )
            )

    def _get_rates(self, company: Self, date: Any) -> dict[int, float]:
        """Return ``{currency_id: rate}`` for ``self`` at ``date`` for ``company``.

        Per currency, selects the latest rate with ``name <= date`` scoped to the
        company root or global (``company_id`` NULL); falls back to the earliest
        known rate, then to ``1.0`` when the currency has no rate at all.
        """
        if not self.ids:
            return {}
        # RCUR-M1: first lookup per (currency, company root) loads the full rate
        # history into the memo; later dates resolve by bisect, so batch flows
        # with per-line dates avoid one SQL query per (date, company, currency).
        rates = self._get_rates_from_memo(company, date)
        if rates is not None:
            return rates
        return self._get_rates_sql(company, date)

    def _get_rates_sql(self, company: Self, date: Any) -> dict[int, float]:
        """SQL cold path of :meth:`_get_rates` (memoization bypassed).

        Same contract as :meth:`_get_rates`; kept as the reference
        implementation whose semantics :meth:`_get_rates_from_memo` must
        reproduce exactly (a test asserts their parity).
        """
        if not self.ids:
            return {}
        currency_query = self._as_query(ordered=False)
        currency_id = self.env["res.currency"]._field_to_sql(currency_query.table, "id")
        Rate = self.env["res.currency.rate"]
        rate_query = Rate._search(
            [
                ("name", "<=", date),
                ("company_id", "in", (False, company.root_id.id)),
            ],
            order="company_id.id, name DESC",
            limit=1,
        )
        rate_query.add_where(
            SQL(
                "%s = %s",
                Rate._field_to_sql(rate_query.table, "currency_id"),
                currency_id,
            )
        )
        # RCUR-L1: fallback for dates before the currency's first recorded rate.
        # 'name ASC' is deliberate — it returns the *earliest* known rate,
        # asymmetric with the primary 'name DESC' selection, not a bug.
        rate_fallback = Rate._search(
            [
                ("company_id", "in", (False, company.root_id.id)),
            ],
            order="company_id.id, name ASC",
            limit=1,
        )
        rate_fallback.add_where(
            SQL(
                "%s = %s",
                Rate._field_to_sql(rate_fallback.table, "currency_id"),
                currency_id,
            )
        )
        rate = Rate._field_to_sql(rate_query.table, "rate")
        return dict(
            self.env.execute_query(
                currency_query.select(
                    currency_id,
                    SQL(
                        "COALESCE((%s), (%s), 1.0)",
                        rate_query.select(rate),
                        rate_fallback.select(rate),
                    ),
                )
            )
        )

    def _get_rates_from_memo(self, company: Self, date: Any) -> dict[int, float] | None:
        """Memoized equivalent of :meth:`_get_rates_sql` (RCUR-M1).

        The first call per (currency, company root) loads the currency's full
        rate history (company-root and global ``company_id IS NULL`` scopes)
        into the memo; later dates resolve in memory via
        :meth:`_resolve_rate_from_history`.

        :return: same mapping as :meth:`_get_rates`, or ``None`` when ``date``
                 cannot be normalized (caller then uses the SQL cold path).
        """
        try:
            date = fields.Date.to_date(date)
        except ValueError, TypeError:
            return None
        if not date:
            return None
        root_id = company.root_id.id
        memo = self.env.cr.cache.setdefault(RATE_HISTORY_CACHE_KEY, {})
        missing = {
            currency_id
            for currency_id in self.ids
            if (currency_id, root_id) not in memo
        }
        if missing:
            histories = {currency_id: (([], []), ([], [])) for currency_id in missing}
            rates = self.env["res.currency.rate"].search_fetch(
                [
                    ("currency_id", "in", tuple(missing)),
                    ("company_id", "in", (False, root_id)),
                ],
                ["currency_id", "company_id", "name", "rate"],
                order="name, id",
            )
            for rate in rates:
                specific, global_ = histories[rate.currency_id.id]
                dates, values = specific if rate.company_id else global_
                dates.append(rate.name)
                # CHECK (rate > 0) forbids 0.0, so a falsy value is SQL NULL,
                # which the COALESCE chain skips — keep None so
                # _resolve_rate_from_history matches.
                values.append(rate.rate or None)
            for currency_id, history in histories.items():
                memo[currency_id, root_id] = history
        return {
            currency_id: self._resolve_rate_from_history(
                memo[currency_id, root_id], date
            )
            for currency_id in self.ids
        }

    @staticmethod
    def _resolve_rate_from_history(history: tuple, date: Any) -> float:
        """Replicate ``COALESCE((primary), (fallback), 1.0)`` of
        :meth:`_get_rates_sql` on an in-memory rate history.

        Primary: latest rate dated on or before ``date``; the company-root
        scope takes precedence over the global one whenever it has any such
        rate (the SQL orders by ``company_id ASC NULLS LAST, name DESC``).
        Fallback (RCUR-L1): when no rate is dated on or before ``date`` — or
        the selected row has a NULL value — use the *earliest* known rate,
        with the same scope precedence; ``1.0`` when there is none at all.
        """
        (specific_dates, specific_values), (global_dates, global_values) = history
        value = None
        if index := bisect_right(specific_dates, date):
            value = specific_values[index - 1]
        elif index := bisect_right(global_dates, date):
            value = global_values[index - 1]
        if value is None:
            # RCUR-L1 asymmetric fallback: earliest known rate; may itself be
            # a NULL-valued row (then the final 1.0 identity applies).
            if specific_values:
                value = specific_values[0]
            elif global_values:
                value = global_values[0]
        return 1.0 if value is None else value

    @api.depends_context("company")
    def _compute_is_current_company_currency(self) -> None:
        company_currency = self.env.company.currency_id
        for currency in self:
            currency.is_current_company_currency = company_currency == currency

    # RCUR-C1: selection depends on the rate's date ('name') and company scope,
    # not only its value — declaring all three keeps the owning currency's
    # cached rate/inverse_rate/rate_string consistent. It does not replace the
    # invalidate_model() calls in ResCurrencyRate: another currency's cached
    # values can depend on this one's rates (via 'to_currency' or as the company
    # currency), a cross-record dependency @api.depends cannot express.
    @api.depends("rate_ids.rate", "rate_ids.name", "rate_ids.company_id")
    @api.depends_context("to_currency", "date", "company", "company_id")
    def _compute_current_rate(self) -> None:
        """Compute ``rate``/``inverse_rate``/``rate_string`` from context.

        ``date``, ``company_id`` and ``to_currency`` are read from the context;
        ``rate`` is units of this currency per 1 unit of ``to_currency`` and
        ``inverse_rate`` its reciprocal (``0.0`` when ``rate`` is falsy).
        """
        date = self.env.context.get("date") or fields.Date.context_today(self)
        company = (
            self.env["res.company"].browse(self.env.context.get("company_id"))
            or self.env.company
        )
        company_currency = company.currency_id
        to_currency = (
            self.browse(self.env.context.get("to_currency")) or company_currency
        )
        currency_rates = (self + to_currency)._get_rates(company, date)
        to_rate = currency_rates.get(to_currency.id) or 1.0
        to_name = to_currency.name
        for currency in self:
            rate = (currency_rates.get(currency.id) or 1.0) / to_rate
            currency.rate = rate
            currency.inverse_rate = 1 / rate if rate else 0.0
            if currency != company_currency:
                currency.rate_string = f"1 {to_name} = {rate:.6f} {currency.name}"
            else:
                currency.rate_string = ""

    @api.depends("rounding")
    def _compute_decimal_places(self) -> None:
        """Derive ``decimal_places`` from the ``rounding`` factor."""
        for currency in self:
            if 0 < currency.rounding < 1:
                currency.decimal_places = math.ceil(math.log10(1 / currency.rounding))
            else:
                currency.decimal_places = 0

    @api.depends("rate_ids.name")
    def _compute_date(self) -> None:
        """Set ``date`` to the most recent rate's date."""
        for currency in self:
            currency.date = currency.rate_ids[:1].name

    def amount_to_text(self, amount: float) -> str:
        self.ensure_one()

        def _num2words(number, lang):
            try:
                return num2words(number, lang=lang).title()
            except NotImplementedError:
                _logger.warning(
                    "The library 'num2words' does not support language %r; "
                    "falling back to English words.",
                    lang,
                )
                return num2words(number, lang="en").title()

        integral, _sep, fractional = f"{amount:.{self.decimal_places}f}".partition(".")
        integer_value = int(integral)
        lang = tools.get_lang(self.env)
        integral_text = _num2words(integer_value, lang=lang.iso_code)
        # For amounts in (-1, 0), int("-0") == 0 silently loses the sign.
        # num2words also drops "minus" for such values, so prepend manually.
        if amount < 0 and integer_value == 0:
            integral_text = self.env._("Minus %s", integral_text)
        if self.is_zero(amount - integer_value):
            return self.env._(
                "%(integral_amount)s %(currency_unit)s",
                integral_amount=integral_text,
                currency_unit=self.currency_unit_label,
            )
        else:
            return self.env._(
                "%(integral_amount)s %(currency_unit)s and %(fractional_amount)s %(currency_subunit)s",
                integral_amount=integral_text,
                currency_unit=self.currency_unit_label,
                fractional_amount=_num2words(int(fractional or 0), lang=lang.iso_code),
                currency_subunit=self.currency_subunit_label,
            )

    def format(self, amount: float) -> str:
        """Return ``amount`` formatted per ``self``'s rounding, symbol and position.

        Also removes the minus sign when 0.0 is negative.
        """
        self.ensure_one()
        return tools.format_amount(self.env, amount + 0.0, self)

    def round(self, amount: float) -> float:
        """Return ``amount`` rounded per ``self``'s rounding rules."""
        self.ensure_one()
        return tools.float_round(amount, precision_rounding=self.rounding)

    def compare_amounts(self, amount1: float, amount2: float) -> int:
        """Compare ``amount1`` and ``amount2`` after rounding each to the currency's
        precision; return -1, 0 or 1 (lower / equal / greater).

        Rounding happens before comparing, so this differs from a non-zero
        difference: 0.006 vs 0.002 compare as different (round to 0.01 vs 0.0) at
        2-digit precision even though their difference rounds to zero.
        """
        self.ensure_one()
        return tools.float_compare(amount1, amount2, precision_rounding=self.rounding)

    def is_zero(self, amount: float) -> bool:
        """Return True if ``amount`` rounds to zero at the currency's precision.

        Warning: ``is_zero(a - b)`` is not always ``compare_amounts(a, b) == 0`` —
        is_zero rounds after the subtraction, compare_amounts before (differing
        for e.g. 0.006 and 0.002 at 2-digit precision).
        """
        self.ensure_one()
        return tools.float_is_zero(amount, precision_rounding=self.rounding)

    @ormcache(cache="stable")
    @api.model
    def get_all_currencies(self) -> dict[int, dict[str, Any]]:
        currencies = self.sudo().search_fetch(
            [("active", "=", True)],
            ["name", "symbol", "position", "decimal_places"],
        )
        return {
            c.id: {
                "name": c.name,
                "symbol": c.symbol,
                "position": c.position,
                "digits": [_CURRENCY_TOTAL_DIGITS, c.decimal_places],
            }
            for c in currencies
        }

    @api.model
    def _get_conversion_rate(
        self,
        from_currency: Self,
        to_currency: Self,
        company: Any = None,
        date: Any = None,
    ) -> float:
        """Return the rate converting one unit of ``from_currency`` to ``to_currency``.

        ``company`` defaults to the env company, ``date`` to today; returns ``1``
        when both currencies are equal.
        """
        if from_currency == to_currency:
            return 1
        company = company or self.env.company
        date = date or fields.Date.context_today(self)
        return (
            from_currency.with_company(company)
            .with_context(to_currency=to_currency.id, date=str(date))
            .inverse_rate
        )

    def _convert(
        self,
        from_amount: float,
        to_currency: Self,
        company: Any = None,
        date: Any = None,
        round: bool = True,
    ) -> float:
        """Return ``from_amount`` converted from ``self`` to ``to_currency``.

        :param bool round: round the result to ``to_currency``'s precision
        """
        if from_amount is None:
            msg = "_convert() requires a numeric amount, got None"
            raise ValueError(msg)
        self, to_currency = self or to_currency, to_currency or self
        if not self:
            raise UserError(
                self.env._("Cannot convert amount: source currency is not set.")
            )
        if not to_currency:
            raise UserError(
                self.env._("Cannot convert amount: target currency is not set.")
            )
        # RCUR-L2: conversion is defined for a single source/target pair.
        self.ensure_one()
        to_currency.ensure_one()
        # Short-circuit on zero to avoid a needless rate lookup.
        if not from_amount:
            return 0.0
        to_amount = from_amount * self._get_conversion_rate(
            self, to_currency, company, date
        )
        return to_currency.round(to_amount) if round else to_amount

    def _select_companies_rates(self) -> str:
        """Return the SQL selecting each rate's validity window per company.

        Extension point with no caller in ``base``; overridden by ``account``.
        """
        return """
            SELECT
                r.currency_id,
                COALESCE(r.company_id, c.id) as company_id,
                r.rate,
                r.name AS date_start,
                (SELECT name FROM res_currency_rate r2
                 WHERE r2.name > r.name AND
                       r2.currency_id = r.currency_id AND
                       (r2.company_id is null or r2.company_id = c.id)
                 ORDER BY r2.name ASC
                 LIMIT 1) AS date_end
            FROM res_currency_rate r
            JOIN res_company c ON (r.company_id is null or r.company_id = c.id)
        """

    @api.model
    def _get_context_company_currency_name(self) -> str:
        """Return the currency name of the context company: ``company_id`` from
        the context when set, else the environment company.

        Shared by the ``_get_view``/``_get_view_cache_key`` overrides of both
        ``res.currency`` and ``res.currency.rate``.
        """
        return (
            self.env["res.company"].browse(self.env.context.get("company_id"))
            or self.env.company
        ).currency_id.name

    @api.model
    def _get_view_cache_key(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple:
        """View cache must depend on the company currency, since _get_view
        relabels the rate fields with it."""
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (self._get_context_company_currency_name(),)

    @api.model
    def _get_view(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple[etree._Element, Any]:
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type in ("list", "form"):
            currency_name = self._get_context_company_currency_name()
            fields_maps = [
                [
                    ["company_rate", "rate"],
                    self.env._("Unit per %s", currency_name),
                ],
                [
                    ["inverse_company_rate", "inverse_rate"],
                    self.env._("%s per Unit", currency_name),
                ],
            ]
            for fnames, label in fields_maps:
                xpath_expression = (
                    "//list//field["
                    + " or ".join(f"@name='{f}'" for f in fnames)
                    + "][1]"
                )
                node = arch.xpath(xpath_expression)
                if node:
                    node[0].set("string", label)
        return arch, view


class ResCurrencyRate(models.Model):
    _name = "res.currency.rate"
    _description = "Currency Rate"
    _rec_names_search = ["name", "rate"]
    _order = "name desc, id"
    _check_company_domain = models.check_company_domain_parent_of

    name = fields.Date(
        string="Date",
        required=True,
        index=True,
        default=fields.Date.context_today,
    )
    rate = fields.Float(
        digits=0,
        aggregator="avg",
        help="The rate of the currency to the currency of rate 1",
        string="Technical Rate",
    )
    company_rate = fields.Float(
        digits=0,
        compute="_compute_company_rate",
        inverse="_inverse_company_rate",
        aggregator="avg",
        help="The currency of rate 1 to the rate of the currency.",
    )
    inverse_company_rate = fields.Float(
        digits=0,
        compute="_compute_inverse_company_rate",
        inverse="_inverse_inverse_company_rate",
        aggregator="avg",
        help="The rate of the currency to the currency of rate 1 ",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        readonly=True,
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company.root_id,
    )

    _unique_name_per_day = models.Constraint(
        "unique (name,currency_id,company_id)",
        "Only one currency rate per day allowed!",
    )
    _currency_rate_check = models.Constraint(
        "CHECK (rate>0)",
        "The currency rate must be strictly positive.",
    )

    def _sanitize_vals(self, vals: dict[str, Any]) -> dict[str, Any]:
        """Drop redundant rate encodings from ``vals``.

        Returns a filtered copy when something must be dropped; the
        caller-owned dict is never mutated.
        """
        drop = set()
        if "inverse_company_rate" in vals and (
            "company_rate" in vals or "rate" in vals
        ):
            drop.add("inverse_company_rate")
        if "company_rate" in vals and "rate" in vals:
            drop.add("company_rate")
        if drop:
            return {name: value for name, value in vals.items() if name not in drop}
        return vals

    def write(self, vals: dict[str, Any]) -> bool:
        # Other currencies' rate/inverse_rate/rate_string may be computed against
        # self's rate rows (company/context currency and 'to_currency' in
        # _compute_current_rate) — a cross-record dependency @api.depends cannot
        # express, so invalidate all three model-wide.
        self.env["res.currency"].invalidate_model(
            ["rate", "inverse_rate", "rate_string"]
        )
        res = super().write(self._sanitize_vals(vals))
        # RCUR-M1: drop the transaction-scoped rate-history memo too.
        self.env.cr.cache.pop(RATE_HISTORY_CACHE_KEY, None)
        return res

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        # Model-wide invalidation for the same reason as write() above.
        self.env["res.currency"].invalidate_model(
            ["rate", "inverse_rate", "rate_string"]
        )
        records = super().create([self._sanitize_vals(vals) for vals in vals_list])
        # RCUR-M1: drop the transaction-scoped rate-history memo too.
        self.env.cr.cache.pop(RATE_HISTORY_CACHE_KEY, None)
        return records

    def unlink(self) -> bool:
        # Cross-record invalidation for the same reason as write() above.
        self.env["res.currency"].invalidate_model(
            ["rate", "inverse_rate", "rate_string"]
        )
        res = super().unlink()
        # RCUR-M1: drop the transaction-scoped rate-history memo too.
        self.env.cr.cache.pop(RATE_HISTORY_CACHE_KEY, None)
        return res

    def _get_latest_rate(self) -> Self:
        # Make sure 'name' is defined when creating a new rate.
        if not self.name:
            raise UserError(
                self.env._("The name for the current rate is empty.\nPlease set it.")
            )
        company = self.company_id or self.env.company.root_id
        # RCUR-P1: rate_ids is ordered "name desc, id" and dates are unique per
        # (currency, company), so the first match below is the latest rate
        # strictly before 'name' — no full filter + re-sort needed.
        for rate in self.currency_id.rate_ids.sudo():
            if rate.rate and rate.company_id == company and rate.name < self.name:
                return rate
        return self.browse()

    def _get_last_rates_for_companies(self, companies: Any) -> dict:
        result = {}
        for company in companies:
            # max by (name, id) matches the previous stable
            # .sorted("name")[-1:] tie-breaking without a per-company sort.
            last = max(
                (
                    rate
                    for rate in company.sudo().currency_id.rate_ids
                    if (rate.rate and rate.company_id == company) or not rate.company_id
                ),
                key=lambda rate: (rate.name, rate.id),
                default=None,
            )
            result[company] = (last.rate if last else 0) or 1
        return result

    @api.depends(
        "rate", "name", "currency_id", "company_id", "currency_id.rate_ids.rate"
    )
    @api.depends_context("company")
    def _compute_company_rate(self) -> None:
        env_company_root = self.env.company.root_id
        last_rate = self.env["res.currency.rate"]._get_last_rates_for_companies(
            self.company_id | env_company_root
        )
        # RCUR-P1: precompute, per (currency, company), the [(date, rate)] list
        # sorted by date once, then bisect per record — instead of filtering
        # and re-sorting the currency's whole rate history for every record.
        rates_per_key = {}
        for currency_rate in self:
            company = currency_rate.company_id or env_company_root
            rate = currency_rate.rate
            if not rate:
                # Same guard as _get_latest_rate: a dated lookup needs a date.
                if not currency_rate.name:
                    raise UserError(
                        self.env._(
                            "The name for the current rate is empty.\nPlease set it."
                        )
                    )
                key = (currency_rate.currency_id, company)
                candidates = rates_per_key.get(key)
                if candidates is None:
                    candidates = rates_per_key[key] = [
                        (rate_sudo.name, rate_sudo.rate)
                        for rate_sudo in currency_rate.currency_id.rate_ids.sudo()
                        if rate_sudo.rate and rate_sudo.company_id == company
                    ]
                    # rate_ids is ordered "name desc, id": reverse to the
                    # date-ascending order bisect needs (dates unique per
                    # currency/company).
                    candidates.reverse()
                # Latest rate strictly before this record's date, like
                # _get_latest_rate; 1.0 when there is none.
                index = bisect_left(candidates, (currency_rate.name,)) - 1
                rate = candidates[index][1] if index >= 0 else 1.0
            currency_rate.company_rate = rate / last_rate[company]

    @api.onchange("company_rate")
    def _inverse_company_rate(self) -> None:
        env_company_root = self.env.company.root_id
        last_rate = self.env["res.currency.rate"]._get_last_rates_for_companies(
            self.company_id | env_company_root
        )
        for currency_rate in self:
            company = currency_rate.company_id or env_company_root
            currency_rate.rate = currency_rate.company_rate * last_rate[company]

    @api.depends("company_rate")
    def _compute_inverse_company_rate(self) -> None:
        for currency_rate in self:
            # Use a local variable to avoid mutating company_rate (a dependency).
            company_rate = currency_rate.company_rate or 1.0
            currency_rate.inverse_company_rate = 1.0 / company_rate

    @api.onchange("inverse_company_rate")
    def _inverse_inverse_company_rate(self) -> None:
        for currency_rate in self:
            if not currency_rate.inverse_company_rate:
                currency_rate.inverse_company_rate = 1.0
            currency_rate.company_rate = 1.0 / currency_rate.inverse_company_rate

    @api.onchange("company_rate")
    def _onchange_rate_warning(self) -> dict[str, Any] | None:
        latest_rate = self._get_latest_rate()
        if latest_rate:
            diff = (latest_rate.rate - self.rate) / latest_rate.rate
            if abs(diff) > 0.2:
                return {
                    "warning": {
                        "title": self.env._("Warning for %s", self.currency_id.name),
                        "message": self.env._(
                            "The new rate is quite far from the previous rate.\n"
                            "Incorrect currency rates may cause critical problems, make sure the rate is correct!"
                        ),
                    }
                }
        return None

    @api.constrains("company_id")
    def _check_company_id(self) -> None:
        for rate in self:
            if rate.company_id.sudo().parent_id:
                raise ValidationError(
                    self.env._(
                        "Currency rates should only be created for main companies"
                    )
                )

    @api.model
    def _search_display_name(self, operator: str, value: Any) -> list:
        if isinstance(value, Iterable) and not isinstance(value, str):
            value = [parse_date(self.env, v) for v in value]
        else:
            value = parse_date(self.env, value)
        return super()._search_display_name(operator, value)

    @api.model
    def _get_view_cache_key(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple:
        """View cache must depend on the company currency, since _get_view
        relabels the rate fields with it."""
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (self.env["res.currency"]._get_context_company_currency_name(),)

    @api.model
    def _get_view(
        self, view_id: int | None = None, view_type: str = "form", **options
    ) -> tuple[etree._Element, Any]:
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == "list":
            names = {
                "company_currency_name": self.env[
                    "res.currency"
                ]._get_context_company_currency_name(),
                "rate_currency_name": self.env["res.currency"]
                .browse(self.env.context.get("active_id"))
                .name
                or "Unit",
            }
            for name, label in [
                [
                    "company_rate",
                    self.env._(
                        "%(rate_currency_name)s per %(company_currency_name)s",
                        **names,
                    ),
                ],
                [
                    "inverse_company_rate",
                    self.env._(
                        "%(company_currency_name)s per %(rate_currency_name)s",
                        **names,
                    ),
                ],
            ]:
                if (node := arch.find(f"./field[@name='{name}']")) is not None:
                    node.set("string", label)
        return arch, view
