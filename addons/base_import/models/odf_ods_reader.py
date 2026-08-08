from odf import opendocument
from odf.table import Table, TableCell, TableRow
from odf.text import P

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
    """ Read an ODF repeat attribute, clamped to ``cap``.

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
    """ The visible text of one cell, including styled runs.

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
    return ''.join(
        _node_text(paragraph)
        for paragraph in cell.getElementsByType(P)
    )


def _node_text(node):
    parts = []
    for child in node.childNodes:
        if child.nodeType == _TEXT_NODE:
            parts.append(child.data)
        elif child.nodeType == _ELEMENT_NODE:
            parts.append(_node_text(child))
    return ''.join(parts)


class ODSReader:
    """ Minimal ODS reader: each sheet becomes a list of rows, each row a list
    of cell strings.

    :param file: a file-like object holding the .ods archive
    :param content: an already-parsed ``OpenDocument``, used instead of ``file``
    """

    def __init__(self, file=None, content=None):
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
            repeat = _repeat_count(row, 'numberrowsrepeated', MAX_ROW_REPEAT)
            rows.extend([cells] * repeat)
        return rows

    def _read_row(self, row):
        cells = []
        elements = row.getElementsByType(TableCell)
        for position, cell in enumerate(elements, start=1):
            # The repeat count on the *last* cell of a row is a "to the end of
            # the used range" marker rather than real data, so it is ignored.
            if position == len(elements):
                repeat = 1
            else:
                repeat = _repeat_count(cell, 'numbercolumnsrepeated', MAX_CELL_REPEAT)
            text = _cell_text(cell)
            if text.startswith("#"):  # comment cell
                continue
            cells.extend([text] * repeat)
        return cells

    def get_sheet(self, name):
        """ One sheet as a list of rows.

        :param str name: sheet name
        :rtype: list[list[str]]
        """
        return self.sheets[name]
