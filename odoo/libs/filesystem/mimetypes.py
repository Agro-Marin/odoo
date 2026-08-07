"""Mimetypes-related utilities.

# TODO: reexport stdlib mimetypes?
"""

import codecs
import collections
import io
import logging
import mimetypes
import re
import zipfile
from typing import Protocol

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


def _check_ooxml(data: bytes) -> str | bool:
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


def _check_open_container_format(data: bytes) -> str | bool:
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
_xls_pattern = re.compile(
    b"""
    \x09\x08\x10\x00\x00\x06\x05\x00
  | \xfd\xff\xff\xff(\x10|\x1f|\x20|"|\\#|\\(|\\))
""",
    re.VERBOSE,
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


def _check_olecf(data: bytes) -> str | bool:
    """Discriminate pre-OOXML Office formats stored as OLE Compound Files.

    Such files all use the same file signature ("magic bytes") and should have
    a subheader at offset 512 (0x200).

    Subheaders taken from http://www.garykessler.net/library/file_sigs.html
    according to which Mac office files *may* have different subheaders. We'll
    ignore that.
    """
    offset = 0x200
    if data.startswith(b"\xec\xa5\xc1\x00", offset):
        return "application/msword"
    elif b"Microsoft Excel" in data:
        return "application/vnd.ms-excel"
    elif _ppt_pattern.match(data, offset):
        return "application/vnd.ms-powerpoint"
    return False


def _check_svg(data: bytes) -> str | None:
    """Check for the opening and ending SVG tags in the data."""
    if b"<svg" in data and b"/svg" in data:
        return "image/svg+xml"
    return None


def _check_webp(data: bytes) -> str | None:
    """Check for the WEBP and VP8 markers in the RIFF container."""
    if data[8:15] == b"WEBPVP8":
        return "image/webp"
    return None


_Entry = collections.namedtuple("_Entry", ["mimetype", "signatures", "discriminants"])
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
    """Guess the mime type of the provided binary data.

    Similar to but significantly more limited than libmagic.

    :param bin_data: binary data to try and guess a mime type for
    :returns: matched mimetype, or ``default`` if none matched
    """
    for entry in _mime_mappings:
        for signature in entry.signatures:
            if bin_data.startswith(signature):
                for discriminant in entry.discriminants:
                    try:
                        guess = discriminant(bin_data)
                        if guess:
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
        head = _utf8_incremental_decoder().decode(bin_data[:1024], False)
    except ValueError:
        return default
    if head and all(c >= " " or c in "\t\n\r" for c in head):
        return "text/plain"
    return default


try:
    import magic
except ImportError:
    magic = None


def guess_mimetype(bin_data: bytes | bytearray, default: str = UNKNOWN_MIMETYPE) -> str:
    """Guess the MIME type of binary data using libmagic.

    Falls back to MS Office sub-checkers for CDFV2/ZIP containers.

    :param bin_data: the bytes to identify (only the first
        ``MIMETYPE_HEAD_SIZE`` are handed to libmagic)
    :param default: returned when neither libmagic nor the signature-based
        guesser can identify the content
    """
    if isinstance(bin_data, bytearray):
        bin_data = bytes(bin_data[:MIMETYPE_HEAD_SIZE])
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
    """The one thing this module needs to know about a user.

    ``odoo.addons.base.models.res_users.ResUsers`` satisfies this structurally,
    which is what keeps ``odoo/libs`` dependency-free: the parameter used to be
    typed ``object`` and the function called ``user._is_system()`` on it, so the
    coupling was real but invisible to ``libs-is-dependency-free`` (which
    reasons about imports, and there was no import). Same treatment as
    ``LocaleConventions`` in :mod:`odoo.libs.locale.number_format`, and the same
    reason: a Protocol states the requirement without importing the model.
    """

    def _is_system(self) -> bool:
        """Whether the user belongs to the system/administration group."""
        ...


def neuter_mimetype(mimetype: str, user: SystemUser) -> str:
    """Downgrade risky markup mimetypes to ``text/plain`` for non-system users.

    .. note::
        No production caller as of 2026-08. ``ir.attachment`` performs the same
        downgrade inline (``_check_contents``) against a *different* predicate —
        write access on ``ir.ui.view`` plus the ``attachments_mime_plainxml``
        context flag — rather than the system-group test here. Two rules for one
        security decision, and the one with the narrower predicate is the one
        that runs. Worth reconciling; until then, do not assume this function
        reflects what the framework actually does.
    """
    wrong_type = "ht" in mimetype or "xml" in mimetype or "svg" in mimetype
    if wrong_type and not user._is_system():
        return "text/plain"
    return mimetype


_extension_pattern = re.compile(r"\w+")


def get_extension(filename: str) -> str:
    """Return the extension of the filename, or an empty string if it has none."""
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
    """Make sure the filename ends with an extension of the mimetype.

    :param str filename: the filename with an unsafe extension
    :param str mimetype: the mimetype detected reading the file's content
    :returns: the same filename if its extension matches the detected
        mimetype, otherwise the same filename with the mimetype's
        extension added at the end.
    """
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

    if extension := mimetypes.guess_extension(mimetype):
        _logger.warning(
            "File %r has an invalid extension for mimetype %r, adding %r",
            filename,
            mimetype,
            extension,
        )
        return filename + extension

    _logger.warning(
        "File %r has an unknown extension for mimetype %r", filename, mimetype
    )
    return filename
