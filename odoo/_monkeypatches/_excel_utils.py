import re
from typing import Final

_INVALID_EXCEL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\[\]:*?/\\]")
_MAX_SHEET_NAME_LENGTH: Final[int] = 31


def sanitize_excel_sheet_name(name: str) -> str:
    if not name:
        return name
    name = _INVALID_EXCEL_CHARS_RE.sub("", name)
    return name[:_MAX_SHEET_NAME_LENGTH]
