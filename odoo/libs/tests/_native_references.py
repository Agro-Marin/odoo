import csv
import io

__all__ = ["NewId", "clone_ref", "csv_export_ref", "rows_to_dicts_ref"]

FORMULA_PREFIXES = ("=", "-", "+", "@", "\t", "\r")


def csv_export_ref(headers, rows):
    fp = io.StringIO()
    writer = csv.writer(fp, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    for row in rows:
        cells = []
        for value in row:
            if value is None or value is False:
                value = ""
            elif isinstance(value, bytes):
                value = value.decode()
            if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return fp.getvalue().encode()


def rows_to_dicts_ref(names, rows):
    return [dict(zip(names, row, strict=True)) for row in rows]


def clone_ref(obj):
    if isinstance(obj, dict):
        return {key: clone_ref(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [clone_ref(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(clone_ref(value) for value in obj)
    return obj


class NewId:
    __slots__ = ("origin",)

    def __init__(self, origin):
        self.origin = origin

    def __bool__(self):
        return False
