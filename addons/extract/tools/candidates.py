from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import Schema


@dataclass(frozen=True)
class Candidate:
    value: Any
    source: str
    confidence: float = 0.5


class FieldResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.candidates: list[Candidate] = []

    def add(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)
        self.candidates.sort(key=lambda c: c.confidence, reverse=True)

    @property
    def selected(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def value(self) -> Any:
        return self.selected.value if self.selected else None

    @property
    def source(self) -> str:
        return self.selected.source if self.selected else ""

    @property
    def confidence(self) -> float:
        return self.selected.confidence if self.selected else 0.0

    @property
    def disputed(self) -> bool:
        if len(self.candidates) < 2:
            return False
        first = self.candidates[0].value
        return any(other.value != first for other in self.candidates[1:])

    def __repr__(self) -> str:
        return f"<FieldResult {self.name}={self.value!r} from {self.source!r}>"


class ExtractionResult:
    def __init__(self, schema: Schema) -> None:
        self.schema = schema
        self.fields: dict[str, FieldResult] = {}
        self.ran: list[str] = []
        self.pending: dict[str, Any] | None = None

    def add(self, name: str, value: Any, source: str, confidence: float) -> None:
        if value is None:
            return
        spec = self.schema.fields.get(name)
        if spec is not None:
            try:
                value = spec.coerce(value)
            except TypeError, ValueError:
                return
            if value is None:
                return
        self.fields.setdefault(name, FieldResult(name)).add(
            Candidate(value=value, source=source, confidence=confidence)
        )

    def flat(self) -> dict[str, Any]:
        return {name: result.value for name, result in self.fields.items()}

    @property
    def missing(self) -> tuple[str, ...]:
        return self.schema.missing(self.flat())

    @property
    def violations(self) -> tuple[str, ...]:
        return self.schema.violations(self.flat())

    @property
    def satisfied(self) -> bool:
        return not self.missing and not self.violations

    @property
    def disputed(self) -> tuple[str, ...]:
        return tuple(n for n, result in self.fields.items() if result.disputed)

    def __getitem__(self, name: str) -> FieldResult:
        return self.fields[name]

    def __contains__(self, name: str) -> bool:
        return name in self.fields

    @property
    def waiting(self) -> bool:
        return self.pending is not None

    def __repr__(self) -> str:
        if self.waiting:
            state = f"waiting on {self.pending['strategy']}"
        elif self.satisfied:
            state = "satisfied"
        else:
            state = f"missing={list(self.missing)}"
        return f"<ExtractionResult {self.schema.name} {state} via {self.ran}>"
