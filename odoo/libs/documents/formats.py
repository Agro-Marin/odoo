from __future__ import annotations

from dataclasses import dataclass, field

from .representations import CUES, DATA, IMAGES, REPRESENTATIONS, ROWS, TEXT, TREE

__all__ = [
    "Format",
    "canonical_mimetypes",
    "extension_for",
    "get_format",
    "get_format_of_extension",
    "known_formats",
    "mimetype_for",
    "mimetypes_for",
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

    @property
    def mimetypes(self) -> frozenset[str]:
        """Every spelling a reader of this format answers to, canonical first."""
        return frozenset({self.mimetype, *self.accepts})

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


def mimetypes_for(*extensions: str) -> frozenset[str]:
    """The mimetypes a reader of these formats claims, aliases included.

    Raises for an extension nobody registered: a reader naming a format the
    table does not hold is the drift this function exists to make impossible,
    and answering an empty set would register a reader that reads nothing.
    """
    claimed: set[str] = set()
    for fmt in _formats_of(extensions):
        claimed |= fmt.mimetypes
    return frozenset(claimed)


def canonical_mimetypes(*extensions: str) -> frozenset[str]:
    """The one mimetype each of these formats is written under, aliases out.

    An allow-list is a statement about what a file *is*, which is the
    canonical spelling; `mimetypes_for` is what a reader *tolerates*. Raises
    for a name nobody registered, for the same reason.
    """
    return frozenset(fmt.mimetype for fmt in _formats_of(extensions))


def _formats_of(extensions: tuple[str, ...]) -> tuple[Format, ...]:
    found = []
    for extension in extensions:
        fmt = get_format_of_extension(extension)
        if fmt is None:
            raise ValueError(f"No format is registered under {extension!r}")
        found.append(fmt)
    return tuple(found)


def known_formats() -> tuple[Format, ...]:
    return tuple(_FORMATS)


_BUILTIN_FORMATS = (
    # (mimetype, extension, representation, accepts, label)
    (
        "text/csv",
        "csv",
        ROWS,
        {"text/plain", "application/csv"},
        "Comma-separated values",
    ),
    ("application/xml", "xml", TREE, {"text/xml", "application/xhtml+xml"}, "XML"),
    ("application/json", "json", DATA, {"text/json"}, "JSON"),
    ("text/vtt", "vtt", CUES, (), "WebVTT"),
    ("application/x-subrip", "srt", CUES, {"application/x-srt", "text/srt"}, "SubRip"),
    ("application/pdf", "pdf", TEXT, (), "PDF"),
    ("image/png", "png", IMAGES, (), "PNG image"),
    ("image/jpeg", "jpg", IMAGES, {"image/jpg"}, "JPEG image"),
    ("image/webp", "webp", IMAGES, (), "WebP image"),
    ("image/gif", "gif", IMAGES, (), "GIF image"),
    ("image/bmp", "bmp", IMAGES, (), "Bitmap image"),
    (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
        ROWS,
        {"application/vnd.ms-excel.sheet.macroenabled.12"},
        "Excel workbook",
    ),
    ("application/vnd.ms-excel", "xls", ROWS, (), "Excel 97-2003 workbook"),
    (
        "application/vnd.oasis.opendocument.spreadsheet",
        "ods",
        ROWS,
        (),
        "OpenDocument spreadsheet",
    ),
    (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
        TEXT,
        (),
        "Word document",
    ),
    (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
        TEXT,
        (),
        "PowerPoint presentation",
    ),
    ("application/vnd.oasis.opendocument.text", "odt", TEXT, (), "OpenDocument text"),
    (
        "application/vnd.oasis.opendocument.presentation",
        "odp",
        TEXT,
        (),
        "OpenDocument presentation",
    ),
    (
        "application/vnd.oasis.opendocument.graphics",
        "odg",
        TEXT,
        (),
        "OpenDocument graphics",
    ),
    ("application/msword", "doc", TEXT, (), "Word 97-2003 document"),
    (
        "application/vnd.ms-powerpoint",
        "ppt",
        TEXT,
        (),
        "PowerPoint 97-2003 presentation",
    ),
)
_BUILTIN_EXTENSION_ALIASES = (("jpeg", "image/jpeg"),)

for _mimetype, _extension, _representation, _accepts, _label in _BUILTIN_FORMATS:
    register_format(
        Format(
            mimetype=_mimetype,
            extension=_extension,
            representation=_representation,
            accepts=frozenset(_accepts),
            label=_label,
        )
    )
for _extension, _mimetype in _BUILTIN_EXTENSION_ALIASES:
    register_extension(_extension, _mimetype)
