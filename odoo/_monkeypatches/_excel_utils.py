import re
from collections.abc import Iterable
from typing import Final

_INVALID_EXCEL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\[\]:*?/\\]")
_MAX_SHEET_NAME_LENGTH: Final[int] = 31
_MAX_DEDUP_SUFFIX: Final[int] = 1000


class SheetNameCollisionError(ValueError):
    """Every `~n` variant of a sanitized sheet name is already taken."""


def sanitize_excel_sheet_name(name: str, taken: Iterable[str] = ()) -> str:
    """Coerce `name` into something Excel accepts as a worksheet name.

    Enforces all four of xlsxwriter's `_check_sheetname` rules, not just the
    two that are about characters: `[]:*?/\\` are dropped, leading and trailing
    apostrophes are dropped, the result is cut to 31 characters, and a clash
    with `taken` -- compared case-insensitively, as Excel does -- is broken with
    a `~n` suffix that fits inside the same 31.

    Edge whitespace and edge apostrophes go too, including whatever the cut
    exposes. Excel tolerates a trailing space but a formula referring to such a
    sheet needs quoting, and truncation manufactures them from any name with a
    space at character 31. The cut manufactures trailing apostrophes the same
    way -- and those xlsxwriter rejects outright -- so both are stripped again
    after truncating, not only before.

    The last two are one rule, not two: truncating is what *creates* the
    clashes, so a sanitizer that truncates and does not then de-duplicate turns
    two long report names into a `DuplicateWorksheetName` at write time.

    Raises `SheetNameCollisionError` if every `~n` variant is taken, rather
    than returning the name known to clash. Reaching it needs 999 sheets
    sharing one 31-character prefix, but returning the clashing name only moved
    the failure to `Workbook.add_worksheet`, where the message names Excel's
    rule instead of the exhausted namespace that actually caused it.
    """
    if not name:
        return name
    name = _INVALID_EXCEL_CHARS_RE.sub("", name).strip().strip("'").strip()
    name = name[:_MAX_SHEET_NAME_LENGTH].rstrip().rstrip("'").rstrip()
    if not name:
        return name

    lowered = {existing.lower() for existing in taken}
    if name.lower() not in lowered:
        return name

    for suffix_n in range(2, _MAX_DEDUP_SUFFIX):
        suffix = f"~{suffix_n}"
        stem = name[: _MAX_SHEET_NAME_LENGTH - len(suffix)].rstrip("'")
        candidate = f"{stem}{suffix}"
        if candidate.lower() not in lowered:
            return candidate
    msg = (
        f"cannot fit a unique worksheet name for {name!r}: every ~2..~"
        f"{_MAX_DEDUP_SUFFIX - 1} variant is taken"
    )
    raise SheetNameCollisionError(msg)
