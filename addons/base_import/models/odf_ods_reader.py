import zipfile

from odf import opendocument
from odf.table import Table, TableCell, TableRow
from odf.text import P

from odoo import _

# `.ods` is a zip archive, and `opendocument.load` reads every member --
# `content.xml`, embedded pictures, thumbnails -- fully into memory via plain
# `zipfile`-backed `z.read()`, with no size guard of its own. A member's
# declared uncompressed size is fully controlled by the file's author, so a
# small upload can decompress to gigabytes before this reader's own
# MAX_CELL_REPEAT/MAX_ROW_REPEAT below ever see a single cell (a zip bomb).
# Checked ahead of `opendocument.load`, against the archive's own declared
# sizes -- cheap, since it only reads the central directory, never a member's
# data.
MAX_UNCOMPRESSED_MEMBER_SIZE = 100 * 1024 * 1024  # 100 MiB


def _check_zip_member_sizes(file):
    """Raise if any member of the ``.ods`` archive would decompress past
    :data:`MAX_UNCOMPRESSED_MEMBER_SIZE`, before handing it to odfpy.

    :param file: a file-like object holding the .ods archive
    :raises ValueError: on the first oversized member
    """
    with zipfile.ZipFile(file) as archive:
        for info in archive.infolist():
            if info.file_size > MAX_UNCOMPRESSED_MEMBER_SIZE:
                raise ValueError(
                    _(
                        "Import file %(member)s would expand to more than "
                        "%(cap)s MiB, which is not supported.",
                        member=info.filename,
                        cap=MAX_UNCOMPRESSED_MEMBER_SIZE // (1024 * 1024),
                    )
                )


# ODF lets a single element stand in for N identical cells/rows via
# `number-columns-repeated` / `number-rows-repeated`. Both counts are fully
# controlled by the uploaded file's author: without a cap, a crafted cell
# declaring e.g. 999999999 makes the expansion below build a near-billion
# element list and OOM-crash the worker (t24068 F1). 16384 matches Excel's own
# max column count -- generous for any real spreadsheet, well short of a DoS.
MAX_CELL_REPEAT = 16384
# Rows get their own, lower cap. The columns cap bounds one row's width; this
# one bounds how many rows a single element may become, and unlike columns it
# is routinely large *and legitimate*: producers mark the unused tail of a
# sheet as one row repeated ~1e6 times. Those rows are blank, so they are
# dropped by the emptiness filter either way -- the cap only stops us
# materialising them first.
MAX_ROW_REPEAT = 16384

# odfpy exposes DOM node types as bare ints (xml.dom.Node); name them.
_ELEMENT_NODE = 1
_TEXT_NODE = 3


def _repeat_count(element, attribute, cap):
    """Read an ODF repeat attribute, clamped to ``cap``.

    :param element: an odfpy element
    :param str attribute: ``'numbercolumnsrepeated'`` / ``'numberrowsrepeated'``
    :param int cap: upper bound, see :data:`MAX_CELL_REPEAT`
    :rtype: int
    """
    try:
        count = int(element.getAttribute(attribute) or 1)
    except ValueError:
        # The attribute is author-controlled and need not be a number at all.
        return 1
    return max(0, min(count, cap))


def _cell_text(cell):
    """The visible text of one cell, including styled runs.

    A cell whose text is partially formatted (bold, coloured, a different
    font) is written by every producer as one or more ``<text:span>`` children
    of the paragraph. The original loop descended into those children and then
    appended ``n.data`` -- ``n`` being the *span element*, which has no
    ``data`` attribute -- so any such cell raised ``AttributeError`` and the
    whole file was reported unreadable. Recursing over descendant text nodes
    handles spans, nested spans, and the ``<text:s>``/``<text:tab>`` runs the
    original dropped.

    :rtype: str
    """
    return "".join(_node_text(paragraph) for paragraph in cell.getElementsByType(P))


def _node_text(node):
    parts = []
    for child in node.childNodes:
        if child.nodeType == _TEXT_NODE:
            parts.append(child.data)
        elif child.nodeType == _ELEMENT_NODE:
            parts.append(_node_text(child))
    return "".join(parts)


class ODSReader:
    """Minimal ODS reader: each sheet becomes a list of rows, each row a list
    of cell strings.

    :param file: a file-like object holding the .ods archive
    :param content: an already-parsed ``OpenDocument``, used instead of ``file``
    """

    def __init__(self, file=None, content=None):
        if content is None:
            _check_zip_member_sizes(file)
        self.doc = content if content is not None else opendocument.load(file)
        self.sheets = {}
        for sheet in self.doc.spreadsheet.getElementsByType(Table):
            name = sheet.getAttribute("name")
            # Duplicate sheet names are not legal ODF, but a crafted file can
            # still carry them; keep the first rather than let a later one
            # silently replace the sheet the user picked.
            self.sheets.setdefault(name, self._read_sheet(sheet))

    def _read_sheet(self, sheet):
        rows = []
        for row in sheet.getElementsByType(TableRow):
            cells = self._read_row(row)
            # Trailing blank rows are the overwhelmingly common use of
            # `number-rows-repeated`; drop them before expanding so the repeat
            # count of an empty row costs nothing.
            if not any(cell.strip() for cell in cells):
                continue
            repeat = _repeat_count(row, "numberrowsrepeated", MAX_ROW_REPEAT)
            rows.extend([cells] * repeat)
        return rows

    def _read_row(self, row):
        """One row's cells, repeats expanded.

        Two things this deliberately does NOT do, both of which it used to:

        * **Skip cells whose text starts with ``#``.** ODF has no comment-cell
          convention -- that came from a third-party recipe this reader
          descends from. The cell was dropped *without a placeholder*, so every
          later column of that row shifted one to the left, differently per
          row. A colour column (``#FF0000``), an ``#N/A`` a spreadsheet left
          behind, an invoice reference written ``#1042``: measured, the row
          ``['Alice', '#FF0000', '1']`` was read as ``['Alice', '1']``, which
          then imports ``1`` as the colour and nothing as the quantity. Silent
          wrong data, which is worse than a rejected file.
        * **Ignore the repeat count on the last cell of the row, whatever it
          holds.** The intent was to drop the "to the end of the used range"
          filler, which is a blank cell carrying a repeat in the thousands --
          but the test was position, not blankness, so a row genuinely *ending*
          in repeated values went with it. ``a,b,b,b`` is written by
          LibreOffice as ``<table:table-cell table:number-columns-repeated="3">
          b</table:table-cell>`` in final position (verified against a real
          CSV -> ODS conversion), and read back as ``['a', 'b']``. The file
          then failed to import on a row-width mismatch.

        A blank last cell still contributes exactly **one** cell, whatever its
        repeat says. Not zero: LibreOffice writes an ordinary trailing empty
        column as a bare ``<table:table-cell/>`` with no repeat at all -- for
        ``Bob,blue,2,`` it emits four cells, the last one empty -- so dropping
        it makes that row one narrower than its header and the import fails on
        a width mismatch it should never have seen. And not `repeat` either:
        the used-range filler would then pad every row with thousands of blank
        columns, which `_prepare_column_examples` turns into thousands of
        phantom columns in the mapping UI.
        """
        cells = []
        elements = row.getElementsByType(TableCell)
        for position, cell in enumerate(elements, start=1):
            text = _cell_text(cell)
            if position == len(elements) and not text.strip():
                repeat = 1
            else:
                repeat = _repeat_count(cell, "numbercolumnsrepeated", MAX_CELL_REPEAT)
            cells.extend([text] * repeat)
        return cells

    def get_sheet(self, name):
        """One sheet as a list of rows.

        :param str name: sheet name
        :rtype: list[list[str]]
        """
        return self.sheets[name]
