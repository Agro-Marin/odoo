import logging
import re
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any, Self

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.db import insert_or_existing
from odoo.exceptions import UserError
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def _create_sequence(
    cr: Any, seq_name: str, number_increment: int, number_next: int
) -> None:
    cr.execute(
        SQL(
            "CREATE SEQUENCE %s INCREMENT BY %s START WITH %s",
            SQL.identifier(seq_name),
            number_increment,
            max(number_next, 1),
        )
    )


def _drop_sequences(cr: Any, seq_names: list[str]) -> None:
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
    if number_increment is None and number_next is None:
        return
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


def _predict_nextvals(env: Any, seq_names: Collection[str]) -> dict[str, int]:
    if not seq_names:
        return {}
    increments = dict(
        env.execute_query(
            SQL(
                "SELECT sequencename, increment_by FROM pg_sequences"
                " WHERE schemaname = current_schema"
                "   AND sequencename = ANY(%s::name[])",
                list(seq_names),
            )
        )
    )
    if not increments:
        return {}
    reads = SQL(" UNION ALL ").join(
        SQL(
            "SELECT %s AS name, last_value, is_called FROM %s",
            name,
            SQL.identifier(name),
        )
        for name in increments
    )
    return {
        name: last_value + increments[name] if is_called else last_value
        for name, last_value, is_called in env.execute_query(reads)
    }


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

# Width of what each format above emits. strftime zero-pads all of them, which is
# what makes the table invertible: a fixed width per placeholder is enough to take
# a string the pattern produced back apart. Kept beside the formats so the two
# cannot drift.
_INTERPOLATION_WIDTHS = {
    "year": 4,
    "month": 2,
    "day": 2,
    "y": 2,
    "doy": 3,
    "woy": 2,
    "weekday": 1,
    "h24": 2,
    "h12": 2,
    "min": 2,
    "sec": 2,
    "isoyear": 4,
    "isoy": 2,
    "isoweek": 2,
}

# Same `range_` / `current_` prefixes `_InterpolationDict.__missing__` accepts.
_INTERPOLATION_REGEXES = {
    prefix + name: rf"\d{{{width}}}"
    for name, width in _INTERPOLATION_WIDTHS.items()
    for prefix in ("", "range_", "current_")
}

_PLACEHOLDER_RE = re.compile(r"%\((\w+)\)s")


class _InterpolationDict(dict):
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
    _name = "ir.sequence"
    _description = "Sequence"
    _order = "name, id"
    _allow_sudo_commands = False

    def _pg_sequence_name(self) -> str:
        return "ir_sequence_%03d" % self.id

    @api.depends("implementation", "number_next")
    def _get_number_next_actual(self) -> None:
        standard = self.filtered(
            lambda seq: seq.id and seq.implementation == "standard"
        )
        predicted = _predict_nextvals(
            self.env, [seq._pg_sequence_name() for seq in standard]
        )
        standard_ids = set(standard._ids)
        for seq in self:
            if not seq.id:
                seq.number_next_actual = 0
            elif seq.id not in standard_ids:
                seq.number_next_actual = seq.number_next
            else:
                seq.number_next_actual = predicted.get(
                    seq._pg_sequence_name(), seq.number_next
                )

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

    _positive_increment = models.Constraint(
        "CHECK (number_increment > 0)",
        "The sequence step must be strictly positive.",
    )
    _non_negative_padding = models.Constraint(
        "CHECK (padding >= 0)",
        "The sequence size cannot be negative.",
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        seqs = super().create(vals_list)
        for seq in seqs:
            if seq.implementation == "standard":
                _create_sequence(
                    self.env.cr,
                    seq._pg_sequence_name(),
                    seq.number_increment,
                    seq.number_next if seq.number_next is not None else 1,
                )
        return seqs

    def unlink(self) -> bool:
        _drop_sequences(self.env.cr, [x._pg_sequence_name() for x in self])
        return super().unlink()

    def write(self, vals: dict[str, Any]) -> bool:
        previous = {seq.id: (seq.implementation, seq.number_increment) for seq in self}
        res = super().write(vals)
        self.flush_model(vals.keys())
        for seq in self:
            previous_implementation, previous_increment = previous[seq.id]
            was_standard = previous_implementation == "standard"
            is_standard = seq.implementation == "standard"
            if was_standard and is_standard:
                if "number_next" in vals:
                    _alter_sequence(
                        self.env.cr,
                        seq._pg_sequence_name(),
                        number_next=seq.number_next,
                    )
                if previous_increment != seq.number_increment:
                    _alter_sequence(
                        self.env.cr,
                        seq._pg_sequence_name(),
                        number_increment=seq.number_increment,
                    )
                    seq.date_range_ids._alter_sequence(
                        number_increment=seq.number_increment
                    )
            elif was_standard:
                if "number_next" not in vals and "number_next_actual" not in vals:
                    seq._carry_over_pg_counters()
                _drop_sequences(
                    self.env.cr,
                    [
                        seq._pg_sequence_name(),
                        *(s._pg_sequence_name() for s in seq.date_range_ids),
                    ],
                )
            elif is_standard:
                _create_sequence(
                    self.env.cr,
                    seq._pg_sequence_name(),
                    seq.number_increment,
                    seq.number_next,
                )
                for sub_seq in seq.date_range_ids:
                    _create_sequence(
                        self.env.cr,
                        sub_seq._pg_sequence_name(),
                        seq.number_increment,
                        sub_seq.number_next,
                    )
        return res

    def _carry_over_pg_counters(self) -> None:
        self.ensure_one()
        sub_seqs = self.date_range_ids
        predicted = _predict_nextvals(
            self.env,
            [
                self._pg_sequence_name(),
                *(sub_seq._pg_sequence_name() for sub_seq in sub_seqs),
            ],
        )
        self.flush_recordset(["number_next"])
        self.env.cr.execute(
            SQL(
                "UPDATE %s SET number_next=%s WHERE id=%s",
                SQL.identifier(self._table),
                predicted.get(self._pg_sequence_name(), self.number_next),
                self.id,
            )
        )
        self.invalidate_recordset(["number_next", "number_next_actual"])
        if not sub_seqs:
            return
        sub_seqs.flush_recordset(["number_next"])
        self.env.cr.execute(
            SQL(
                "UPDATE %s t SET number_next = v.number_next"
                " FROM unnest(%s::int[], %s::int[])"
                " AS v(id, number_next)"
                " WHERE t.id = v.id",
                SQL.identifier(sub_seqs._table),
                sub_seqs.ids,
                [
                    predicted.get(sub_seq._pg_sequence_name(), sub_seq.number_next)
                    for sub_seq in sub_seqs
                ],
            )
        )
        sub_seqs.invalidate_recordset(["number_next", "number_next_actual"])

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

    @api.model
    def _get_pattern_placeholders(self) -> dict[str, str]:
        """Placeholder name -> regex for what interpolating it can emit.

        Override to declare placeholders a caller substitutes itself, on top of
        the date ones every sequence understands.
        """
        return dict(_INTERPOLATION_REGEXES)

    @api.model
    def _pattern_to_regex(self, pattern: str) -> str:
        """Compile a prefix/suffix pattern into an anchored regex with named groups.

        `_get_prefix_suffix` runs a pattern forward, turning `%(year)s` into a
        year. This runs it backward, so a string the pattern could have produced
        can be recognised and taken apart again — which is what validating a
        user-typed reference, or recovering the date encoded in one, needs.

        A placeholder used twice becomes a backreference rather than a second
        group: one interpolation cannot yield two different values, so a string
        where the two copies disagree is not one this pattern produced.

        :param str pattern: pattern in `%(name)s` form, as `prefix`/`suffix` hold
        :return: anchored regex, one named group per distinct placeholder
        :rtype: str
        :raises ValueError: if the pattern names a placeholder with no regex
        """
        placeholders = self._get_pattern_placeholders()
        parts = ["^"]
        seen = set()
        position = 0
        for match in _PLACEHOLDER_RE.finditer(pattern):
            parts.append(re.escape(pattern[position : match.start()]))
            name = match.group(1)
            if name not in placeholders:
                raise ValueError(
                    f"Unknown placeholder %({name})s: expected one of "
                    f"{', '.join(sorted(placeholders))}"
                )
            if name in seen:
                parts.append(f"(?P={name})")
            else:
                seen.add(name)
                parts.append(f"(?P<{name}>{placeholders[name]})")
            position = match.end()
        parts.append(re.escape(pattern[position:]))
        parts.append("$")
        return "".join(parts)

    def _create_date_range_seq(self, date: Any) -> Any:
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
        date_range, _created = insert_or_existing(
            self.env.cr,
            lambda: seq_date_range.create(
                {
                    "date_from": date_from,
                    "date_to": date_to,
                    "sequence_id": self.id,
                }
            ),
            lambda: seq_date_range.search(
                [
                    ("sequence_id", "=", self.id),
                    ("date_from", "<=", date),
                    ("date_to", ">=", date),
                ],
                limit=1,
            ),
            conflict=f"ir.sequence {self.id} date range {date_from}..{date_to}",
        )
        return date_range

    def _get_current_sequence(self, sequence_date: Any = None) -> Any:
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
        self.browse().check_access("read")
        return self._next(sequence_date=sequence_date)

    def preview_next(self, sequence_date: Any = None) -> str:
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
        self.browse().check_access("read")
        company_id = self.env.company.id
        seq_ids = self.search(
            [
                ("code", "=", sequence_code),
                ("company_id", "in", [company_id, False]),
            ],
            order="company_id, id",
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
        return "ir_sequence_%03d_%03d" % (self.sequence_id.id, self.id)

    @api.depends("number_next", "sequence_id.implementation")
    def _get_number_next_actual(self) -> None:
        standard = self.filtered(
            lambda seq: seq.id and seq.sequence_id.implementation == "standard"
        )
        predicted = _predict_nextvals(
            self.env, [seq._pg_sequence_name() for seq in standard]
        )
        standard_ids = set(standard._ids)
        for seq in self:
            if seq.id not in standard_ids:
                seq.number_next_actual = seq.number_next
            else:
                seq.number_next_actual = predicted.get(
                    seq._pg_sequence_name(), seq.number_next
                )

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
        for seq in self:
            _alter_sequence(
                self.env.cr,
                seq._pg_sequence_name(),
                number_increment=number_increment,
                number_next=number_next,
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
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
