import codecs
import io
import logging
import mimetypes
import re
import zipfile
from collections.abc import Callable
from typing import Literal, NamedTuple, Protocol

_utf8_incremental_decoder = codecs.getincrementaldecoder("utf-8")

__all__ = [
    "MIMETYPE_HEAD_SIZE",
    "UNKNOWN_MIMETYPE",
    "SystemUser",
    "_olecf_mimetypes",
    "fix_filename_extension",
    "get_extension",
    "guess_mimetype",
    "neuter_mimetype",
]

_logger = logging.getLogger(__name__)
_logger_guess_mimetype = _logger.getChild("guess_mimetype")
MIMETYPE_HEAD_SIZE = 2048
UNKNOWN_MIMETYPE = "application/octet-stream"
"""What both libmagic and our own guesser return when they cannot identify the content."""


_ooxml_dirs = {
    "word/": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt/": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xl/": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _check_ooxml(data: bytes) -> str | Literal[False]:
    with io.BytesIO(data) as f, zipfile.ZipFile(f) as z:
        filenames = z.namelist()
        if "[Content_Types].xml" not in filenames:
            return False

        for dirname, mime in _ooxml_dirs.items():
            if any(entry.startswith(dirname) for entry in filenames):
                return mime

        return False


_mime_validator = re.compile(
    r"""
    [\w-]+ # type-name
    / # subtype separator
    [\w-]+ # registration facet or subtype
    (?:\.[\w-]+)* # optional faceted name
    (?:\+[\w-]+)? # optional structured syntax specifier
""",
    re.VERBOSE,
)


def _check_open_container_format(data: bytes) -> str | Literal[False]:
    with io.BytesIO(data) as f, zipfile.ZipFile(f) as z:
        if "mimetype" not in z.namelist():
            return False

        with z.open("mimetype") as mimetype_file:
            marcel = mimetype_file.read(256).decode("ascii")
        if len(marcel) < 256 and _mime_validator.match(marcel):
            return marcel

        return False


_old_ms_office_mimetypes = {
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
}
_olecf_mimetypes = ("application/x-ole-storage", "application/CDFV2")

# OLE compound-file directory entry names, UTF-16LE as they are stored. The
# signature checks in _check_olecf look at one fixed offset and only match when
# the stream happens to be the first sector allocated; these names are present
# whichever sector the FAT put the stream in.
_olecf_streams = (
    ("WordDocument".encode("utf-16-le"), "application/msword"),
    ("Workbook".encode("utf-16-le"), "application/vnd.ms-excel"),
    ("Book".encode("utf-16-le"), "application/vnd.ms-excel"),
    ("PowerPoint Document".encode("utf-16-le"), "application/vnd.ms-powerpoint"),
)
_ppt_pattern = re.compile(
    rb"""
    \x00\x6e\x1e\xf0
  | \x0f\x00\xe8\x03
  | \xa0\x46\x1d\xf0
  | \xfd\xff\xff\xff(\x0e|\x1c|\x43)\x00\x00\x00
""",
    re.VERBOSE,
)


def _check_olecf(data: bytes) -> str | Literal[False]:
    offset = 0x200
    if data.startswith(b"\xec\xa5\xc1\x00", offset):
        return "application/msword"
    elif b"Microsoft Excel" in data:
        return "application/vnd.ms-excel"
    elif _ppt_pattern.match(data, offset):
        return "application/vnd.ms-powerpoint"
    # Every check above reads one fixed offset, so a real .doc whose
    # WordDocument stream is not the first sector fell through to False and was
    # served as the container type application/x-ole-storage -- which is not
    # even an IANA-registered mimetype. The directory entry names do not move.
    for stream, mimetype in _olecf_streams:
        if stream in data:
            return mimetype
    return False


def _check_svg(data: bytes) -> str | None:
    if b"<svg" in data and b"/svg" in data:
        return "image/svg+xml"
    return None


def _check_webp(data: bytes) -> str | None:
    if data[8:15] == b"WEBPVP8":
        return "image/webp"
    return None


class _Entry(NamedTuple):
    mimetype: str
    signatures: list[bytes]
    discriminants: list[Callable[[bytes], str | bool | None]]


_mime_mappings = (
    _Entry("application/pdf", [b"%PDF"], []),
    _Entry(
        "image/jpeg",
        [
            b"\xff\xd8\xff\xe0",
            b"\xff\xd8\xff\xe2",
            b"\xff\xd8\xff\xe3",
            b"\xff\xd8\xff\xe1",
            b"\xff\xd8\xff\xdb",
        ],
        [],
    ),
    _Entry("image/png", [b"\x89PNG\r\n\x1a\n"], []),
    _Entry("image/gif", [b"GIF87a", b"GIF89a"], []),
    _Entry("image/bmp", [b"BM"], []),
    _Entry(
        "text/xml",
        [b"<"],
        [
            _check_svg,
        ],
    ),
    _Entry("image/x-icon", [b"\x00\x00\x01\x00"], []),
    _Entry(
        "image/webp",
        [b"RIFF"],
        [
            _check_webp,
        ],
    ),
    _Entry(
        "application/msword",
        [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"\x0d\x44\x4f\x43"],
        [_check_olecf],
    ),
    _Entry(
        "application/zip",
        [b"PK\x03\x04"],
        [_check_ooxml, _check_open_container_format],
    ),
)


def _odoo_guess_mimetype(bin_data: bytes, default: str = UNKNOWN_MIMETYPE) -> str:
    for entry in _mime_mappings:
        for signature in entry.signatures:
            if bin_data.startswith(signature):
                for discriminant in entry.discriminants:
                    try:
                        guess = discriminant(bin_data)
                        # `isinstance`, not truthiness: the discriminants are
                        # typed `str | bool` and only a str is a mimetype.
                        if isinstance(guess, str):
                            return guess
                    except Exception:
                        _logger_guess_mimetype.warning(
                            "Sub-checker '%s' of type '%s' failed",
                            discriminant.__name__,
                            entry.mimetype,
                            exc_info=True,
                        )
                return entry.mimetype
    try:
        head = _utf8_incremental_decoder().decode(bin_data[:1024], final=False)
    except ValueError:
        return default
    if head and all(c >= " " or c in "\t\n\r" for c in head):
        return "text/plain"
    return default


# libmagic is an ENHANCEMENT over _odoo_guess_mimetype above, not a replacement:
# guess_mimetype consults it first and falls back to our own signatures only when
# it answers UNKNOWN_MIMETYPE. That ordering is why a pure-Python detector cannot
# simply take its place, and puremagic in particular must not -- measured 2026-08
# over 90 real files from this checkout, on the 2048-byte head this module passes,
# the two agree on 38. The disagreements are not just coverage:
#
#   .xlsx / .ods / .odt  ->  ...wordprocessingml.document   (every OOXML and ODF
#                                                            container called a
#                                                            Word document)
#   .zip                 ->  application/java-archive
#   .js                  ->  text/x-python
#
# Those are CONFIDENT wrong answers, so they never reach the UNKNOWN_MIMETYPE
# branch and our _check_ooxml/_check_open_container_format discriminants -- which
# exist precisely to tell the zip-container subtypes apart -- are bypassed.
# puremagic is better on a few (font/ttf where libmagic says
# application/SIMH-tape-data, application/json, image/x-icon), and it would drop
# the libmagic system dependency and the win32 exclusion on the pin. Neither pays
# for mislabelling every spreadsheet as a text document. Revisit only with a
# fixture corpus asserting the zip-family subtypes.
try:
    import magic
except ImportError:
    magic = None


def guess_mimetype(bin_data: bytes | bytearray, default: str = UNKNOWN_MIMETYPE) -> str:
    if isinstance(bin_data, bytearray):
        # Convert, but do NOT truncate: the fallback below needs the whole
        # buffer. A zip's central directory sits at the END of the file, so a
        # 2048-byte head makes _check_ooxml/_check_open_container_format raise
        # BadZipFile, and every OOXML or ODF buffer passed as a bytearray came
        # back as the generic application/zip -- with six warning lines logged
        # per call -- where the same bytes returned the right subtype.
        bin_data = bytes(bin_data)
    elif not isinstance(bin_data, bytes):
        msg = "`bin_data` must be bytes or bytearray"
        raise TypeError(msg)
    if magic is not None:
        mimetype = magic.from_buffer(bin_data[:MIMETYPE_HEAD_SIZE], mime=True)
    else:
        mimetype = UNKNOWN_MIMETYPE
    if mimetype == UNKNOWN_MIMETYPE:
        mimetype = _odoo_guess_mimetype(bin_data, default)
    if mimetype in _olecf_mimetypes:
        try:
            if msoffice_mimetype := _check_olecf(bin_data):
                return msoffice_mimetype
        except Exception:
            _logger_guess_mimetype.warning(
                "Sub-checker '_check_olecf' of type '%s' failed",
                mimetype,
                exc_info=True,
            )
    if mimetype == "application/zip":
        try:
            if msoffice_mimetype := _check_ooxml(bin_data):
                return msoffice_mimetype
        except zipfile.BadZipFile:
            pass
        except Exception:
            _logger_guess_mimetype.warning(
                "Sub-checker '_check_ooxml' of type '%s' failed",
                mimetype,
                exc_info=True,
            )
    return mimetype


class SystemUser(Protocol):
    def _is_system(self) -> bool: ...


def neuter_mimetype(mimetype: str, user: SystemUser) -> str:
    wrong_type = "ht" in mimetype or "xml" in mimetype or "svg" in mimetype
    if wrong_type and not user._is_system():
        return "text/plain"
    return mimetype


_extension_pattern = re.compile(r"\w+")


def get_extension(filename: str) -> str:
    _stem, dot, ext = filename.lstrip(".").rpartition(".")
    if not dot or not _extension_pattern.fullmatch(ext):
        return ""

    if len(ext) <= 4:
        return f".{ext}".lower()

    guessed_mimetype, guessed_ext = mimetypes.guess_type(filename)
    if guessed_ext:
        return guessed_ext
    if guessed_mimetype:
        return f".{ext}".lower()

    return ""


def fix_filename_extension(filename: str, mimetype: str) -> str:
    extension_mimetype = mimetypes.guess_type(filename)[0]
    if extension_mimetype == mimetype:
        return filename

    extension = get_extension(filename)
    if mimetype in _olecf_mimetypes and extension in _old_ms_office_mimetypes:
        return filename

    if mimetype == "application/zip" and extension in {
        ".docx",
        ".xlsx",
        ".pptx",
    }:
        return filename

    # A distinct name from the `extension` above: the walrus used to rebind it,
    # so the two lines below silently switched from the filename's own
    # extension to the guessed one. Same values, but only one of them is
    # `str` — which is how the reuse surfaced at all.
    if guessed_extension := mimetypes.guess_extension(mimetype):
        _logger.warning(
            "File %r has an invalid extension for mimetype %r, adding %r",
            filename,
            mimetype,
            guessed_extension,
        )
        return filename + guessed_extension

    _logger.warning(
        "File %r has an unknown extension for mimetype %r", filename, mimetype
    )
    return filename
