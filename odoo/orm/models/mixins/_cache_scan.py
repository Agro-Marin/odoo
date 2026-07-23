"""Eligibility rules for the raw field-cache scanning fast paths.

Five call sites bypass ``Field.__get__`` and scan a field's raw cache dict
directly: ``mapped``, ``filtered``, ``grouped``, ``_sorted_by_ids``
(TraversalMixin) and ``_read_format`` (ReadMixin).  Each mode needs a
different guarantee from the raw cache value, so each has exactly one
predicate here — the single owner of "which field types are safe to scan
raw per mode" — instead of a hand-rolled check at every call site.

Per-miss fallback protocol shared by the scans: the call site first runs
``field.ensure_access(...)`` and ``field.ensure_computed(records)``, then
scans ``field._get_cache(env)``; a slot that is absent or ``PENDING`` is a
miss and must be resolved through ``Field.__get__`` on a singleton obtained
by iterating the recordset (iteration shares ``_prefetch_ids``, so the first
miss batch-fetches the rest).  ``_sorted_by_ids`` instead bails out entirely
on the first miss (sort keys are all-or-nothing).
"""

import typing

if typing.TYPE_CHECKING:
    from ...fields.base import Field

# Field types where convert_to_record(value, record) is the identity for
# non-None values: the raw cache value IS the record value.
_IDENTITY_TYPES = frozenset(
    {
        "boolean",
        "date",
        "datetime",
        "selection",
        "integer",
        "float",
        "monetary",
    }
)
_CHAR_TEXT_TYPES = frozenset({"char", "text"})

# Types eligible for the ID-based sort: non-relational, non-boolean scalars
# whose cache value is directly comparable.  Boolean is excluded because it
# sorts via expression_getter (not raw cache access).
_SORTABLE_TYPES = frozenset(
    {
        "char",
        "text",
        "integer",
        "float",
        "monetary",
        "date",
        "datetime",
        "selection",
    }
)

# Types whose convert_to_record + convert_to_read chain reduces to
# ``none_val if v is None else v``.
_READ_TYPES = frozenset(
    {
        "boolean",
        "selection",
        "date",
        "datetime",
        "char",
        "text",  # non-translate only (checked in can_scan_read)
        # integer is safe ONLY because Integer/Id are int4-backed (always
        # <= MAXINT, so convert_to_read is identity).  An int8-backed
        # integer would need the slow path and MUST NOT be added here.
        "integer",
        "float",
        "monetary",
    }
)


def can_scan_identity(field: Field) -> bool:
    """``mapped()``/``grouped()`` value scan: the raw cache value must BE the
    record value (``convert_to_record`` is the identity for non-None values),
    so singleton creation and method dispatch can be skipped.  Per-term-
    translated char/text cache ``{lang: value}`` dicts, not scalars.
    """
    return field.type in _IDENTITY_TYPES or (
        field.type in _CHAR_TEXT_TYPES and not callable(field.translate)
    )


def can_scan_truthy(field: Field) -> bool:
    """``filtered(field_name)`` truthiness scan: ``bool(raw cache value)``
    must equal ``bool(field value)``.  Relational fields are excluded: a
    many2one caches the comodel id, and for an unsaved record that is a
    ``NewId`` whose ``__bool__`` is False while the field value is a truthy
    one-record recordset.  Per-term-translated fields cache ``{lang: value}``
    dicts the C scanner cannot read.
    """
    return not field.relational and not callable(field.translate)


def can_scan_sorted(field: Field) -> bool:
    """``sorted(order)``/``_sorted_by_ids`` cache sort: raw cache values must
    be directly comparable scalars.  Per-term-translated fields cache
    ``{lang: value}`` dicts (a LangProxyDict), not the plain scalars the Rust
    sorter needs.
    """
    return field.type in _SORTABLE_TYPES and not callable(field.translate)


def can_scan_read(field: Field) -> bool:
    """``_read_format`` scalar fill: the ``convert_to_record`` +
    ``convert_to_read`` chain must reduce to ``none_val if v is None else v``.
    Requires ``store`` — non-stored fields are not populated by ``fetch()``
    and need ``__get__`` to trigger computation.
    """
    return (
        field.store
        and not field.relational
        and not callable(field.translate)
        and field.type in _READ_TYPES
    )
