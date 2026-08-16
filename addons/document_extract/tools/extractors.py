"""Strategies, and what each one needs before it is worth running.

A strategy declares three things: which document types it can read, which
representations it needs, and what it costs. The framework uses all three, so
that no strategy has to re-derive whether it applies -- an XML parser handed a
scanned photograph is a bug the registry should prevent, not one each parser
should defend against.

Cost is the ordering. A signed XML source answers for free and is
authoritative; a metered service and a generative model answer at a price. The
cascade spends in that order and stops when the schema is satisfied, which is
what makes "never pay to read a document that carries its own data" a property
of the framework rather than a convention.

Two shapes are allowed, because a service that answers later cannot be
expressed as one that answers now. A synchronous strategy implements
``extract``. A two-phase one implements ``submit`` and ``poll``, and is
reachable only from the background queue, where a pending answer becomes a
deferral rather than a blocked transaction.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from .source import DocumentSource

_logger = logging.getLogger(__name__)

FREE = 0
CHEAP = 10
METERED = 20
GENERATIVE = 30

COST_NAMES = {
    FREE: "free",
    CHEAP: "cheap",
    METERED: "metered",
    GENERATIVE: "generative",
}

PENDING = object()


@runtime_checkable
class Extractor(Protocol):
    name: str
    doc_types: tuple[str, ...]
    needs: tuple[str, ...]
    cost: int
    confidence: float


class BaseExtractor:
    """Convenience base. Implementing the protocol directly is equally valid."""

    name: str = ""
    doc_types: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    cost: int = GENERATIVE
    confidence: float = 0.5

    def extract(
        self,
        source: DocumentSource,
        doc_type: str,
        wanted: tuple[str, ...],
        env: Any = None,
    ) -> dict[str, Any] | None:
        """Return field values, or None when this document is not one of ours.

        ``wanted`` names the fields still missing or disputed. A strategy may
        answer only those -- a generative one should, since that is where the
        cost is -- or answer everything it reads and let the framework keep
        what it needed.

        ``env`` is the Odoo environment, or None when the caller had none. A
        parser reading bytes ignores it; anything reaching a service needs it
        for the company's credentials and configuration, which is most
        strategies that cost money. Passing it is what keeps those strategies
        registrable objects rather than a second mechanism beside this one.
        """
        raise NotImplementedError

    def applies_to(self, source: DocumentSource, doc_type: str) -> bool:
        return doc_type in self.doc_types and all(
            source.provides(need) for need in self.needs
        )


_EXTRACTORS: dict[str, BaseExtractor] = {}


def register_extractor(extractor: BaseExtractor) -> BaseExtractor:
    """Register a strategy. Raises if the name is taken."""
    if not extractor.name:
        raise ValueError("An extractor needs a name")
    if not extractor.doc_types:
        raise ValueError(f"Extractor {extractor.name!r} declares no document types")
    for need in extractor.needs:
        if need not in ("text", "images", "tree", "data", "barcodes"):
            raise ValueError(
                f"Extractor {extractor.name!r} needs unknown representation {need!r}"
            )
    if extractor.name in _EXTRACTORS:
        raise ValueError(
            f"Extractor {extractor.name!r} is already registered by "
            f"{type(_EXTRACTORS[extractor.name]).__module__}"
        )
    _EXTRACTORS[extractor.name] = extractor
    return extractor


def get_extractors(
    source: DocumentSource | None = None,
    doc_type: str | None = None,
    up_to: int = GENERATIVE,
) -> list[BaseExtractor]:
    """The applicable strategies, cheapest first, most confident first within a cost."""
    found = [e for e in _EXTRACTORS.values() if e.cost <= up_to]
    if doc_type is not None:
        found = [e for e in found if doc_type in e.doc_types]
    if source is not None:
        found = [e for e in found if e.applies_to(source, doc_type or "")]
    return sorted(found, key=lambda e: (e.cost, -e.confidence, e.name))


def known_extractors() -> tuple[str, ...]:
    return tuple(sorted(_EXTRACTORS))
