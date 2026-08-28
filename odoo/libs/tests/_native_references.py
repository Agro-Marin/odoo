"""Pure-Python references for the `odoo_rust` exports that have none in production.

Nine of the twelve exports already have one, because something still calls it:
the eight `_field_access` functions have `odoo/libs/_field_access/_fallback.py`,
and `origin_ids` has `_origin_ids_python`, which `orm/helpers._origin_ids` uses
for any non-tuple input. `csv_export`, `rows_to_dicts` and `fast_clone` have
nothing.

They are defined here, under `tests/`, and deliberately NOT beside the functions
they stand in for. An unused twin in production is not a reference, it is drift
waiting to happen: the crate carried eight `#[allow(dead_code)]` `_safe`
functions kept "for documentation and semantic comparison", nothing called them
so nothing compared them, and `clone_inner_safe` had quietly acquired different
subclass semantics from the very function it documented. A reference earns its
keep by being *run against* the thing it describes, which is what the two suites
beside this file do:

- `test_native_parity_fuzz` — do they compute the same answer?
- `test_native_acceleration_pays` — is the accelerated one faster?

Neither is meaningful without the other. A reference that is not checked for
agreement makes the speed ratio a comparison between two different jobs; a
reference nobody times makes the agreement free.
"""

import csv
import io

__all__ = ["NewId", "clone_ref", "csv_export_ref", "rows_to_dicts_ref"]

#: The cell prefixes `web.rs` neutralises: spreadsheet applications read a cell
#: starting with any of these as a formula or a command. The Python original
#: guarded only the first three; the Rust added `@`, tab and CR, which are the
#: remaining OWASP CSV-injection prefixes. This reference implements what the
#: Rust documents, because that is what it is a reference *for* — the historical
#: three are pinned separately in `addons/web/tests/test_export.py`.
FORMULA_PREFIXES = ("=", "-", "+", "@", "\t", "\r")


def csv_export_ref(headers, rows):
    """`CSVExport.from_data`'s rules, on Python's own `csv` writer.

    QUOTE_ALL, `\\r\\n` terminators, `None`/`False` blanked by identity so that
    `0` and `""` survive, `bytes` decoded, and a leading formula character
    neutralised with a `'`.
    """
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
    """The pattern `rows.rs` names as the one it replaced."""
    return [dict(zip(names, row, strict=True)) for row in rows]


def clone_ref(obj):
    """`clone.rs`'s semantics: containers rebuilt, everything else shared.

    `isinstance`, not `type(x) is`, to match `PyDict_Check` — the accelerated
    version rebuilds subclasses too, and normalizes them to the builtin type,
    which is why a `dict` subclass compares equal to the plain dict this
    returns.

    NOT what production replaced. `Json.convert_to_record` called
    `copy.deepcopy`, which also memoizes, so it preserves aliasing between two
    slots that hold the same object where this (and the Rust) duplicate it. For
    a tree — which JSON is — the two agree.
    """
    if isinstance(obj, dict):
        return {key: clone_ref(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [clone_ref(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(clone_ref(value) for value in obj)
    return obj


class NewId:
    """Falsy, carrying an `origin` — what `origin_ids` exists to unwrap."""

    __slots__ = ("origin",)

    def __init__(self, origin):
        self.origin = origin

    def __bool__(self):
        return False
