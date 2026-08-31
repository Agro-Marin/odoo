from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .format import from_value

__all__ = [
    "ALIGNMENTS",
    "LEFT",
    "RIGHT",
    "Field",
    "Layout",
]

LEFT = "left"
RIGHT = "right"

ALIGNMENTS = (LEFT, RIGHT)


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    width: int
    align: str = LEFT
    pad: str = " "
    constant: str = ""
    render: Callable[[Any], str] | None = None
    parse: Callable[[str], Any] | None = None
    truncate: bool = False
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError(f"Field {self.name!r} must have a positive width")
        if self.align not in ALIGNMENTS:
            raise ValueError(
                f"Field {self.name!r} has unknown alignment {self.align!r}; "
                f"expected one of {ALIGNMENTS}"
            )
        if len(self.pad) != 1:
            raise ValueError(f"Field {self.name!r} needs a single padding character")
        if self.constant and len(self.constant) > self.width:
            raise ValueError(
                f"Field {self.name!r} has a constant of {len(self.constant)} "
                f"characters and a width of {self.width}"
            )

    def render_value(self, value: Any) -> str:
        if self.constant:
            text = self.constant
        elif self.render is not None:
            text = self.render(value)
        else:
            text = from_value(value, **dict(self.options))
        if len(text) > self.width:
            if not self.truncate:
                raise ValueError(
                    f"Field {self.name!r} is {self.width} characters wide and "
                    f"{text!r} is {len(text)}"
                )
            text = text[: self.width] if self.align == LEFT else text[-self.width :]
        if self.align == RIGHT:
            return text.rjust(self.width, self.pad)
        return text.ljust(self.width, self.pad)

    def parse_value(self, text: str) -> Any:
        stripped = (
            text.rstrip(self.pad) if self.align == LEFT else text.lstrip(self.pad)
        )
        if self.parse is not None:
            return self.parse(stripped)
        return stripped


@dataclass(frozen=True, slots=True)
class Layout:
    fields: tuple[Field, ...]

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("A layout needs at least one field")
        seen: set[str] = set()
        for item in self.fields:
            if item.name in seen:
                raise ValueError(f"Layout names {item.name!r} twice")
            seen.add(item.name)

    @property
    def width(self) -> int:
        return sum(item.width for item in self.fields)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    def render(self, values: Mapping[str, Any]) -> str:
        return "".join(item.render_value(values.get(item.name)) for item in self.fields)

    def render_all(
        self, records: Iterable[Mapping[str, Any]], terminator: str = "\r\n"
    ) -> str:
        return "".join(f"{self.render(record)}{terminator}" for record in records)

    def parse(self, line: str) -> dict[str, Any]:
        # A short line is a defect in the file, not something to pad over: a
        # record that stops early means every column after the truncation is
        # read from the wrong offset, and silently returning blanks for them is
        # how a wrong amount reaches a record.
        if len(line) < self.width:
            raise ValueError(
                f"Line is {len(line)} characters and the layout is {self.width}"
            )
        parsed: dict[str, Any] = {}
        at = 0
        for item in self.fields:
            parsed[item.name] = item.parse_value(line[at : at + item.width])
            at += item.width
        return parsed
