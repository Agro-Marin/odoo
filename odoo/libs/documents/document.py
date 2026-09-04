from __future__ import annotations

import base64
import logging
from typing import Any

from odoo.libs.filesystem import guess_mimetype

from .guess import decode, looks_like_text
from .readers import (
    BARCODES,
    CHEAP,
    CUES,
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
    "DEFAULT_READ_UP_TO",
    "TEXT_MAX_CHARS",
    "Document",
    "essential_mimetype",
]

_logger = logging.getLogger(__name__)

# What one document may hold in memory as text, and hand to a strategy. The
# derivations this replaces clamped every branch; the limit is a property of
# holding a whole document's text at once, not of any one format.
TEXT_MAX_CHARS = 60_000

# The dearest reader a document is derived by unless its caller says otherwise.
# Free and cheap readers parse what is already in the bytes; anything above that
# spends real time or real money on a document nobody has yet decided is worth
# it, so it waits to be asked for by name.
DEFAULT_READ_UP_TO = CHEAP

_DEFAULT_MIMETYPES = {
    ROWS: "text/csv",
    TEXT: "text/plain",
    TREE: "application/xml",
    DATA: "application/json",
    CUES: "text/vtt",
}


def essential_mimetype(mimetype: str) -> str:
    """`type/subtype`, with the parameters a transport added stripped off.

    A browser labels a recording `audio/webm;codecs=opus` and an upload can
    carry `;charset=utf-8`, and `ir.attachment.mimetype` stores whatever it was
    told. Every registry here keys on the type and subtype, so a parameter that
    reached a lookup matched nothing: a `.vtt` declared `text/vtt;charset=utf-8`
    found no reader and fell back to decoding its own cue markup as prose.

    RFC 2045 makes the parameters modifiers of the type, not part of it, so this
    is the mimetype's identity rather than a normalisation of convenience.
    """
    return mimetype.split(";", 1)[0].strip().lower()


def _clamp(text: str, name: str, limit: int = TEXT_MAX_CHARS) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    _logger.warning(
        "%r yields %d characters of text; using the first %d and dropping %d",
        name,
        len(text),
        limit,
        len(text) - limit,
    )
    return text[:limit]


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
        self.mimetype: str = essential_mimetype(guess_mimetype(data, declared=mimetype))
        self.options: dict[str, Any] = options
        self._derived: dict[str, Any] = {}
        self._derived_at: dict[str, int] = {}

    @property
    def read_up_to(self) -> int:
        """The dearest reader this document may be derived by.

        Read from the options on each access rather than fixed at construction,
        so a caller that decides mid-flight that a document is worth reading
        properly raises it on the object it already holds and the readers it
        already refused are asked. Named for reading rather than for extraction,
        because a consumer of both sets two ceilings and they are not the same
        question.
        """
        return self.options.get("read_up_to", DEFAULT_READ_UP_TO)

    @property
    def text_max_chars(self) -> int:
        """How much text this document may hold, `0` for no bound.

        `TEXT_MAX_CHARS` is an extraction bound -- what one document may hold in
        memory and hand to a strategy -- and a caller with a budget of its own
        should not inherit it. `ir.attachment._index` is the case that forced
        this: it stores `_get_index_max_chars()`, four times more and settable
        per database, so deriving its text through this layer would have
        truncated the stored index with nothing to say so and no setting able
        to raise it.
        """
        return self.options.get("text_max_chars", TEXT_MAX_CHARS)

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
        cues: Any = None,
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
            CUES: cues,
        }
        named = [rep for rep, value in given.items() if value is not None]
        if len(named) != 1:
            raise ValueError(
                "A document is written from exactly one representation; got "
                f"{', '.join(named) if named else 'none'}"
            )
        representation = named[0]
        value = given[representation]
        mimetype = essential_mimetype(mimetype or _DEFAULT_MIMETYPES[representation])
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
        derived = self._derive(TEXT)
        if derived is None:
            if not get_readers(self.mimetype, TEXT):
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
                self._derived[TEXT] = _clamp(derived, self.name, self.text_max_chars)
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

    @property
    def cues(self) -> list[Any]:
        return self._derive(CUES) or []

    def _is_read(self, representation: str, value: Any) -> bool:
        """Whether an answer counts as having read the document.

        `tree` is answered with `is not None` rather than truthiness: an lxml
        element with no children is falsy, lxml warns it will stop being, and a
        root element on its own is the shape a small EDI payload takes. Every
        other representation is a container, where empty means nothing was read.
        """
        if value is None:
            return False
        return True if representation == TREE else bool(value)

    def provides(self, representation: str) -> bool:
        """Whether this document can supply a representation, non-empty.

        Bounded by `read_up_to`, exactly as deriving is. A probe that answered
        for a reader the ceiling forbids would promise a representation that
        comes back empty -- and `BaseExtractor.applies_to` reads this to decide
        whether to run a strategy, so the promise would be paid for.
        """
        if representation not in REPRESENTATIONS:
            raise ValueError(f"Unknown representation {representation!r}")
        cheap = [
            answer
            for reader in get_readers(self.mimetype, representation)
            if reader.cost <= self.read_up_to
            and (answer := reader.provides(self)) is not None
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
        read. The first non-empty answer wins.

        An empty answer is kept but does not end the search, which is what makes
        `cost` mean anything: a PDF with no text layer costs its free reader
        nothing and then reaches the one that renders and recognises its pages.
        A reader that legitimately has nothing to say and a reader that could not
        read the document are indistinguishable from the outside, so trying the
        next one is the only reading of an empty answer that cannot lose text.
        """
        ceiling = self.read_up_to
        if representation in self._derived:
            cached = self._derived[representation]
            # A cached answer is re-read only when it is empty AND the ceiling
            # has risen since it was taken. `_derive` stops at the first reader
            # that reads something, so a cached non-empty answer is already what
            # a dearer reader would never have been asked for; an empty one may
            # be all the readers under the old ceiling had to say.
            if self._is_read(representation, cached) or ceiling <= self._derived_at.get(
                representation, ceiling
            ):
                return cached
        value = None
        clamp = representation == TEXT
        for reader in get_readers(self.mimetype, representation):
            if reader.cost > ceiling:
                continue
            try:
                answer = reader.read(self)
            except Exception as e:
                _logger.info(
                    "Reader %s could not derive %s from %r: %s",
                    reader.name,
                    representation,
                    self.name or self.mimetype,
                    e,
                )
                continue
            if answer is None:
                continue
            read = self._is_read(representation, answer)
            if value is None or read:
                value = answer
            if read:
                break
        if clamp and value:
            # Clamped where it is stored, not where it is read: a reader's
            # output is held for the life of the document, and clamping on the
            # way out would bound what a caller sees while the whole of it
            # stayed in memory -- and would log the same warning per access.
            value = _clamp(value, self.name, self.text_max_chars)
        self._derived[representation] = value
        self._derived_at[representation] = ceiling
        return value

    def __repr__(self) -> str:
        return f"<Document {self.name or '?'} {self.mimetype} {len(self.data)}B>"
