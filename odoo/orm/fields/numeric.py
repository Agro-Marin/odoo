import typing
from decimal import Decimal
from operator import attrgetter
from typing import override

from odoo.exceptions import AccessError
from odoo.tools import float_compare, float_round
from odoo.tools.misc import PENDING, SENTINEL, Sentinel

from .base import Field, _make_scalar_get

if typing.TYPE_CHECKING:
    from .._typing import BaseModel, Environment, ModelLike

# Maximum value representable by XML-RPC's <i4> type (32-bit signed int).
# Values exceeding this are sent as floats to avoid XML-RPC transport errors.
MAXINT = 2**31 - 1


class Integer(Field[int]):
    """Encapsulates an :class:`int`."""

    type = "integer"
    _column_type = ("int4", "int4")
    falsy_value = 0

    aggregator = "sum"

    if not typing.TYPE_CHECKING:
        # Runtime fast path; the type checker inherits Field[int].__get__.
        __get__ = _make_scalar_get(lambda v: v or 0)

    def _get_attrs(
        self, model_class: type[BaseModel], name: str
    ) -> dict[str, typing.Any]:
        res = super()._get_attrs(model_class, name)
        # The default aggregator is None for sequence fields
        if "aggregator" not in res and name == "sequence":
            res["aggregator"] = None
        return res

    @override
    def convert_to_column(
        self,
        value,
        record: BaseModel,
        values: dict | None = None,
        validate: bool = True,
    ) -> typing.Any:
        return int(value or 0)

    @override
    def convert_to_cache(
        self, value, record: BaseModel, validate: bool = True
    ) -> typing.Any:
        # fast path: most writes already pass an int
        if value.__class__ is int:
            return value
        if isinstance(value, dict):
            # integer field used as inverse for a one2many: a missing/falsy id
            # collapses to 0 (never None) to keep the cache in-type.
            return value.get("id") or 0
        return int(value or 0)

    @override
    def convert_to_record(
        self, value, record: BaseModel
    ) -> int | typing.Literal[False]:
        return value or 0

    @override
    def convert_to_read(
        self, value, record: BaseModel, use_display_name: bool = True
    ) -> typing.Any:
        # XML-RPC's i4 can't marshal values outside [-2^31, 2^31-1]; pass those
        # as floats. Guard both ends.
        if value and not (-MAXINT - 1 <= value <= MAXINT):
            return float(value)
        return value

    def _update_inverse(self, records: BaseModel, value: BaseModel) -> None:
        self._update_cache(records, value.id or 0)

    @override
    def convert_to_export(self, value, record: BaseModel) -> typing.Any:
        if value or value == 0:
            return value
        return ""


class Float(Field[float]):
    """Encapsulates a :class:`float`.

    The precision digits are given by the (optional) ``digits`` attribute.

    :param digits: a pair (total, decimal) or a string referencing a
        :class:`~odoo.addons.base.models.decimal_precision.DecimalPrecision` record name.
    :type digits: tuple(int,int) or str

    When a float is a quantity associated with a unit of measure, use the right
    tool to compare or round values with the correct precision.

    The Float class provides static methods for this purpose:

    :func:`~odoo.fields.Float.round()` to round a float with the given precision.
    :func:`~odoo.fields.Float.compare()` to compare two floats at the given precision.

    .. admonition:: Example

        To round a quantity with the precision of the unit of measure::

            fields.Float.round(
                self.product_uom_qty, precision_rounding=self.product_uom_id.rounding
            )

        To compare two quantities::

            field.Float.compare(
                self.product_uom_qty,
                self.qty_done,
                precision_rounding=self.product_uom_id.rounding,
            )

        The compare helper uses __cmp__ semantics for historic reasons, so the
        idiomatic way to use it is:

            if result == 0, the first and second floats are equal
            if result < 0, the first float is lower than the second
            if result > 0, the first float is greater than the second
    """

    type = "float"
    _digits: str | tuple[int, int] | None = (
        None  # digits argument passed to class initializer
    )
    _min_display_digits: str | int | None = None
    falsy_value = 0.0
    aggregator = "sum"

    if not typing.TYPE_CHECKING:
        # Runtime fast path; the type checker inherits Field[float].__get__.
        __get__ = _make_scalar_get(lambda v: v or 0.0)

    def __init__(
        self,
        string: str | Sentinel = SENTINEL,
        digits: str | tuple[int, int] | Sentinel | None = SENTINEL,
        min_display_digits: str | int | Sentinel | None = SENTINEL,
        **kwargs,
    ):
        if digits is SENTINEL and min_display_digits is not SENTINEL:
            digits = False
        super().__init__(
            string=string,
            _digits=digits,
            _min_display_digits=min_display_digits,
            **kwargs,
        )

    @property
    def _column_type(self) -> tuple[str, str]:
        # digits set (incl. falsy 0/False) -> NUMERIC, keeping all significant
        # digits. digits=None -> float8 (default): faster for sums etc.
        return (
            ("numeric", "numeric")
            if self._digits is not None
            else ("float8", "double precision")
        )

    def get_digits(self, env: Environment) -> tuple[int, int] | None:
        if isinstance(self._digits, str):
            precision = env["decimal.precision"].precision_get(self._digits)
            return 16, precision
        else:
            return self._digits

    _related__digits = property(attrgetter("_digits"))

    def _description_digits(self, env: Environment) -> tuple[int, int] | None:
        return self.get_digits(env)

    def get_min_display_digits(self, env: Environment) -> int | None:
        if isinstance(self._min_display_digits, str):
            return env["decimal.precision"].precision_get(self._min_display_digits)
        return self._min_display_digits

    def _description_min_display_digits(self, env: Environment) -> int | None:
        return self.get_min_display_digits(env)

    @override
    def convert_to_column(
        self,
        value,
        record: BaseModel,
        values: dict | None = None,
        validate: bool = True,
    ) -> typing.Any:
        value = float(value or 0.0)
        if digits := self.get_digits(record.env):
            _precision, scale = digits
            value = float_round(value, precision_digits=scale)
        elif self._digits is not None and self.column_type[0] == "numeric":
            # digits=0: NUMERIC column with unlimited precision. Send a Decimal
            # so the value round-trips exactly; a float would go through
            # PostgreSQL's float8->numeric cast, which keeps only 15 significant
            # digits (e.g. a uom factor of 1/60 comes back changed).
            # Company-dependent floats also have falsy digits but live in a
            # JSONB column: keep those as float.
            return Decimal(repr(value))
        return value

    @override
    def convert_to_cache(
        self, value, record: BaseModel, validate: bool = True
    ) -> typing.Any:
        # Fast path: float with no digits constraint (most Float fields)
        if value.__class__ is float and self._digits is None:
            return value
        # apply rounding here, otherwise value in cache may be wrong!
        value = float(value or 0.0)
        # Fast path: inline digit resolution for the common tuple case
        digits = self._digits
        if digits is None:
            return value
        if isinstance(digits, tuple):
            return float_round(value, precision_digits=digits[1])
        if not isinstance(digits, str):
            # Falsy/integer digits (e.g., digits=0): NUMERIC with no fixed precision
            return value
        # String-referenced precision (rare): needs env lookup
        precision = record.env["decimal.precision"].precision_get(digits)
        return float_round(value, precision_digits=precision)

    @override
    def convert_to_record(
        self, value, record: BaseModel
    ) -> float | typing.Literal[False]:
        return value or 0.0

    @override
    def convert_to_export(self, value, record: BaseModel) -> typing.Any:
        if value or value == 0.0:  # noqa: RUF069  # exact-zero check distinguishes 0.0 from empty
            return value
        return ""

    round = staticmethod(float_round)
    compare = staticmethod(float_compare)


class Monetary(Field[float]):
    """Encapsulates a :class:`float` expressed in a given
    :class:`res_currency<odoo.addons.base.models.res_currency.Currency>`.

    The decimal precision and currency symbol are taken from the ``currency_field`` attribute.

    :param str currency_field: name of the :class:`Many2one` field
        holding the :class:`res_currency <odoo.addons.base.models.res_currency.Currency>`
        this monetary field is expressed in (default: `\'currency_id\'`)
    """

    type = "monetary"
    write_sequence = 10
    _column_type = ("numeric", "numeric")
    falsy_value = 0.0

    if not typing.TYPE_CHECKING:
        # Runtime fast path; the type checker inherits Field[float].__get__.
        __get__ = _make_scalar_get(lambda v: v or 0.0)

    currency_field: Field | None = None
    aggregator = "sum"

    def __init__(
        self,
        string: str | Sentinel = SENTINEL,
        currency_field: str | Sentinel = SENTINEL,
        **kwargs,
    ):
        super().__init__(string=string, currency_field=currency_field, **kwargs)

    def _description_currency_field(self, env: Environment) -> str | None:
        return self.get_currency_field(env[self.model_name])

    def _description_aggregator(self, env: Environment) -> str | None:
        model = env[self.model_name]
        query = model._as_query(ordered=False)
        currency_field_name = self.get_currency_field(model)
        currency_field = model._fields[currency_field_name]
        # The currency field needs to be aggregable too
        if not currency_field.column_type or not currency_field.store:
            try:
                model._read_group_select(
                    f"{currency_field_name}:array_agg_distinct", query
                )
            except (ValueError, AccessError):
                return None

        return super()._description_aggregator(env)

    def get_currency_field(self, model: ModelLike) -> str | None:
        """Return the name of the currency field."""
        return self.currency_field or (
            "currency_id"
            if "currency_id" in model._fields
            else "x_currency_id"
            if "x_currency_id" in model._fields
            else None
        )

    def _currency_record(self, record: BaseModel):
        """Return ``record[:1]``'s currency for this monetary field (or empty).

        ``prefetch_fields=False`` is load-bearing: the ``value`` being converted
        may already sit in cache, and prefetching siblings here could overwrite
        it with the stale DB value before flush. ``sudo()`` because the currency
        may be ACL-restricted. (``convert_to_cache`` keeps its own variant: it
        scans *all* records for a single currency, not just ``[:1]``.)
        """
        currency_field_name = self.get_currency_field(record)
        if not currency_field_name:
            return None
        return (
            record[:1].sudo().with_context(prefetch_fields=False)[currency_field_name]
        )

    def setup_nonrelated(self, model: BaseModel) -> None:
        super().setup_nonrelated(model)
        assert self.get_currency_field(model) in model._fields, (
            f"Field {self} with unknown currency_field {self.get_currency_field(model)!r}"
        )

    def setup_related(self, model: BaseModel) -> None:
        super().setup_related(model)
        if self.inherited:
            self.currency_field = self.related_field.get_currency_field(
                model.env[self.related_field.model_name]
            )
        assert self.get_currency_field(model) in model._fields, (
            f"Field {self} with unknown currency_field {self.get_currency_field(model)!r}"
        )

    @override
    def convert_to_column(
        self,
        value,
        record: BaseModel,
        values: dict | None = None,
        validate: bool = True,
    ) -> typing.Any:
        value = float(value or 0.0)
        if not value:
            return value
        # Apply currency rounding only on actual records (not the model class).
        if record.ids:
            currency = self._currency_record(record)
            if currency:
                return currency.with_env(record.env).round(value)
        return value

    def convert_to_column_insert(
        self,
        value,
        record: BaseModel,
        values: dict | None = None,
        validate: bool = True,
    ) -> typing.Any:
        # retrieve currency from values or record
        currency_field_name = self.get_currency_field(record)
        currency_field = record._fields[currency_field_name]
        if values and currency_field_name in values:
            dummy = record.new({currency_field_name: values[currency_field_name]})
            currency = dummy[currency_field_name]
        elif (
            values
            and currency_field.related
            and currency_field.related.split(".")[0] in values
        ):
            related_field_name = currency_field.related.split(".")[0]
            dummy = record.new({related_field_name: values[related_field_name]})
            currency = dummy[currency_field_name]
        else:
            # Wrong if 'record' spans several currencies, but that is functional
            # nonsense and should not happen. _currency_record keeps the
            # no-prefetch invariant (prefetching could overwrite the cached
            # 'value').
            currency = self._currency_record(record).with_env(record.env)

        value = float(value or 0.0)
        if currency:
            return currency.round(value)
        return value

    @override
    def convert_to_cache(
        self, value, record: BaseModel, validate: bool = True
    ) -> typing.Any:
        # cache format: float
        value = float(value or 0.0)
        if value and validate:
            # The currency field may be uninitialized (computed/related, during
            # creation). prefetch_fields=False avoids reading unrelated fields
            # that could overwrite the value being cached.
            currency_field = self.get_currency_field(record)
            currency = record.sudo().with_context(prefetch_fields=False)[currency_field]
            if len(currency) > 1:
                raise ValueError(
                    "Got multiple currencies while assigning values of monetary field %s"
                    % str(self)
                )
            if currency:
                value = currency.with_env(record.env).round(value)
        return value

    @override
    def convert_to_record(
        self, value, record: BaseModel
    ) -> float | typing.Literal[False]:
        return value or 0.0

    @override
    def convert_to_read(
        self, value, record: BaseModel, use_display_name: bool = True
    ) -> typing.Any:
        return value

    @override
    def convert_to_write(self, value, record: BaseModel) -> typing.Any:
        return value

    @override
    def convert_to_export(self, value, record: BaseModel) -> typing.Any:
        if value or value == 0.0:  # noqa: RUF069  # exact-zero check distinguishes 0.0 from empty
            return value
        return ""

    def _filter_not_equal(
        self, records: BaseModel, cache_value: typing.Any
    ) -> BaseModel:
        records = super()._filter_not_equal(records, cache_value)
        if not records:
            return records
        # check that the values were rounded properly when put in cache
        # (see odoo/odoo#177200)
        env = records.env
        field_cache = self._get_cache(env)
        currency_field = records._fields[self.get_currency_field(records)]
        return records.browse(
            record_id
            for record_id, record_sudo in zip(
                records._ids,
                records.sudo().with_context(prefetch_fields=False),
                strict=False,
            )
            if not (
                (value := field_cache.get(record_id))
                and value is not PENDING
                and (currency := currency_field.__get__(record_sudo))
                and currency.with_env(env).round(value) == cache_value
            )
        )
