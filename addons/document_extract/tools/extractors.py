from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from odoo.libs.documents import Document

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
    name: str = ""
    doc_types: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    cost: int = GENERATIVE
    confidence: float = 0.5

    def extract(
        self,
        source: Document,
        doc_type: str,
        wanted: tuple[str, ...],
        env: Any = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    def applies_to(self, source: Document, doc_type: str) -> bool:
        return doc_type in self.doc_types and all(
            source.provides(need) for need in self.needs
        )


_EXTRACTORS: dict[str, BaseExtractor] = {}


def register_extractor(extractor: BaseExtractor) -> BaseExtractor:
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
    source: Document | None = None,
    doc_type: str | None = None,
    up_to: int = GENERATIVE,
) -> list[BaseExtractor]:
    found = [e for e in _EXTRACTORS.values() if e.cost <= up_to]
    if doc_type is not None:
        found = [e for e in found if doc_type in e.doc_types]
    if source is not None:
        found = [e for e in found if e.applies_to(source, doc_type or "")]
    return sorted(found, key=lambda e: (e.cost, -e.confidence, e.name))


def known_extractors() -> tuple[str, ...]:
    return tuple(sorted(_EXTRACTORS))
