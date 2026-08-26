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

    def _sanitized(self, name: str | None) -> str | None:
        if not name:
            return name
        # Both sheet kinds share one namespace in `_check_sheetname`, and
        # `worksheets()` is the list it checks against, so a chartsheet clashes
        # with a worksheet exactly as two worksheets do.
        return sanitize_excel_sheet_name(
            name, [sheet.name for sheet in self.worksheets()]
        )

    def add_worksheet(
        self, name: str | None = None, worksheet_class: type | None = None
    ) -> Any:
        return super().add_worksheet(
            self._sanitized(name), worksheet_class=worksheet_class
        )

    def add_chartsheet(
        self, name: str | None = None, chartsheet_class: type | None = None
    ) -> Any:
        return super().add_chartsheet(
            self._sanitized(name), chartsheet_class=chartsheet_class
        )


def patch_module() -> None:
    """Make `xlsxwriter.Workbook` safe for names and cell values we do not own.

    Two problems, both from data that reaches the workbook without passing a
    validator. Sheet names come from translated report titles and can break
    every one of Excel's four naming rules, so they go through
    `sanitize_excel_sheet_name` first -- xlsxwriter's own check only raises.
    And `strings_to_formulas` is on by default, which turns an exported cell
    beginning with `=` into a live formula; it is switched off.

    Patching the `xlsxwriter.Workbook` attribute is enough: every call site in
    the tree does `import xlsxwriter` and then `xlsxwriter.Workbook(...)`, so
    none of them bypasses the subclass.
    """
    xlsxwriter.Workbook = PatchedXlsxWorkbook
