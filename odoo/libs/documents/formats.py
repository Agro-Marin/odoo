from __future__ import annotations

from dataclasses import dataclass, field

from .readers import REPRESENTATIONS

__all__ = [
    "Format",
    "extension_for",
    "get_format",
    "get_format_of_extension",
    "known_formats",
    "mimetype_for",
    "register_extension",
    "register_format",
]


@dataclass(frozen=True, slots=True)
class Format:
    mimetype: str
    extension: str
    representation: str
    accepts: frozenset[str] = field(default_factory=frozenset)
    label: str = ""

    def __repr__(self) -> str:
        return f"<Format {self.extension} {self.mimetype}>"


_FORMATS: list[Format] = []
_BY_MIMETYPE: dict[str, Format] = {}
_BY_EXTENSION: dict[str, Format] = {}
_BY_ALIAS: dict[str, Format] = {}


def register_format(fmt: Format) -> Format:
    if not fmt.mimetype:
        raise ValueError(f"{fmt!r} must name a mimetype")
    if not fmt.extension:
        raise ValueError(f"Format {fmt.mimetype!r} must name an extension")
    if fmt.representation not in REPRESENTATIONS:
        raise ValueError(
            f"Format {fmt.mimetype!r} claims unknown representation "
            f"{fmt.representation!r}; expected one of {', '.join(REPRESENTATIONS)}"
        )
    mimetype = fmt.mimetype.lower()
    extension = fmt.extension.lower().lstrip(".")
    if mimetype in _BY_MIMETYPE:
        raise ValueError(f"{mimetype!r} is already registered")
    if extension in _BY_EXTENSION:
        raise ValueError(f"{extension!r} is already registered")
    _FORMATS.append(fmt)
    _BY_MIMETYPE[mimetype] = fmt
    _BY_EXTENSION[extension] = fmt
    for alias in fmt.accepts:
        # A canonical spelling always wins: `text/csv` and `text/plain` are both
        # read as rows, but only one of them is what `.csv` means and only one of
        # them is what a csv writer emits. Registering the alias over a canonical
        # entry is how `extension_for` starts answering `csv` for a plain note.
        _BY_ALIAS.setdefault(alias.lower(), fmt)
    return fmt


def register_extension(extension: str, mimetype: str) -> Format:
    # One mimetype, several extensions: `.xaf` is a Dutch audit file and
    # `application/xml` is what it is. The localization that produces one says so
    # from its own layer, rather than the format layer having to know every
    # jurisdiction that ever named an XML document after itself.
    extension = (extension or "").lower().lstrip(".")
    fmt = _BY_MIMETYPE.get((mimetype or "").lower())
    if fmt is None:
        raise ValueError(f"No format is registered for {mimetype!r}")
    if not extension:
        raise ValueError(f"An extension for {mimetype!r} cannot be empty")
    registered = _BY_EXTENSION.get(extension)
    if registered is not None and registered is not fmt:
        raise ValueError(
            f"{extension!r} already means {registered.mimetype!r}, not {mimetype!r}"
        )
    _BY_EXTENSION[extension] = fmt
    return fmt


def get_format(mimetype: str) -> Format | None:
    mimetype = (mimetype or "").lower()
    return _BY_MIMETYPE.get(mimetype) or _BY_ALIAS.get(mimetype)


def get_format_of_extension(extension: str) -> Format | None:
    return _BY_EXTENSION.get((extension or "").lower().lstrip("."))


def mimetype_for(extension: str) -> str:
    fmt = get_format_of_extension(extension)
    return fmt.mimetype if fmt else ""


def extension_for(mimetype: str) -> str:
    # Canonical only. An alias answers `get_format` because a document arriving
    # mislabelled still has to be read; it does not answer this, because the
    # name a file is written under is a statement about what it is.
    fmt = _BY_MIMETYPE.get((mimetype or "").lower())
    return fmt.extension if fmt else ""


def known_formats() -> tuple[Format, ...]:
    return tuple(_FORMATS)


register_format(
    Format(
        mimetype="text/csv",
        extension="csv",
        representation="rows",
        accepts=frozenset({"text/plain", "application/csv"}),
        label="Comma-separated values",
    )
)
register_format(
    Format(
        mimetype="application/xml",
        extension="xml",
        representation="tree",
        accepts=frozenset({"text/xml", "application/xhtml+xml"}),
        label="XML",
    )
)
register_format(
    Format(
        mimetype="application/json",
        extension="json",
        representation="data",
        accepts=frozenset({"text/json"}),
        label="JSON",
    )
)
