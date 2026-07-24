"""Barcode rendering and check-digit helpers built on Reportlab."""

import functools
import re
from threading import RLock
from typing import Any

__all__ = [
    "check_barcode_encoding",
    "createBarcodeDrawing",
    "get_barcode_check_digit",
    "get_barcode_font",
]
_barcode_init_lock: RLock = RLock()


# Reportlab builds a T1 font cache on first barcode render; this initialization
# is not thread-safe. The lock serializes it; ``lru_cache`` then serves every
# later call without taking the lock. Note the cache alone would not be enough:
# it does not hold the lock across a miss, so concurrent first callers can all
# enter the body -- the lock (plus the ``_barcode_init`` guard) is what makes
# the reportlab work happen once.
_barcode_init: tuple[Any, str] | None = None


@functools.lru_cache(1)
def _init_barcode() -> tuple[Any, str]:
    global _barcode_init  # noqa: PLW0603
    with _barcode_init_lock:
        if _barcode_init is not None:
            return _barcode_init
        try:
            from reportlab.graphics import barcode
            from reportlab.pdfbase.pdfmetrics import TypeFace, getFont

            font_name = "Courier"
            available = TypeFace(font_name).findT1File()
            if not available:
                substitution_font = "NimbusMonoPS-Regular"
                fnt = getFont(substitution_font)
                if fnt:
                    font_name = substitution_font
                    fnt.ascent = 629
                    fnt.descent = -157
            barcode.createBarcodeDrawing(
                "Code128",
                value="foo",
                format="png",
                width=100,
                height=100,
                humanReadable=1,
                fontName=font_name,
            ).asString("png")
        except ImportError:
            raise
        except Exception:
            font_name = "Courier"
        _barcode_init = (barcode, font_name)
        return _barcode_init


def createBarcodeDrawing(codeName: str, **options: Any) -> Any:
    """Create a Reportlab barcode drawing for `codeName` with the given options."""
    barcode, _font = _init_barcode()
    return barcode.createBarcodeDrawing(codeName, **options)


def get_barcode_font() -> str:
    """Get the barcode font for rendering."""
    _barcode, font = _init_barcode()
    return font


def get_barcode_check_digit(numeric_barcode: str) -> int:
    """Compute and return the barcode check digit.

    The algorithm follows the GTIN specifications and works for all
    compatible barcode nomenclatures, such as EAN-8, EAN-12 (UPC-A) or EAN-13.
    https://www.gs1.org/sites/default/files/docs/barcodes/GS1_General_Specifications.pdf
    https://www.gs1.org/services/how-calculate-check-digit-manually

    :param numeric_barcode: the barcode to verify/recompute the check digit
    :return: the number corresponding to the right check digit.
    """
    # Multiply value of each position by
    # N1  N2  N3  N4  N5  N6  N7  N8  N9  N10 N11 N12 N13 N14 N15 N16 N17 N18
    # x3  X1  x3  x1  x3  x1  x3  x1  x3  x1  x3  x1  x3  x1  x3  x1  x3  CHECKSUM
    oddsum = evensum = 0
    # Drop the check digit (it gets recomputed) and reverse, so the odd/even
    # grouping is anchored at the right and independent of the barcode length.
    code = numeric_barcode[-2::-1]
    for i, digit in enumerate(code):
        if i % 2 == 0:
            evensum += int(digit)
        else:
            oddsum += int(digit)
    total = evensum * 3 + oddsum
    return (10 - total % 10) % 10


_BARCODE_SIZES = {
    "ean8": 8,
    "ean13": 13,
    "gtin14": 14,
    "upca": 12,
    "sscc": 18,
}

# ASCII digits only: ``\d`` also matches Unicode decimal digits, so a barcode
# written in fullwidth (U+FF10..U+FF19) or Arabic-Indic digits validated as a
# legal EAN-8 and then round-tripped through int() without complaint.
_ASCII_DIGITS_RE = re.compile(r"\A[0-9]+\Z")


def check_barcode_encoding(barcode: str, encoding: str) -> bool:
    """Check whether the given barcode is correctly encoded.

    :return: True if the barcode string is encoded with the provided encoding.
        An encoding this function knows no fixed length for (including the
        ``gs1-128`` value that ``barcodes_gs1_nomenclature`` adds to
        ``barcode.rule.encoding``) yields False rather than raising.
    """
    encoding = encoding.lower()
    if encoding == "any":
        return True
    barcode_size = _BARCODE_SIZES.get(encoding)
    if barcode_size is None:
        # Unknown symbology: it cannot satisfy this encoding's check-digit rule.
        return False
    # The length test comes FIRST: the ean13 leading-zero test used to be
    # evaluated before it and indexed ``barcode[0]`` unconditionally, so an
    # empty value raised IndexError instead of returning False -- reachable
    # from ``ir.actions.report.barcode`` (and hence the /report/barcode route)
    # with an EAN type and no value.  The same short-circuit guards the
    # ``barcode[-1]`` indexing in the check-digit test below.
    return bool(
        len(barcode) == barcode_size
        and _ASCII_DIGITS_RE.match(barcode)
        and (encoding != "ean13" or barcode[0] != "0")
        and get_barcode_check_digit(barcode) == int(barcode[-1])
    )
