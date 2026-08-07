"""
Shared utilities for Excel-related monkeypatches.

This module provides common functionality used by xlsxwriter.py
to sanitize Excel sheet names according to Microsoft Excel restrictions.
"""

import re
from typing import Final

_INVALID_EXCEL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\[\]:*?/\\]")
_MAX_SHEET_NAME_LENGTH: Final[int] = 31


def sanitize_excel_sheet_name(name: str) -> str:
    """Sanitize a string to be used as an Excel sheet name.

    Removes invalid characters and truncates to the maximum allowed length.

    :param name: The proposed sheet name
    :return: A sanitized sheet name safe for Excel
    """
    if not name:
        return name
    name = _INVALID_EXCEL_CHARS_RE.sub("", name)
    return name[:_MAX_SHEET_NAME_LENGTH]
