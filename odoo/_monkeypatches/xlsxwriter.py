"""
Patch xlsxwriter for Odoo-specific defaults:

- Sanitize Excel sheet names (remove invalid characters, enforce 31-char limit)
- Disable formula interpretation of strings to prevent formula injection attacks
  (e.g. a partner named '=HYPERLINK("http://evil.com","Click")' in an export)
"""

from typing import Any

import xlsxwriter

from ._excel_utils import sanitize_excel_sheet_name


class PatchedXlsxWorkbook(xlsxwriter.Workbook):
    def __init__(
        self, filename: str | None = None, options: dict[str, Any] | None = None
    ) -> None:
        options = dict(options or {})
        options.setdefault("strings_to_formulas", False)
        super().__init__(filename, options)

    def add_worksheet(
        self, name: str | None = None, worksheet_class: type | None = None
    ) -> Any:
        if name:
            name = sanitize_excel_sheet_name(name)
        return super().add_worksheet(name, worksheet_class=worksheet_class)


def patch_module() -> None:
    xlsxwriter.Workbook = PatchedXlsxWorkbook  # type: ignore[misc]
