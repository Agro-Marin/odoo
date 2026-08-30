from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

QUEUED = "queued"
SENT = "sent"
ACCEPTED = "accepted"
REJECTED = "rejected"
EXPIRED = "expired"

SETTLED_STATES = frozenset({ACCEPTED, REJECTED, EXPIRED})

_STATES = frozenset({QUEUED, SENT, ACCEPTED, REJECTED, EXPIRED})


@dataclass(frozen=True, slots=True)
class Verdict:
    state: str
    reference: str = ""
    message: str = ""
    response: bytes | None = None
    response_name: str = ""
    retry_after: int | None = None
    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in _STATES:
            raise ValueError(
                f"Verdict state {self.state!r} is not one of {sorted(_STATES)}",
            )
        if self.state == REJECTED and not self.message:
            raise ValueError(
                "A rejection carries the counterparty's own words; "
                "Verdict(REJECTED) needs a message",
            )
        if self.retry_after is not None and self.state in SETTLED_STATES:
            raise ValueError(
                f"Verdict({self.state}) is settled and cannot ask to be retried",
            )

    @property
    def is_settled(self) -> bool:
        return self.state in SETTLED_STATES
