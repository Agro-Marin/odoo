"""What each strategy proposed, and which proposal won.

A flat dict of extracted values loses the two questions that matter once more
than one strategy can answer: where did this value come from, and what did the
others say. Odoo's own extraction service already answers per field rather than
per document, so keeping candidates is also what lets it be wrapped as one
strategy among several rather than a parallel pipeline.

The concrete payoff is per-field escalation. A structured parse that yields
nine fields of eleven no longer forces the whole document to an expensive
strategy: the nine are kept, and only the two that are missing -- or the ones
whose rules do not hold -- are asked again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import Schema


@dataclass(frozen=True)
class Candidate:
    """One strategy's answer for one field."""

    value: Any
    source: str
    confidence: float = 0.5


class FieldResult:
    """Every answer for one field, best first."""

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
        """Whether strategies proposed different values for this field.

        Compared rather than hashed. A schema field may be a list or a dict --
        an invoice's lines, a bill's meter registers -- and putting those in a
        set raises rather than answering, which is a failure of this property
        and not of the document.
        """
        if len(self.candidates) < 2:
            return False
        first = self.candidates[0].value
        return any(other.value != first for other in self.candidates[1:])

    def __repr__(self) -> str:
        return f"<FieldResult {self.name}={self.value!r} from {self.source!r}>"


class ExtractionResult:
    """The document's fields, with provenance, measured against its schema."""

    def __init__(self, schema: Schema) -> None:
        self.schema = schema
        self.fields: dict[str, FieldResult] = {}
        self.ran: list[str] = []
        # Set when a strategy has been asked and has not answered yet. The
        # caller is expected to come back with it rather than start again --
        # a service that takes a minute must not be asked twice for the same
        # document, and its handle is the only thing that prevents that.
        self.pending: dict[str, Any] | None = None

    def add(self, name: str, value: Any, source: str, confidence: float) -> None:
        """Record one strategy's answer.

        A value the schema does not declare is kept rather than dropped: a
        strategy that reads more than the schema knows about is a reason to
        extend the schema, and discarding it silently is how that never
        happens. A value of the wrong type is dropped, because a string where
        a total belongs is not information.
        """
        if value is None:
            return
        spec = self.schema.fields.get(name)
        if spec is not None and not spec.accepts(value):
            return
        self.fields.setdefault(name, FieldResult(name)).add(
            Candidate(value=value, source=source, confidence=confidence)
        )

    def flat(self) -> dict[str, Any]:
        """The selected values, for a consumer that wants a plain dict."""
        return {name: result.value for name, result in self.fields.items()}

    @property
    def missing(self) -> tuple[str, ...]:
        """Required fields nobody produced."""
        return self.schema.missing(self.flat())

    @property
    def violations(self) -> tuple[str, ...]:
        """Consistency rules that do not hold."""
        return self.schema.violations(self.flat())

    @property
    def satisfied(self) -> bool:
        """Whether the document is complete and coherent.

        Not "did a strategy return something" -- that question was measured
        answering yes for a bill that had lost its entire money block.
        """
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
        """Whether a strategy was asked and has not answered yet."""
        return self.pending is not None

    def __repr__(self) -> str:
        if self.waiting:
            state = f"waiting on {self.pending['strategy']}"
        elif self.satisfied:
            state = "satisfied"
        else:
            state = f"missing={list(self.missing)}"
        return f"<ExtractionResult {self.schema.name} {state} via {self.ran}>"
