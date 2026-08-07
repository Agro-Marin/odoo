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
    def __init__(self, ftype, *, relational=False, translate=None, store=True):
        self.type = ftype
        self.relational = relational
        self.translate = translate
        self.store = store


class _FakeEnv:
    def __init__(self, **context):
        self.context = context


def _per_term(callback, value):
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
    assert predicate(_FakeField(ftype)) is False, (
        f"{pred_name} admits the unlisted field type {ftype!r}; "
        f"a raw cache scan would be trusted without anyone having verified it"
    )


@pytest.mark.parametrize(
    ("pred_name", "predicate"), PREDICATES, ids=[p[0] for p in PREDICATES]
)
def test_relational_types_are_never_scanned(pred_name, predicate):
    for ftype in ("many2one", "one2many", "many2many"):
        field = _FakeField(ftype, relational=True)
        assert predicate(field) is False, f"{pred_name} admits {ftype}"


@pytest.mark.parametrize(
    ("pred_name", "predicate"), PREDICATES, ids=[p[0] for p in PREDICATES]
)
def test_callable_translate_is_never_scanned(pred_name, predicate):
    field = _FakeField("char", translate=lambda callback, value: value)
    assert predicate(field) is False, f"{pred_name} admits a callable-translate field"


def test_truthy_set_is_a_frozenset_of_known_types():
    assert isinstance(_cache_scan._TRUTHY_TYPES, frozenset)
    assert all(isinstance(t, str) for t in _cache_scan._TRUTHY_TYPES)
    assert not _cache_scan._TRUTHY_TYPES & {"many2one", "one2many", "many2many"}


def test_listed_scalar_types_are_still_scanned():
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
    assert can_scan_read(_FakeField("char", store=False)) is False
    assert can_scan_read(_FakeField("char", store=True)) is True


def test_caches_lang_dicts_needs_both_halves():
    per_term = _FakeField("text", translate=_per_term)
    assert caches_lang_dicts(per_term, _FakeEnv(prefetch_langs=True)) is True
    assert caches_lang_dicts(per_term, _FakeEnv()) is False
    assert caches_lang_dicts(per_term, _FakeEnv(prefetch_langs=False)) is False
    model_translated = _FakeField("char", translate=True)
    assert caches_lang_dicts(model_translated, _FakeEnv(prefetch_langs=True)) is False
    untranslated = _FakeField("char")
    assert caches_lang_dicts(untranslated, _FakeEnv(prefetch_langs=True)) is False


def test_caches_lang_dicts_covers_every_per_term_translatable_type():
    for ftype in ("char", "text", "html"):
        field = _FakeField(ftype, translate=_per_term)
        assert caches_lang_dicts(field, _FakeEnv(prefetch_langs=True)) is True, ftype


def test_caches_lang_dicts_is_not_a_type_allowlist():
    assert caches_lang_dicts not in dict(PREDICATES).values()
    assert caches_lang_dicts(_FakeField("some_future_type"), _FakeEnv()) is False
