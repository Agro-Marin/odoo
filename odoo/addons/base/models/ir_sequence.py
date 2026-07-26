import logging
from datetime import datetime, timedelta
from typing import Any, Self

import psycopg.errors

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def _create_sequence(
    cr: Any, seq_name: str, number_increment: int, number_next: int
) -> None:
    """Create a PostgreSQL sequence."""
    if number_increment == 0:
        raise UserError(_("Step must not be zero."))
    cr.execute(
        SQL(
            "CREATE SEQUENCE %s INCREMENT BY %s START WITH %s",
            SQL.identifier(seq_name),
            number_increment,
            max(number_next, 1),
        )
    )


def _drop_sequences(cr: Any, seq_names: list[str]) -> None:
    """Drop the PostgreSQL sequences if they exist."""
    if not seq_names:
        return
    names = SQL(",").join(map(SQL.identifier, seq_names))
    cr.execute(SQL("DROP SEQUENCE IF EXISTS %s RESTRICT", names))


def _alter_sequence(
    cr: Any,
    seq_name: str,
    number_increment: int | None = None,
    number_next: int | None = None,
) -> None:
    """Alter a PostgreSQL sequence."""
    if number_increment is None and number_next is None:
        return
    if number_increment == 0:
        raise UserError(_("Step must not be zero."))
    cr.execute(
        "SELECT relname FROM pg_class"
        " WHERE relkind = %s AND relname = %s"
        "   AND relnamespace = current_schema::regnamespace",
        ("S", seq_name),
    )
    if not cr.fetchone():
        return
    statement = SQL(
        "ALTER SEQUENCE %s%s%s",
        SQL.identifier(seq_name),
        (
            SQL(" INCREMENT BY %s", number_increment)
            if number_increment is not None
            else SQL()
        ),
        (
            SQL(" RESTART WITH %s", max(number_next, 1))
            if number_next is not None
            else SQL()
        ),
    )
    cr.execute(statement)


def _select_nextval(cr: Any, seq_name: str) -> int:
    """Return the next value from a PostgreSQL sequence as an integer."""
    cr.execute("SELECT nextval(%s)", [seq_name])
    return cr.fetchone()[0]


def _update_nogap(self: Any, number_increment: int) -> int:
    self.flush_recordset(["number_next"])
    table = SQL.identifier(self._table)
    self.env.cr.execute(
        SQL(
            "WITH locked AS ("
            "SELECT number_next FROM %s WHERE id=%s FOR UPDATE NOWAIT"
            ") "
            "UPDATE %s t SET number_next = t.number_next + %s "
            "FROM locked WHERE t.id = %s "
            "RETURNING locked.number_next",
            table,
            self.id,
            table,
            number_increment,
            self.id,
        )
    )
    [number_next] = self.env.cr.fetchone()
    self.invalidate_recordset(["number_next"])
    return number_next


def _predict_nextval(self: Any, seq_name: str) -> int:
    """Predict next value for PostgreSQL sequence without consuming it"""
    seqtable = SQL.identifier(seq_name)
    query = SQL(
        """
        SELECT last_value,
            (SELECT increment_by FROM pg_sequences
             WHERE schemaname = current_schema AND sequencename = %s),
            is_called
        FROM %s""",
        seq_name,
        seqtable,
    )
    [(last_value, increment_by, is_called)] = self.env.execute_query(query)
    if is_called:
        return last_value + increment_by
    return last_value


_INTERPOLATION_FORMATS = {
    "year": "%Y",
    "month": "%m",
    "day": "%d",
    "y": "%y",
    "doy": "%j",
    "woy": "%W",
    "weekday": "%w",
    "h24": "%H",
    "h12": "%I",
    "min": "%M",
    "sec": "%S",
    "isoyear": "%G",
    "isoy": "%g",
    "isoweek": "%V",
}


class _InterpolationDict(dict):
    """Lazy mapping for the legacy ``%(key)s`` prefix/suffix placeholders.

    Values are strftime-formatted on first access via ``__missing__`` and
    cached, so drawing a number avoids formatting the full 14 formats x 3 dates
    matrix when a pattern references only a few keys. Unknown keys raise
    ``KeyError``, which ``_get_prefix_suffix`` turns into a ``UserError``.
    """

    def __init__(
        self, effective_date: datetime, range_date: datetime, now: datetime
    ) -> None:
        super().__init__()
        self._dates = {"": effective_date, "range_": range_date, "current_": now}

    def __missing__(self, key: str) -> str:
        date, fmt_key = self._dates[""], key
        for date_prefix in ("range_", "current_"):
            if key.startswith(date_prefix):
                date = self._dates[date_prefix]
                fmt_key = key.removeprefix(date_prefix)
                break
        try:
            fmt = _INTERPOLATION_FORMATS[fmt_key]
        except KeyError:
            raise KeyError(key) from None
        value = date.strftime(fmt)
        self[key] = value
        return value


class IrSequence(models.Model):
    """Sequence objects that generate unique identifiers in a transaction-safe way."""

    _name = "ir.sequence"
    _description = "Sequence"
    _order = "name, id"
    _allow_sudo_commands = False

    def _pg_sequence_name(self) -> str:
        """Return the name of the PostgreSQL sequence backing this record."""
        return "ir_sequence_%03d" % self.id

    @api.depends("implementation", "number_next")
    def _get_number_next_actual(self) -> None:
        """Return number from ir_sequence row when no_gap implementation,
        and number from postgres sequence when standard implementation.

        The declared dependencies cover the ``no_gap`` branch, which simply
        mirrors ``number_next``: without them the field was computed once per
        transaction cache and never invalidated, so writing ``number_next`` left
        the *inversable* ``number_next_actual`` showing the old value.

        The ``standard`` branch reads a PostgreSQL sequence, which no
        ``@api.depends`` can track -- that value is volatile by nature (see the
        field's own help text) and a stale read there is expected.
        """
        for seq in self:
            if not seq.id:
                seq.number_next_actual = 0
            elif seq.implementation != "standard":
                seq.number_next_actual = seq.number_next
            else:
                seq.number_next_actual = _predict_nextval(seq, seq._pg_sequence_name())

    def _set_number_next_actual(self) -> None:
        for seq in self:
            val = seq.number_next_actual
            seq.write({"number_next": val if val is not None else 1})

    name = fields.Char(required=True)
    code = fields.Char(string="Sequence Code")
    implementation = fields.Selection(
        [("standard", "Standard"), ("no_gap", "No gap")],
        string="Implementation",
        required=True,
        default="standard",
        help="While assigning a sequence number to a record, the 'no gap' sequence implementation ensures that each previous sequence number has been assigned already. "
        "While this sequence implementation will not skip any sequence number upon assignment, there can still be gaps in the sequence if records are deleted. "
        "The 'no gap' implementation is slower than the standard one.",
    )
    active = fields.Boolean(default=True)
    prefix = fields.Char(help="Prefix value of the record for the sequence", trim=False)
    suffix = fields.Char(help="Suffix value of the record for the sequence", trim=False)
    number_next = fields.Integer(
        string="Next Number",
        required=True,
        default=1,
        help="Next number of this sequence",
    )
    number_next_actual = fields.Integer(
        compute="_get_number_next_actual",
        inverse="_set_number_next_actual",
        string="Actual Next Number",
        help="Next number that will be used. This number can be incremented "
        "frequently so the displayed value might already be obsolete",
    )
    number_increment = fields.Integer(
        string="Step",
        required=True,
        default=1,
        help="The next number of the sequence will be incremented by this number",
    )
    padding = fields.Integer(
        string="Sequence Size",
        required=True,
        default=0,
        help="Odoo will automatically adds some '0' on the left of the 'Next Number' to get the required padding size.",
    )
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda s: s.env.company
    )
    use_date_range = fields.Boolean(string="Use subsequences per date_range")
    date_range_ids = fields.One2many(
        "ir.sequence.date_range", "sequence_id", string="Subsequences"
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create a sequence; the ``standard`` implementation is backed by a fast, gaps-allowed PostgreSQL sequence."""
        seqs = super().create(vals_list)
        for seq in seqs:
            if seq.implementation == "standard":
                _create_sequence(
                    self.env.cr,
                    seq._pg_sequence_name(),
                    seq.number_increment or 1,
                    seq.number_next if seq.number_next is not None else 1,
                )
        return seqs

    def unlink(self) -> bool:
        _drop_sequences(self.env.cr, [x._pg_sequence_name() for x in self])
        return super().unlink()

    def write(self, vals: dict[str, Any]) -> bool:
        new_implementation = vals.get("implementation")
        for seq in self:
            i = vals.get("number_increment", seq.number_increment)
            n = vals.get("number_next", seq.number_next)
            if seq.implementation == "standard":
                if new_implementation in ("standard", None):
                    if "number_next" in vals:
                        _alter_sequence(
                            self.env.cr,
                            seq._pg_sequence_name(),
                            number_next=n,
                        )
                    if seq.number_increment != i:
                        _alter_sequence(
                            self.env.cr,
                            seq._pg_sequence_name(),
                            number_increment=i,
                        )
                        seq.date_range_ids._alter_sequence(number_increment=i)
                else:
                    if "number_next" not in vals and "number_next_actual" not in vals:
                        seq_seed = _predict_nextval(seq, seq._pg_sequence_name())
                        sub_seeds = [
                            (
                                sub_seq.id,
                                _predict_nextval(sub_seq, sub_seq._pg_sequence_name()),
                            )
                            for sub_seq in seq.date_range_ids
                        ]
                        seq.flush_recordset(["number_next"])
                        self.env.cr.execute(
                            SQL(
                                "UPDATE %s SET number_next=%s WHERE id=%s",
                                SQL.identifier(seq._table),
                                seq_seed,
                                seq.id,
                            )
                        )
                        seq.invalidate_recordset(["number_next", "number_next_actual"])
                        if sub_seeds:
                            sub_seqs = seq.date_range_ids
                            sub_seqs.flush_recordset(["number_next"])
                            self.env.cr.execute(
                                SQL(
                                    "UPDATE %s t SET number_next = v.number_next"
                                    " FROM unnest(%s::int[], %s::int[])"
                                    " AS v(id, number_next)"
                                    " WHERE t.id = v.id",
                                    SQL.identifier(sub_seqs._table),
                                    [sub_id for sub_id, _ in sub_seeds],
                                    [number for _, number in sub_seeds],
                                )
                            )
                            sub_seqs.invalidate_recordset(
                                ["number_next", "number_next_actual"]
                            )
                    _drop_sequences(
                        self.env.cr,
                        [
                            seq._pg_sequence_name(),
                            *(s._pg_sequence_name() for s in seq.date_range_ids),
                        ],
                    )
            elif new_implementation in ("no_gap", None):
                pass
            else:
                _create_sequence(self.env.cr, seq._pg_sequence_name(), i, n)
                for sub_seq in seq.date_range_ids:
                    _create_sequence(
                        self.env.cr,
                        sub_seq._pg_sequence_name(),
                        i,
                        sub_seq.number_next,
                    )
        res = super().write(vals)
        self.flush_model(vals.keys())
        return res

    def _next_do(self) -> str:
        if self.implementation == "standard":
            number_next = _select_nextval(self.env.cr, self._pg_sequence_name())
        else:
            number_next = _update_nogap(self, self.number_increment)
        return self.get_next_char(number_next)

    def _get_prefix_suffix(
        self, date: Any = None, date_range: Any = None
    ) -> tuple[str, str]:
        def _interpolate(s, d):
            return (s % d) if s else ""

        self.ensure_one()
        if not self.prefix and not self.suffix:
            return "", ""
        now = range_date = effective_date = datetime.now(self.env.tz)
        if date or self.env.context.get("ir_sequence_date"):
            effective_date = fields.Datetime.from_string(
                date or self.env.context.get("ir_sequence_date")
            )
        if date_range or self.env.context.get("ir_sequence_date_range"):
            range_date = fields.Datetime.from_string(
                date_range or self.env.context.get("ir_sequence_date_range")
            )
        d = _InterpolationDict(effective_date, range_date, now)
        try:
            interpolated_prefix = _interpolate(self.prefix, d)
            interpolated_suffix = _interpolate(self.suffix, d)
        except ValueError, TypeError, KeyError:
            raise UserError(
                _("Invalid prefix or suffix for sequence '%s'", self.name)
            ) from None
        return interpolated_prefix, interpolated_suffix

    def get_next_char(self, number_next: int) -> str:
        interpolated_prefix, interpolated_suffix = self._get_prefix_suffix()
        return (
            interpolated_prefix
            + f"{number_next:0{max(0, self.padding)}d}"
            + interpolated_suffix
        )

    def _create_date_range_seq(self, date: Any) -> Any:
        """Create the ``ir.sequence.date_range`` covering ``date``.

        The new range defaults to the calendar year of ``date`` and is then
        clamped to avoid overlapping any existing adjacent range.

        :param date: the date the new sub-sequence must cover
        :return: the created ``ir.sequence.date_range`` record
        """
        year = fields.Date.from_string(date).strftime("%Y")
        date_from = f"{year}-01-01"
        date_to = f"{year}-12-31"
        date_range = self.env["ir.sequence.date_range"].search(
            [
                ("sequence_id", "=", self.id),
                ("date_from", ">=", date),
                ("date_from", "<=", date_to),
            ],
            order="date_from asc",
            limit=1,
        )
        if date_range:
            date_to = date_range.date_from + timedelta(days=-1)
        date_range = self.env["ir.sequence.date_range"].search(
            [
                ("sequence_id", "=", self.id),
                ("date_to", ">=", date_from),
                ("date_to", "<=", date),
            ],
            order="date_to desc",
            limit=1,
        )
        if date_range:
            date_from = date_range.date_to + timedelta(days=1)
        seq_date_range = self.env["ir.sequence.date_range"].sudo()
        try:
            with self.env.cr.savepoint():
                return seq_date_range.create(
                    {
                        "date_from": date_from,
                        "date_to": date_to,
                        "sequence_id": self.id,
                    }
                )
        except psycopg.errors.UniqueViolation:
            return seq_date_range.search(
                [
                    ("sequence_id", "=", self.id),
                    ("date_from", "<=", date),
                    ("date_to", ">=", date),
                ],
                limit=1,
            )

    def _get_current_sequence(self, sequence_date: Any = None) -> Any:
        """Return the concrete record that holds this sequence's counter.

        For a plain sequence that is ``self``; for a date-ranged one it is the
        ``ir.sequence.date_range`` sub-sequence covering ``sequence_date`` (or
        the contextual / current date), created on the fly if none exists yet.
        """
        self.ensure_one()
        if not self.use_date_range:
            return self
        dt = sequence_date or self.env.context.get(
            "ir_sequence_date", fields.Datetime.now()
        )
        seq_date = self.env["ir.sequence.date_range"].search(
            [
                ("sequence_id", "=", self.id),
                ("date_from", "<=", dt),
                ("date_to", ">=", dt),
            ],
            limit=1,
        )
        return seq_date or self._create_date_range_seq(dt)

    def _next(self, sequence_date: Any = None) -> str:
        """Return the next interpolated value for this sequence."""
        if not self.use_date_range:
            if sequence_date is None:
                return self._next_do()
            ir_sequence_date = (
                sequence_date.replace(tzinfo=None)
                if isinstance(sequence_date, datetime)
                else sequence_date
            )
            return self.with_context(ir_sequence_date=ir_sequence_date)._next_do()
        dt = sequence_date or self.env.context.get(
            "ir_sequence_date", fields.Datetime.now()
        )
        seq_date = self._get_current_sequence(dt)
        ir_sequence_date = dt.replace(tzinfo=None) if isinstance(dt, datetime) else dt
        return seq_date.with_context(
            ir_sequence_date_range=seq_date.date_from,
            ir_sequence_date=ir_sequence_date,
        )._next()

    def next_by_id(self, sequence_date: Any = None) -> str:
        """Draw an interpolated string using the specified sequence."""
        self.browse().check_access("read")
        return self._next(sequence_date=sequence_date)

    def preview_next(self, sequence_date: Any = None) -> str:
        """Interpolated preview of the next value WITHOUT consuming it.

        Unlike ``next_by_id`` this never increments the counter nor creates a
        date range, so clients may call it freely to display the upcoming
        value (e.g. serial/lot generators). The preview can go stale if a
        concurrent transaction draws from the sequence in the meantime.
        """
        self.browse().check_access("read")
        self.ensure_one()
        if not self.use_date_range:
            if sequence_date is None:
                return self.get_next_char(self.number_next_actual)
            ir_sequence_date = (
                sequence_date.replace(tzinfo=None)
                if isinstance(sequence_date, datetime)
                else sequence_date
            )
            return self.with_context(ir_sequence_date=ir_sequence_date).get_next_char(
                self.number_next_actual
            )
        dt = sequence_date or self.env.context.get(
            "ir_sequence_date", fields.Datetime.now()
        )
        date_range = self.env["ir.sequence.date_range"].search(
            [
                ("sequence_id", "=", self.id),
                ("date_from", "<=", dt),
                ("date_to", ">=", dt),
            ],
            limit=1,
        )
        number_next = date_range.number_next_actual if date_range else 1
        ir_sequence_date = dt.replace(tzinfo=None) if isinstance(dt, datetime) else dt
        return self.with_context(
            ir_sequence_date_range=(
                date_range.date_from
                if date_range
                else fields.Date.to_date(f"{fields.Date.to_date(dt).year}-01-01")
            ),
            ir_sequence_date=ir_sequence_date,
        ).get_next_char(number_next)

    @api.model
    def next_by_code(self, sequence_code: str, sequence_date: Any = None) -> str | bool:
        """Draw an interpolated string using a sequence with the requested code.
        If several sequences with the correct code are available to the user
        (multi-company cases), the one from the user's current company will
        be used.
        """
        self.browse().check_access("read")
        company_id = self.env.company.id
        seq_ids = self.search(
            [
                ("code", "=", sequence_code),
                ("company_id", "in", [company_id, False]),
            ],
            order="company_id",
        )
        if not seq_ids:
            _logger.debug(
                "No ir.sequence has been found for code '%s'. Please make sure a sequence is set for current company.",
                sequence_code,
            )
            return False
        seq_id = seq_ids[0]
        return seq_id._next(sequence_date=sequence_date)


class IrSequenceDate_Range(models.Model):
    _name = "ir.sequence.date_range"
    _description = "Sequence Date Range"
    _rec_name = "sequence_id"
    _allow_sudo_commands = False

    _unique_range_per_sequence = models.Constraint(
        "UNIQUE(sequence_id, date_from, date_to)",
        "You cannot create two date ranges for the same sequence with the same date range.",
    )

    def _pg_sequence_name(self) -> str:
        """Return the name of the PostgreSQL sequence backing this sub-sequence."""
        return "ir_sequence_%03d_%03d" % (self.sequence_id.id, self.id)

    @api.depends("number_next", "sequence_id.implementation")
    def _get_number_next_actual(self) -> None:
        """Return number_next from the date_range row (no_gap parent) or from
        the PostgreSQL sequence (standard parent).

        Same reasoning as ``ir.sequence._get_number_next_actual``: the declared
        dependencies cover the no_gap branch (which mirrors ``number_next``),
        while the standard branch reads a PostgreSQL sequence that no
        ``@api.depends`` can track.
        """
        for seq in self:
            if not seq.id or seq.sequence_id.implementation != "standard":
                seq.number_next_actual = seq.number_next
            else:
                seq.number_next_actual = _predict_nextval(seq, seq._pg_sequence_name())

    def _set_number_next_actual(self) -> None:
        for seq in self:
            val = seq.number_next_actual
            seq.write({"number_next": val if val is not None else 1})

    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", required=True)
    sequence_id = fields.Many2one(
        "ir.sequence", string="Main Sequence", required=True, ondelete="cascade"
    )
    number_next = fields.Integer(
        string="Next Number",
        required=True,
        default=1,
        help="Next number of this sequence",
    )
    number_next_actual = fields.Integer(
        compute="_get_number_next_actual",
        inverse="_set_number_next_actual",
        string="Actual Next Number",
        help="Next number that will be used. This number can be incremented "
        "frequently so the displayed value might already be obsolete",
    )

    def _next(self) -> str:
        """Draw the next interpolated value from this date-range sub-sequence."""
        if self.sequence_id.implementation == "standard":
            number_next = _select_nextval(self.env.cr, self._pg_sequence_name())
        else:
            number_next = _update_nogap(self, self.sequence_id.number_increment)
        return self.sequence_id.get_next_char(number_next)

    def _alter_sequence(
        self,
        number_increment: int | None = None,
        number_next: int | None = None,
    ) -> None:
        """Alter the PostgreSQL sub-sequence(s) backing these date ranges.

        :param number_increment: new step, or ``None`` to leave unchanged
        :param number_next: new restart value, or ``None`` to leave unchanged
        """
        for seq in self:
            _alter_sequence(
                self.env.cr,
                seq._pg_sequence_name(),
                number_increment=number_increment,
                number_next=number_next,
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create a sequence; the ``standard`` implementation is backed by a fast, gaps-allowed PostgreSQL sequence."""
        seqs = super().create(vals_list)
        for seq in seqs:
            main_seq = seq.sequence_id
            if main_seq.implementation == "standard":
                val = seq.number_next
                _create_sequence(
                    self.env.cr,
                    seq._pg_sequence_name(),
                    main_seq.number_increment or 1,
                    val if val is not None else 1,
                )
        return seqs

    def unlink(self) -> bool:
        _drop_sequences(self.env.cr, [x._pg_sequence_name() for x in self])
        return super().unlink()

    def write(self, vals: dict[str, Any]) -> bool:
        if "number_next" in vals:
            seq_to_alter = self.filtered(
                lambda seq: seq.sequence_id.implementation == "standard"
            )
            seq_to_alter._alter_sequence(number_next=vals["number_next"])
        res = super().write(vals)
        self.flush_model(vals.keys())
        return res
