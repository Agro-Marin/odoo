"""Locale conversion utilities.

Pure Python locale helpers with no Odoo dependencies.
"""

from .conversions import (
    # Regex patterns
    XPG_LOCALE_RE,
    POSIX_TO_LDML,
    # Conversion functions
    py_to_js_locale,
    posix_to_ldml,
)

__all__ = [
    "POSIX_TO_LDML",
    # Regex patterns
    "XPG_LOCALE_RE",
    "posix_to_ldml",
    # Conversion functions
    "py_to_js_locale",
]
