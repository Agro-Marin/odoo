"""Every raw-cache scan predicate must be an ALLOWLIST, not a denylist.

Six call sites bypass ``Field.__get__`` and read a field's raw cache dict
(``mapped``, ``filtered``, ``grouped``, ``_sorted_by_ids``,
``_sorted_order_to_function``, ``_read_format``). Whether that is sound depends
on the field type, and the predicates in ``models/mixins/_cache_scan`` decide it.

The direction of the default is the whole safety property. ``can_scan_truthy``
was once written as ``not field.relational and not callable(field.translate)``,
which opted every unconsidered type IN -- ``vector``, defined outside core, was
being raw-scanned on that basis, and any field type a module adds tomorrow would
be too. An unlisted type must instead fall back to ``Field.__get__``: slower,
never wrong.

The sixth site (``_sorted_order_to_function``) is the odd one out and gets its
own guard below: it cannot use a type allowlist, because its scalar branch must
stay open to types no list here enumerates. It asks :func:`caches_lang_dicts`
about the cache SHAPE instead — the one question that is not answerable from the
field alone, since ``prefetch_langs`` decides it per environment.

Tier-2 suite: real ``import odoo``, no database.
"""

import pytest

from odoo.orm.models.mixins import _cache_scan
from odoo.orm.models.mixins._cache_scan import (
    caches_lang_dicts,
    can_scan_identity,
    can_scan_read,
    can_scan_sorted,
    can_scan_truthy,
)


class _FakeField:
    """Minimal Field stand-in: the predicates only read these attributes."""

    def __init__(self, ftype, *, relational=False, translate=None, store=True):
        self.type = ftype
        self.relational = relational
        self.translate = translate
        self.store = store


class _FakeEnv:
    """Minimal Environment stand-in: ``caches_lang_dicts`` reads only context."""

    def __init__(self, **context):
        self.context = context


def _per_term(callback, value):
    """A per-term ``translate`` callable (only its callability matters)."""
    return value


UNKNOWN_TYPES = ["vector", "geometry", "some_future_type", "custom_widget_thing"]

PREDICATES = [
    ("can_scan_truthy", can_scan_truthy),
    ("can_scan_sorted", can_scan_sorted),
    ("can_scan_read", can_scan_read),
    ("can_scan_identity", can_scan_identity),
]


@pytest.mark.parametrize(
    ("pred_name", "predicate"), PREDICATES, ids=[p[0] for p in PREDICATES]
)
@pytest.mark.parametrize("ftype", UNKNOWN_TYPES)
def test_unlisted_type_is_never_scanned(pred_name, predicate, ftype):
    """An unrecognised field type must take the __get__ path, for every mode."""
    assert predicate(_FakeField(ftype)) is False, (
        f"{pred_name} admits the unlisted field type {ftype!r}; "
        f"a raw cache scan would be trusted without anyone having verified it"
    )


@pytest.mark.parametrize(
    ("pred_name", "predicate"), PREDICATES, ids=[p[0] for p in PREDICATES]
)
def test_relational_types_are_never_scanned(pred_name, predicate):
    """Relational caches hold ids, not values.

    A many2one caches the comodel id; on an unsaved record that is a ``NewId``,
    falsy while the field value is a truthy one-record recordset.
    """
    for ftype in ("many2one", "one2many", "many2many"):
        field = _FakeField(ftype, relational=True)
        assert predicate(field) is False, f"{pred_name} admits {ftype}"


@pytest.mark.parametrize(
    ("pred_name", "predicate"), PREDICATES, ids=[p[0] for p in PREDICATES]
)
def test_callable_translate_is_never_scanned(pred_name, predicate):
    """Per-term-translated fields cache ``{lang: value}`` dicts, not scalars."""
    field = _FakeField("char", translate=lambda callback, value: value)
    assert predicate(field) is False, f"{pred_name} admits a callable-translate field"


def test_truthy_set_is_a_frozenset_of_known_types():
    """The allowlist must stay an explicit, immutable set of type strings."""
    assert isinstance(_cache_scan._TRUTHY_TYPES, frozenset)
    assert all(isinstance(t, str) for t in _cache_scan._TRUTHY_TYPES)
    assert not _cache_scan._TRUTHY_TYPES & {"many2one", "one2many", "many2many"}


def test_listed_scalar_types_are_still_scanned():
    """The allowlist must not have narrowed the fast path to nothing.

    These are the types verified against ``__get__`` across the registry; if one
    stops qualifying, ``filtered(name)`` silently loses its fast path.
    """
    for ftype in (
        "char",
        "integer",
        "float",
        "boolean",
        "date",
        "datetime",
        "selection",
    ):
        assert can_scan_truthy(_FakeField(ftype)) is True, f"{ftype} lost the fast path"


def test_read_requires_store():
    """Non-stored fields are not populated by fetch() and need __get__."""
    assert can_scan_read(_FakeField("char", store=False)) is False
    assert can_scan_read(_FakeField("char", store=True)) is True


def test_caches_lang_dicts_needs_both_halves():
    """Only a per-term-translated field UNDER prefetch_langs holds lang dicts.

    ``Field._get_cache`` normally wraps such a field in a ``LangProxyDict`` that
    resolves the active language, so the raw scan sees scalars;
    ``prefetch_langs=True`` bypasses the wrapper and exposes
    ``{id: {lang: value}}``. Both halves are required, and the answer must be
    ``False`` for every other combination or the fast path is lost for no reason.
    """
    per_term = _FakeField("text", translate=_per_term)
    assert caches_lang_dicts(per_term, _FakeEnv(prefetch_langs=True)) is True
    assert caches_lang_dicts(per_term, _FakeEnv()) is False
    assert caches_lang_dicts(per_term, _FakeEnv(prefetch_langs=False)) is False
    model_translated = _FakeField("char", translate=True)
    assert caches_lang_dicts(model_translated, _FakeEnv(prefetch_langs=True)) is False
    untranslated = _FakeField("char")
    assert caches_lang_dicts(untranslated, _FakeEnv(prefetch_langs=True)) is False


def test_caches_lang_dicts_covers_every_per_term_translatable_type():
    """``translate`` lives on BaseString, so every string-ish type is in scope.

    The predicate must key on ``callable(translate)`` rather than on a type list:
    ``html`` is not in any allowlist above, yet ``ir.ui.view.arch_db``-style
    per-term translation applies to it just the same.
    """
    for ftype in ("char", "text", "html"):
        field = _FakeField(ftype, translate=_per_term)
        assert caches_lang_dicts(field, _FakeEnv(prefetch_langs=True)) is True, ftype


def test_caches_lang_dicts_is_not_a_type_allowlist():
    """Guard the inversion: it EXCLUDES on True, so it must not be added to
    ``PREDICATES`` (whose contract is "True == safe to scan").

    Stated as a test because the two families read alike at the call site and a
    future edit that lumps them together would silently invert the default for
    whichever one it moved.
    """
    assert caches_lang_dicts not in dict(PREDICATES).values()
    assert caches_lang_dicts(_FakeField("some_future_type"), _FakeEnv()) is False
