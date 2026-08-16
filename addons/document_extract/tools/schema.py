"""What a document type is supposed to yield, declared once.

Without this, every producer invents the shape of its own output and every
consumer guesses. That is not hypothetical: a utility bill in this workspace
is stored as a bare JSON column written by three independent parsers with no
declaration between them, which is why the OCR bridge maps three fields and
leaves the rest to a comment.

A schema declares the fields, which of them are required, and the rules that
must hold between them. Both halves matter, because "the extractor returned
something" is not a usable definition of success -- measured on a real bill,
a one-word layout change dropped the subtotal, tax, surcharge and total
together while the parser returned twenty-eight other fields and reported
success. Required fields catch the absence; consistency rules catch the
subtler case where every field is present and they contradict each other.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

TYPES: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "float": (int, float),
    "int": int,
    "bool": bool,
    "date": (datetime.date, str),
    "list": list,
    "dict": dict,
}


@dataclass(frozen=True)
class FieldSpec:
    """One field of a document type."""

    type: str = "str"
    required: bool = False
    help: str = ""

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(
                f"Unknown field type {self.type!r}; expected one of "
                f"{', '.join(sorted(TYPES))}"
            )

    def accepts(self, value: Any) -> bool:
        return value is None or isinstance(value, TYPES[self.type])


@dataclass(frozen=True)
class Rule:
    """A consistency requirement between fields of one document.

    ``check`` receives the flat values and returns True when the document is
    coherent. A rule whose fields are not all present is skipped rather than
    failed: an incomplete extraction is the business of ``required``, and
    reporting it twice would make a missing field look like a contradiction.
    """

    name: str
    fields: tuple[str, ...]
    check: Callable[[dict[str, Any]], bool]
    message: str = ""

    def holds(self, values: dict[str, Any]) -> bool:
        if any(values.get(name) is None for name in self.fields):
            return True
        return bool(self.check(values))


@dataclass(frozen=True)
class Schema:
    name: str
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    rules: tuple[Rule, ...] = ()

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(n for n, spec in self.fields.items() if spec.required)

    def missing(self, values: dict[str, Any]) -> tuple[str, ...]:
        return tuple(n for n in self.required if values.get(n) is None)

    def violations(self, values: dict[str, Any]) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.rules if not rule.holds(values))


_SCHEMAS: dict[str, Schema] = {}


def register_schema(
    name: str,
    fields: dict[str, FieldSpec],
    rules: Iterable[Rule] = (),
) -> Schema:
    """Declare a document type. Raises if it is already declared."""
    if name in _SCHEMAS:
        raise ValueError(f"Schema {name!r} is already registered")
    _SCHEMAS[name] = Schema(name=name, fields=dict(fields), rules=tuple(rules))
    return _SCHEMAS[name]


def extend_schema(
    name: str,
    fields: dict[str, FieldSpec] | None = None,
    rules: Iterable[Rule] = (),
) -> Schema:
    """Add fields or rules to a declared type.

    How a localization adds what only it knows -- a Mexican invoice's fiscal
    UUID, a utility bill's meter number -- without forking the type or
    teaching the core about a country. Redeclaring an existing field is an
    error: two modules disagreeing about what ``total`` means is a bug, and a
    silent last-one-wins would hide it.
    """
    schema = get_schema(name)
    added = dict(fields or {})
    clashing = sorted(set(added) & set(schema.fields))
    if clashing:
        raise ValueError(
            f"Schema {name!r} already declares {', '.join(clashing)}; "
            "extend with new fields or change the declaration"
        )
    _SCHEMAS[name] = replace(
        schema,
        fields={**schema.fields, **added},
        rules=schema.rules + tuple(rules),
    )
    return _SCHEMAS[name]


def get_schema(name: str) -> Schema:
    try:
        return _SCHEMAS[name]
    except KeyError:
        raise ValueError(
            f"Unknown document type {name!r}; registered: "
            f"{', '.join(sorted(_SCHEMAS)) or 'none'}"
        ) from None


def known_schemas() -> tuple[str, ...]:
    return tuple(sorted(_SCHEMAS))


def sums_to(
    name: str, parts: Iterable[str], total: str, tolerance: float = 0.01
) -> Rule:
    """The commonest consistency rule: some fields add up to another."""
    parts = tuple(parts)

    def _check(values: dict[str, Any]) -> bool:
        return abs(sum(values[p] for p in parts) - values[total]) <= tolerance

    return Rule(
        name=name,
        fields=(*parts, total),
        check=_check,
        message=f"{' + '.join(parts)} should equal {total}",
    )


def not_after(name: str, earlier: str, later: str) -> Rule:
    """A date ordering rule, tolerant of dates written as strings."""

    def _check(values: dict[str, Any]) -> bool:
        return str(values[earlier]) <= str(values[later])

    return Rule(
        name=name,
        fields=(earlier, later),
        check=_check,
        message=f"{earlier} should not be after {later}",
    )
