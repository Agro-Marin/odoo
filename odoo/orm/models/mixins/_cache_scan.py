"""Eligibility rules for the raw field-cache scanning fast paths.

Six call sites bypass ``Field.__get__`` and scan a field's raw cache dict
directly: ``mapped``, ``filtered``, ``grouped``, ``_sorted_by_ids``,
``_sorted_order_to_function`` (TraversalMixin) and ``_read_format``
(ReadMixin).  Each mode needs a different guarantee from the raw cache value,
so each has exactly one predicate here — the single owner of "which field
types are safe to scan raw per mode" — instead of a hand-rolled check at every
call site.

Per-miss fallback protocol shared by the scans: the call site first runs
``field.ensure_access(...)`` and ``field.ensure_computed(records)``, then
scans ``field._get_cache(env)``; a slot that is absent or ``PENDING`` is a
miss and must be resolved through ``Field.__get__`` on a singleton obtained
by iterating the recordset (iteration shares ``_prefetch_ids``, so the first
miss batch-fetches the rest).  ``_sorted_by_ids`` instead bails out entirely
on the first miss (sort keys are all-or-nothing).

**The cache shape is not a property of the field alone.**  For a
per-term-translated field ``Field._get_cache`` normally hands out a
``LangProxyDict`` view that resolves the active language, so a raw scan sees
plain scalars; under ``prefetch_langs=True`` that view is bypassed and the raw
``{id: {lang: value}}`` dict is exposed instead (see
``BaseString._get_cache_impl``).  The per-mode predicates below reject
``callable(translate)`` fields outright, which covers them in *both* shapes;
a call site that cannot use an allow-list (``_sorted_order_to_function``, whose
scalar branch must stay open to field types no list here enumerates) asks
:func:`caches_lang_dicts` instead.
"""

import typing

if typing.TYPE_CHECKING:
    from ...fields.base import Field
    from ...runtime import Environment

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

_TRUTHY_TYPES = frozenset(
    {
        "boolean",
        "integer",
        "float",
        "monetary",
        "char",
        "text",
        "html",
        "date",
        "datetime",
        "selection",
        "binary",
        "json",
        "properties",
        "properties_definition",
        "reference",
        "many2one_reference",
    }
)

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

_READ_TYPES = frozenset(
    {
        "boolean",
        "selection",
        "date",
        "datetime",
        "char",
        "text",
        "integer",
        "float",
        "monetary",
    }
)


def caches_lang_dicts(field: Field, env: Environment) -> bool:
    """Whether *field*'s cache in *env* holds raw ``{lang: value}`` dicts.

    The env-dependent half of the cache-shape question (see the module
    docstring): a per-term-translated field is normally read through a
    ``LangProxyDict`` that yields scalars, but ``prefetch_langs=True`` bypasses
    that view and exposes the raw per-language dicts.  Those are neither
    orderable nor comparable, so any caller keying on the raw cache value must
    fall back to ``Field.__get__`` — which owns the shape decode — when this
    returns ``True``.
    """
    return callable(field.translate) and bool(env.context.get("prefetch_langs"))


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
    must equal ``bool(field value)``.

    Allowlisted like every other mode here.  This was the one predicate written
    as a denylist (``not field.relational and not callable(field.translate)``),
    which inverted the default: a field type nobody had thought about was opted
    IN to raw scanning, and was only correct by luck.  ``vector`` -- defined
    outside core, so not visible to the reasoning in this module -- was being
    scanned on that basis.  Now an unlisted type takes the ``Field.__get__``
    path: slower, never wrong, and it fails toward correctness when someone adds
    a field type.

    Every type below was verified against ``__get__`` over 1654 (model, field)
    pairs across the registry.  Relational types stay out for the original
    reason: a many2one caches the comodel id, and on an unsaved record that is a
    ``NewId`` whose ``__bool__`` is False while the field value is a truthy
    one-record recordset.  Per-term-translated fields cache ``{lang: value}``
    dicts the C scanner cannot read, hence the ``translate`` check.
    """
    return field.type in _TRUTHY_TYPES and not callable(field.translate)


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
