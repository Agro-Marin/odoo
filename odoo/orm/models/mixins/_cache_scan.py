"""When a scan may read the raw cache value instead of the record value.

``mapped()``, ``filtered()``, ``grouped()``, ``sorted()`` and ``_read_format()``
all have a fast path that reads ``field._get_cache(env)`` directly and skips
``convert_to_record`` / ``convert_to_read``. That is only sound for a field
whose cache value stands in for its record value *in the way that scan needs*,
and the four predicates below name the four ways.

Until 2026-08-23 this was five frozensets of ``field.type`` strings. Three
things were wrong with that, and all three had actually happened:

* **It admitted the wrong classes.** ``Many2oneReference`` subclasses
  ``Integer`` and ``Reference`` subclasses ``Selection``; both keep their own
  ``type``, so the string tables told them apart, but nothing said that is what
  the tables were for. ``Id`` is the mirror case -- it carries
  ``type = "integer"`` while subclassing ``Field`` directly, so it rode
  ``Integer``'s entries with no declaration anywhere.
* **It encoded an invariant nothing checked.** ``properties`` and
  ``properties_definition`` were both listed as truthiness-preserving and
  neither is; see the attributes on those classes for what each actually does.
  ``tests/test_cache_scan_allowlists.py`` tested the *mechanics* of the tables
  with a fake field carrying nothing but a type string, so it could not see it.
* **It withheld a fast path for no reason.** ``boolean`` was absent from the
  sortable table although the sorter handles booleans correctly.

The answers are now class attributes declared beside the ``convert_to_record``
they describe (``Field.cache_is_record_value`` and its three siblings), so a
new field type states its own case and a subclass inherits the answer that
belongs to its conversions. ``orm/tests/test_cache_scan_allowlists.py`` checks
every registered class against its real conversions rather than against a fake.

The ``translate`` half stays here because it is per-*instance*, not per-class:
the same ``Char`` is scannable or not depending on whether it was declared
``translate=<callable>``, whose cache holds a per-term dict rather than a
string.
"""

import typing

if typing.TYPE_CHECKING:
    from ...fields.base import Field
    from ...runtime import Environment


def caches_lang_dicts(field: Field, env: Environment) -> bool:
    return callable(field.translate) and bool(env.context.get("prefetch_langs"))


def can_scan_identity(field: Field) -> bool:
    """The cache value *is* the record value, apart from ``None``."""
    return field.cache_is_record_value and not callable(field.translate)


def can_scan_truthy(field: Field) -> bool:
    """``bool(cache value)`` answers ``bool(record value)``."""
    return field.cache_truthiness_matches and not callable(field.translate)


def can_scan_sorted(field: Field) -> bool:
    """Cache values order the records the way the record values would."""
    return field.cache_is_orderable and not callable(field.translate)


def can_scan_read(field: Field) -> bool:
    """The cache value is what ``read()`` should return."""
    return field.store and field.cache_is_read_value and not callable(field.translate)
