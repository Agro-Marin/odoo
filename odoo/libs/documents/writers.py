from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from .format import from_value
from .formats import mimetype_for
from .representations import ANY, CUES, DATA, REPRESENTATIONS, ROWS, TEXT, TREE

__all__ = [
    "BaseWriter",
    "get_writers",
    "known_writers",
    "register_writer",
    "registered_writers",
    "unregister_writer",
]


@runtime_checkable
class Writer(Protocol):
    name: str
    mimetype: str
    consumes: str

    def write(self, value: Any, **options: Any) -> bytes: ...


class BaseWriter:
    name: str = ""
    mimetype: str = ""
    consumes: str = ""

    def write(self, value: Any, **options: Any) -> bytes:
        raise NotImplementedError

    def applies_to(self, mimetype: str) -> bool:
        return self.mimetype in (ANY, mimetype)

    def accepts(self, value: Any) -> bool | None:
        _ = value
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


_WRITERS: dict[str, list[BaseWriter]] = {name: [] for name in REPRESENTATIONS}


def register_writer(writer: BaseWriter) -> BaseWriter:
    if not writer.name:
        raise ValueError(f"{writer!r} must name itself")
    if writer.consumes not in REPRESENTATIONS:
        raise ValueError(
            f"Writer {writer.name!r} consumes unknown representation "
            f"{writer.consumes!r}; expected one of {', '.join(REPRESENTATIONS)}"
        )
    if not writer.mimetype:
        raise ValueError(f"Writer {writer.name!r} emits no mimetype")
    _WRITERS[writer.consumes].append(writer)
    return writer


def unregister_writer(writer: BaseWriter) -> None:
    for writers in _WRITERS.values():
        while writer in writers:
            writers.remove(writer)


def get_writers(mimetype: str, representation: str) -> tuple[BaseWriter, ...]:
    if representation not in _WRITERS:
        raise ValueError(f"Unknown representation {representation!r}")
    named, fallback = [], []
    for writer in _WRITERS[representation]:
        if writer.mimetype == ANY:
            fallback.append(writer)
        elif writer.applies_to(mimetype):
            named.append(writer)
    return (*named, *fallback)


def registered_writers() -> tuple[BaseWriter, ...]:
    """Every registered writer object, once, in registration order."""
    seen: dict[int, BaseWriter] = {}
    for writers in _WRITERS.values():
        for writer in writers:
            seen.setdefault(id(writer), writer)
    return tuple(seen.values())


def known_writers() -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for writers in _WRITERS.values():
        for writer in writers:
            seen.setdefault(writer.name, None)
    return tuple(sorted(seen))


def _writer(
    name: str,
    mimetype: str,
    consumes: str,
    write: Callable[..., bytes],
) -> BaseWriter:
    writer = BaseWriter()
    writer.name = name
    writer.mimetype = mimetype
    writer.consumes = consumes
    writer.write = write  # type: ignore[method-assign]
    return writer


def _write_csv(value: Any, **options: Any) -> bytes:
    separator = options.get("separator") or ","
    quoting = options.get("quoting") or '"'
    encoding = options.get("encoding") or "utf-8"
    buffer = io.StringIO()
    # `\r\n` is what RFC 4180 specifies and what `csv.writer` defaults to; it is
    # named rather than defaulted so a caller writing for a system that rejects
    # it has one option to set instead of a post-processing pass.
    writer = csv.writer(
        buffer,
        delimiter=separator,
        quotechar=quoting,
        lineterminator=options.get("lineterminator") or "\r\n",
    )
    cells = options.get("cells") or {}
    for row in value:
        writer.writerow([from_value(cell, **cells) for cell in row])
    return buffer.getvalue().encode(encoding)


def _write_json(value: Any, **options: Any) -> bytes:
    encoding = options.get("encoding") or "utf-8"
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=options.get("indent"),
        sort_keys=bool(options.get("sort_keys")),
        default=str,
    ).encode(encoding)


def _write_tree(value: Any, **options: Any) -> bytes:
    from lxml import etree

    return etree.tostring(
        value,
        xml_declaration=options.get("xml_declaration", True),
        encoding=options.get("encoding") or "utf-8",
        pretty_print=bool(options.get("pretty_print")),
    )


def _write_text(value: Any, **options: Any) -> bytes:
    return str(value).encode(options.get("encoding") or "utf-8")


def _write_vtt(value: Any, **options: Any) -> bytes:
    from .cues import write_vtt

    return write_vtt(value).encode(options.get("encoding") or "utf-8")


def _write_srt(value: Any, **options: Any) -> bytes:
    from .cues import write_srt

    return write_srt(value).encode(options.get("encoding") or "utf-8")


register_writer(_writer("csv", mimetype_for("csv"), ROWS, _write_csv))
register_writer(_writer("json", mimetype_for("json"), DATA, _write_json))
register_writer(_writer("xml", mimetype_for("xml"), TREE, _write_tree))
register_writer(_writer("text", ANY, TEXT, _write_text))
register_writer(_writer("vtt", mimetype_for("vtt"), CUES, _write_vtt))
register_writer(_writer("srt", mimetype_for("srt"), CUES, _write_srt))
