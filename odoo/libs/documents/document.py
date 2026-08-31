from __future__ import annotations

import base64
import logging
from typing import Any

from .guess import decode, guess_mimetype, looks_like_text
from .readers import (
    BARCODES,
    DATA,
    IMAGES,
    REPRESENTATIONS,
    ROWS,
    TEXT,
    TREE,
    get_readers,
)
from .writers import get_writers, known_writers

__all__ = [
    "TEXT_MAX_CHARS",
    "Document",
]

_logger = logging.getLogger(__name__)

# What one document may hold in memory as text, and hand to a strategy. The
# derivations this replaces clamped every branch; the limit is a property of
# holding a whole document's text at once, not of any one format.
TEXT_MAX_CHARS = 60_000

_DEFAULT_MIMETYPES = {
    ROWS: "text/csv",
    TEXT: "text/plain",
    TREE: "application/xml",
    DATA: "application/json",
}


def _clamp(text: str, name: str) -> str:
    if len(text) <= TEXT_MAX_CHARS:
        return text
    _logger.warning(
        "%r yields %d characters of text; using the first %d and dropping %d",
        name,
        len(text),
        TEXT_MAX_CHARS,
        len(text) - TEXT_MAX_CHARS,
    )
    return text[:TEXT_MAX_CHARS]


class Document:
    """Bytes, what they are, and what can be derived from them."""

    def __init__(
        self,
        data: bytes,
        mimetype: str = "",
        name: str = "",
        **options: Any,
    ) -> None:
        if not data:
            raise ValueError("A document needs data.")
        self.data: bytes = data
        self.name: str = name
        self.mimetype: str = guess_mimetype(data, mimetype)
        self.options: dict[str, Any] = options
        self._derived: dict[str, Any] = {}

    @classmethod
    def of_bytes(
        cls, data: bytes | str, mimetype: str = "", name: str = "", **options: Any
    ) -> Document:
        """A document from raw or base64 bytes."""
        if isinstance(data, str):
            raw = data.split(",", 1)[1] if data.startswith("data:") else data
            data = base64.b64decode(raw)
        return cls(data, mimetype, name, **options)

    @classmethod
    def of(
        cls,
        *,
        rows: Any = None,
        text: Any = None,
        tree: Any = None,
        data: Any = None,
        mimetype: str = "",
        name: str = "",
        **options: Any,
    ) -> Document:
        """A document from a representation, written by a registered writer.

        The inverse of reading: the representation a caller holds becomes the
        bytes a format states it as. ``images`` and ``barcodes`` are absent
        because neither is a statement of a whole document -- they are things a
        document happens to contain.
        """
        given = {
            ROWS: rows,
            TEXT: text,
            TREE: tree,
            DATA: data,
        }
        named = [rep for rep, value in given.items() if value is not None]
        if len(named) != 1:
            raise ValueError(
                "A document is written from exactly one representation; got "
                f"{', '.join(named) if named else 'none'}"
            )
        representation = named[0]
        value = given[representation]
        mimetype = mimetype or _DEFAULT_MIMETYPES[representation]
        writers = get_writers(mimetype, representation)
        if not writers:
            raise ValueError(
                f"Nothing writes {representation} as {mimetype!r}; "
                f"registered: {', '.join(known_writers()) or 'none'}"
            )
        written = writers[0].write(value, **options)
        document = cls(written, mimetype, name, **options)
        # Seeded rather than re-derived: the caller's own object is what the
        # document is of, and reading it back would return a copy that has been
        # through a serializer -- a date that left as a date returning as a str.
        document._derived[representation] = value
        return document

    # -- representations ----------------------------------------------

    @property
    def rows(self) -> list[list[Any]]:
        return self._derive(ROWS) or []

    @property
    def text(self) -> str:
        if TEXT not in self._derived:
            derived = self._derive(TEXT)
            if derived is None and not get_readers(self.mimetype, TEXT):
                # Nobody claims this mimetype for text, so decoding the bytes is
                # the whole of what a reader would have done. Gated on the
                # registry rather than on `text/*`: a mimetype is a guess, and
                # gating on it lost the text of anything the guess got slightly
                # wrong -- `application/csv`, or a note libmagic could not place.
                # A format that does have a reader is left to it, so PDF bytes
                # are never decoded into mojibake.
                try:
                    decoded = decode(self.data)
                except UnicodeDecodeError as e:
                    _logger.info("Could not decode %r: %s", self.name, e)
                    decoded = ""
                derived = decoded if looks_like_text(decoded) else ""
                self._derived[TEXT] = _clamp(derived, self.name)
        return self._derived.get(TEXT) or ""

    @property
    def tree(self) -> Any:
        return self._derive(TREE)

    @property
    def data_dict(self) -> dict | list | None:
        return self._derive(DATA)

    @property
    def images(self) -> list[bytes]:
        return self._derive(IMAGES) or []

    @property
    def barcodes(self) -> list[str]:
        return self._derive(BARCODES) or []

    def provides(self, representation: str) -> bool:
        """Whether this document can supply a representation, non-empty.

        ``tree`` is answered with ``is not None`` rather than truthiness: an
        lxml element with no children is falsy, and a root element on its own is
        the shape a small EDI payload takes.
        """
        if representation not in REPRESENTATIONS:
            raise ValueError(f"Unknown representation {representation!r}")
        cheap = [
            answer
            for reader in get_readers(self.mimetype, representation)
            if (answer := reader.provides(self)) is not None
        ]
        if cheap:
            return any(cheap)
        if representation == TREE:
            return self.tree is not None
        return bool(
            getattr(self, "data_dict" if representation == DATA else representation)
        )

    # -- deriving ------------------------------------------------------

    def _derive(self, representation: str) -> Any:
        """The representation, read once and kept -- ``None`` if nobody can.

        A reader that raises is not fatal: another may still succeed, and a
        document that cannot be read one way is not a document that cannot be
        read. The first non-``None`` answer wins.
        """
        if representation in self._derived:
            return self._derived[representation]
        value = None
        clamp = representation == TEXT
        for reader in get_readers(self.mimetype, representation):
            try:
                value = reader.read(self)
            except Exception as e:
                _logger.info(
                    "Reader %s could not derive %s from %r: %s",
                    reader.name,
                    representation,
                    self.name or self.mimetype,
                    e,
                )
                continue
            if value is not None:
                break
        if clamp and value:
            # Clamped where it is stored, not where it is read: a reader's
            # output is held for the life of the document, and clamping on the
            # way out would bound what a caller sees while the whole of it
            # stayed in memory -- and would log the same warning per access.
            value = _clamp(value, self.name)
        self._derived[representation] = value
        return value

    def __repr__(self) -> str:
        return f"<Document {self.name or '?'} {self.mimetype} {len(self.data)}B>"
