from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "BARCODES",
    "DATA",
    "IMAGES",
    "REPRESENTATIONS",
    "ROWS",
    "TEXT",
    "TREE",
    "BaseReader",
    "get_readers",
    "known_readers",
    "register_reader",
]

ROWS = "rows"
TEXT = "text"
TREE = "tree"
DATA = "data"
IMAGES = "images"
BARCODES = "barcodes"

REPRESENTATIONS = (ROWS, TEXT, TREE, DATA, IMAGES, BARCODES)

ANY = "*"


@runtime_checkable
class Reader(Protocol):
    name: str
    mimetypes: frozenset[str]
    yields: tuple[str, ...]

    def read(self, document: Any) -> Any: ...


class BaseReader:
    name: str = ""
    mimetypes: frozenset[str] = frozenset()
    yields: tuple[str, ...] = ()

    def read(self, document: Any) -> Any:
        raise NotImplementedError

    def applies_to(self, mimetype: str) -> bool:
        return ANY in self.mimetypes or mimetype in self.mimetypes

    def provides(self, document: Any) -> bool | None:
        _ = document
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


_READERS: dict[str, list[BaseReader]] = {name: [] for name in REPRESENTATIONS}


def register_reader(reader: BaseReader) -> BaseReader:
    if not reader.name:
        raise ValueError(f"{reader!r} must name itself")
    if not reader.yields:
        raise ValueError(f"Reader {reader.name!r} yields no representation")
    unknown = set(reader.yields) - set(REPRESENTATIONS)
    if unknown:
        raise ValueError(
            f"Reader {reader.name!r} yields unknown representation(s) "
            f"{', '.join(sorted(unknown))}; expected one of "
            f"{', '.join(REPRESENTATIONS)}"
        )
    if not reader.mimetypes:
        raise ValueError(f"Reader {reader.name!r} accepts no mimetype")
    for representation in reader.yields:
        _READERS[representation].append(reader)
    return reader


def get_readers(mimetype: str, representation: str) -> tuple[BaseReader, ...]:
    if representation not in _READERS:
        raise ValueError(f"Unknown representation {representation!r}")
    named, fallback = [], []
    for reader in _READERS[representation]:
        if ANY in reader.mimetypes:
            if reader.applies_to(mimetype):
                fallback.append(reader)
        elif reader.applies_to(mimetype):
            named.append(reader)
    return (*named, *fallback)


def known_readers() -> tuple[str, ...]:
    """Every registered reader, once, by name."""
    seen: dict[str, None] = {}
    for readers in _READERS.values():
        for reader in readers:
            seen.setdefault(reader.name, None)
    return tuple(sorted(seen))


def _reader(
    name: str,
    mimetypes: frozenset[str],
    yields: tuple[str, ...],
    read: Callable[..., Any],
) -> BaseReader:
    reader = BaseReader()
    reader.name = name
    reader.mimetypes = mimetypes
    reader.yields = yields
    reader.read = read  # type: ignore[method-assign]
    return reader


_XML_MIMETYPES = frozenset({"application/xml", "text/xml", "application/xhtml+xml"})
_JSON_MIMETYPES = frozenset({"application/json", "text/json"})
_CSV_MIMETYPES = frozenset({"text/csv", "text/plain", "application/csv"})


def _read_tree(document: Any) -> Any:
    from lxml import etree

    return etree.fromstring(
        document.data,
        parser=etree.XMLParser(
            remove_comments=True, resolve_entities=False, decompress=False
        ),
    )


def _read_data(document: Any) -> Any:
    return json.loads(document.data)


def _read_csv_rows(document: Any) -> list[list[str]]:
    from .guess import decode

    options = document.options
    separator = options.get("separator") or ","
    quoting = options.get("quoting") or '"'
    try:
        text = decode(document.data)
    except UnicodeDecodeError:
        return []
    reader = csv.reader(io.StringIO(text), delimiter=separator, quotechar=quoting)
    return [list(row) for row in reader]


register_reader(_reader("xml", _XML_MIMETYPES, (TREE,), _read_tree))
register_reader(_reader("json", _JSON_MIMETYPES, (DATA,), _read_data))
register_reader(_reader("csv", _CSV_MIMETYPES, (ROWS,), _read_csv_rows))
