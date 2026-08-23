"""The cache-scan flags must agree with the conversions they describe.

Until 2026-08-23 these were five frozensets of ``field.type`` strings, and this
file tested them with a ``_FakeField`` carrying a ``type`` attribute and
nothing else. That checked the *tables* and never the *claim*: it could not see
that ``properties`` and ``properties_definition`` were both listed as
truthiness-preserving while neither is, because it never ran a real
``convert_to_record``. Every assertion below goes through the registered field
classes.
"""

import datetime
import decimal
import unittest

from odoo import fields, models
from odoo.orm.fields.base import Field
from odoo.orm.fields.misc import Id
from odoo.orm.model_test_env import model_test_env
from odoo.orm.models.mixins._cache_scan import (
    caches_lang_dicts,
    can_scan_identity,
    can_scan_read,
    can_scan_sorted,
    can_scan_truthy,
)

_MOD = "test_cache_scan_allowlists"

SCAN_FLAGS = (
    "cache_is_record_value",
    "cache_truthiness_matches",
    "cache_is_orderable",
    "cache_is_read_value",
)

PREDICATES = {
    "cache_is_record_value": can_scan_identity,
    "cache_truthiness_matches": can_scan_truthy,
    "cache_is_orderable": can_scan_sorted,
    "cache_is_read_value": can_scan_read,
}

SAMPLES: dict[str, list] = {
    "boolean": [None, True, False],
    "integer": [None, 0, 5, -3],
    "float": [None, 0.0, 1.5, -2.25],
    "monetary": [None, 0.0, decimal.Decimal("1.50")],
    "char": [None, "", "a"],
    "text": [None, "", "a\nb"],
    "html": [None, "", "<p>x</p>"],
    "json": [None, {}, [], {"a": 1}],
    "date": [None, datetime.date(2020, 1, 1)],
    "datetime": [None, datetime.datetime(2020, 1, 1, 12, 30)],
    "selection": [None, "", "draft"],
    "binary": [None, b"", b"xx"],
    "reference": [None, "", "res.users,1"],
    "many2one_reference": [None, 0, 1],
}
"""Cache-shaped values per registered type.

``properties`` and ``properties_definition`` are absent on purpose: both need a
definition record to convert at all, and both declare every flag False, so the
"claims it, therefore it holds" direction below has nothing to check. That they
*fail* the claim is pinned where a definition exists, in
``test_orm/tests/test_cache_scan_equivalence.py``.
"""


class SHost(models.Model):
    _name = "s.host"
    _module = _MOD
    _description = "Scan flag host"

    name = fields.Char()


def _a_record():
    with model_test_env(SHost) as env:
        return env["s.host"].create({"name": "x"})


def _unbound(cls) -> Field:
    """A field instance with no setup, for calling the converters directly."""
    field = object.__new__(cls)
    field.translate = False
    field.store = True
    return field


class TestTheFlagsAreDeclared(unittest.TestCase):
    def test_the_registry_is_populated(self):
        self.assertGreaterEqual(
            len(Field._by_type__),
            15,
            "Field._by_type__ is unexpectedly small; the field modules may not "
            "have been imported, which would make every assertion below vacuous",
        )

    def test_the_base_class_grants_nothing(self):
        for flag in SCAN_FLAGS:
            with self.subTest(flag=flag):
                self.assertIs(
                    getattr(Field, flag),
                    False,
                    f"Field.{flag} must default to False so a field type that "
                    f"says nothing gets no fast path",
                )

    def test_every_flag_is_claimed_by_someone(self):
        for flag in SCAN_FLAGS:
            with self.subTest(flag=flag):
                claimants = [
                    name
                    for name, cls in Field._by_type__.items()
                    if getattr(cls, flag, False)
                ]
                self.assertTrue(
                    claimants,
                    f"no registered field type claims {flag}; either every "
                    f"override was lost or the fast path is now dead code",
                )

    def test_id_declares_its_own_flags_rather_than_riding_a_type_string(self):
        # Id carries type = "integer" but subclasses Field, not Integer. Under
        # the old type-string tables it silently inherited Integer's entries;
        # under class attributes it has to say so itself, or `sorted("id")` and
        # `read(["id"])` quietly lose their fast path.
        for flag in SCAN_FLAGS:
            with self.subTest(flag=flag):
                self.assertTrue(
                    getattr(Id, flag, False),
                    f"Id.{flag} is False; the id field lost a scan it used to "
                    f"get through `type == 'integer'`",
                )


class TestTheFlagsMatchTheConversions(unittest.TestCase):
    """Each flag is a claim about the converters. Run them and check it."""

    @classmethod
    def setUpClass(cls):
        cls.record = _a_record()

    def _samples(self, type_name):
        samples = SAMPLES.get(type_name)
        if samples is None:
            self.skipTest(f"no cache-shaped samples for {type_name!r}")
        return samples

    def test_identity_claimants_return_the_cached_value(self):
        for type_name, cls in sorted(Field._by_type__.items()):
            if not cls.cache_is_record_value:
                continue
            with self.subTest(type=type_name):
                field = _unbound(cls)
                for value in self._samples(type_name):
                    if value is None:
                        continue
                    got = field.convert_to_record(value, self.record)
                    self.assertEqual(
                        got,
                        value,
                        f"{cls.__name__} claims cache_is_record_value but "
                        f"convert_to_record({value!r}) returned {got!r}",
                    )

    def test_truthiness_claimants_preserve_truthiness(self):
        for type_name, cls in sorted(Field._by_type__.items()):
            if not cls.cache_truthiness_matches:
                continue
            with self.subTest(type=type_name):
                field = _unbound(cls)
                for value in self._samples(type_name):
                    got = field.convert_to_record(value, self.record)
                    self.assertEqual(
                        bool(got),
                        bool(value),
                        f"{cls.__name__} claims cache_truthiness_matches but "
                        f"bool({value!r}) is {bool(value)} while the record "
                        f"value {got!r} is {bool(got)}; filtered({type_name!r}) "
                        f"would disagree with reading the field",
                    )

    def test_read_claimants_round_trip(self):
        for type_name, cls in sorted(Field._by_type__.items()):
            if not cls.cache_is_read_value:
                continue
            with self.subTest(type=type_name):
                field = _unbound(cls)
                none_value = field.convert_to_record(None, self.record)
                for value in self._samples(type_name):
                    expected = none_value if value is None else value
                    got = field.convert_to_read(
                        field.convert_to_record(value, self.record), self.record
                    )
                    self.assertEqual(
                        got,
                        expected,
                        f"{cls.__name__} claims cache_is_read_value but the "
                        f"cached {value!r} reads as {got!r}; _read_format's "
                        f"scan branch hands out the cached value",
                    )

    def test_orderable_claimants_are_mutually_comparable(self):
        for type_name, cls in sorted(Field._by_type__.items()):
            if not cls.cache_is_orderable:
                continue
            with self.subTest(type=type_name):
                values = [v for v in self._samples(type_name) if v is not None]
                try:
                    sorted(values)
                except TypeError as exc:
                    self.fail(
                        f"{cls.__name__} claims cache_is_orderable but its "
                        f"cached values do not sort: {exc}"
                    )

    def test_relational_types_claim_nothing(self):
        for type_name in ("many2one", "one2many", "many2many"):
            cls = Field._by_type__[type_name]
            for flag in SCAN_FLAGS:
                with self.subTest(type=type_name, flag=flag):
                    self.assertFalse(
                        getattr(cls, flag),
                        f"{cls.__name__}.{flag} would let a scan hand out ids "
                        f"where a recordset is expected",
                    )


class TestNoFlagLeaksThroughAResetType(unittest.TestCase):
    """A subclass that changes its conversions must not inherit the claim.

    ``Reference`` subclasses ``Selection``, ``Many2oneReference`` subclasses
    ``Integer`` and ``Html`` subclasses ``BaseString`` -- each keeps the
    parent's storage and changes what ``convert_to_record`` hands back. Under
    the old tables the distinct ``type`` string told them apart by accident;
    a class attribute is inherited, so each has to reset what it no longer
    honours.
    """

    KNOWN_RESETS = (
        ("reference", "Selection"),
        ("many2one_reference", "Integer"),
    )

    def test_the_hazard_shape_still_exists(self):
        for type_name, parent_name in self.KNOWN_RESETS:
            with self.subTest(type=type_name):
                cls = Field._by_type__[type_name]
                self.assertIn(
                    parent_name,
                    [c.__name__ for c in cls.__mro__],
                    f"{type_name} no longer subclasses {parent_name}; this "
                    f"test is now checking nothing",
                )

    def test_a_reset_type_does_not_inherit_a_flag_it_breaks(self):
        for type_name, _parent in self.KNOWN_RESETS:
            cls = Field._by_type__[type_name]
            for flag in ("cache_is_record_value", "cache_is_orderable"):
                with self.subTest(type=type_name, flag=flag):
                    self.assertFalse(
                        getattr(cls, flag),
                        f"{cls.__name__} inherits {flag} from a parent whose "
                        f"conversions it replaced",
                    )

    def test_html_does_not_inherit_char_identity(self):
        html = Field._by_type__["html"]
        self.assertFalse(
            html.cache_is_record_value,
            "Html wraps its value in Markup; the cached str is not the record value",
        )
        self.assertTrue(
            html.cache_truthiness_matches,
            "Markup(x) is falsy exactly when x is; filtered('html_field') "
            "keeps its fast path",
        )


class TestInstanceLevelGuards(unittest.TestCase):
    def test_a_callable_translate_disables_every_scan(self):
        char = fields.Char(translate=lambda callback, value: value)
        char.translate = lambda callback, value: value
        char.store = True
        for name, predicate in PREDICATES.items():
            with self.subTest(flag=name):
                self.assertFalse(
                    predicate(char),
                    f"{name} admitted a per-term translated field, whose cache "
                    f"holds a dict of terms rather than the value",
                )

    def test_a_model_level_translate_keeps_its_scans(self):
        char = fields.Char()
        char.translate = True
        char.store = True
        self.assertTrue(can_scan_identity(char))
        self.assertTrue(can_scan_read(char))

    def test_read_still_requires_store(self):
        char = fields.Char()
        char.translate = False
        char.store = False
        self.assertFalse(can_scan_read(char))
        char.store = True
        self.assertTrue(can_scan_read(char))

    def test_caches_lang_dicts_needs_both_halves(self):
        def per_term(_callback, value):
            return value

        class _Env:
            def __init__(self, **context):
                self.context = context

        field = fields.Text()
        field.translate = per_term
        self.assertTrue(caches_lang_dicts(field, _Env(prefetch_langs=True)))
        self.assertFalse(caches_lang_dicts(field, _Env()))
        field.translate = True
        self.assertFalse(caches_lang_dicts(field, _Env(prefetch_langs=True)))


if __name__ == "__main__":
    unittest.main()
