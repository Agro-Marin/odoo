"""The `env.__dict__["_field_cache_memo"]` fast path must stay fast.

Four Layer-1 hot paths read the memo by **string key** off the instance dict to
skip a descriptor call::

    try:
        field_cache = env.__dict__["_field_cache_memo"][self]
    except KeyError:
        field_cache = self._get_cache(env)

(`fields/base.py:1027,1393`, `fields/textual.py:76`,
`fields/relational/many2one.py:54`.)

It works only because `Environment._field_cache_memo` is a
`functools.cached_property`, which writes into the instance `__dict__` on first
access. Make it a slot, a plain attribute, or rename it, and the subscript
raises `KeyError` -- which the `except KeyError` above **catches**, because that
clause already exists for the ordinary "no entry for this field yet" miss. The
two are indistinguishable at the call site, so the fast path degrades to a
permanent slow path and nothing fails: not ruff, not the test suite, and not
`env_surface_check`, which validates that the name *exists* on `Environment`
(it would, as a slot) but not that this access *reaches* it.

That is the whole gap these tests close: existence is already gated, use is not.
"""

import functools

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment

_MOD = "test_field_cache_memo_fast_path"

#: The four sites, so a moved fast path is noticed rather than silently dropped.
_FAST_PATH_SITES = (
    ("orm/fields/base.py", 2),
    ("orm/fields/textual.py", 1),
    ("orm/fields/relational/many2one.py", 1),
)


class MemoThing(models.Model):
    _name = "memo.thing"
    _module = _MOD
    _description = "field cache memo probe"
    _log_access = False

    name = fields.Char()


def test_the_memo_is_an_instance_dict_cached_property():
    """The precondition the subscript depends on.

    A slot or a plain class attribute would keep `env._field_cache_memo`
    working and make `env.__dict__["_field_cache_memo"]` raise forever.
    """
    attr = Environment.__dict__.get("_field_cache_memo")
    assert isinstance(attr, functools.cached_property), (
        "Environment._field_cache_memo is no longer a functools.cached_property "
        f"(got {type(attr).__name__}). Four Layer-1 hot paths read it as "
        "env.__dict__['_field_cache_memo'] and silently fall back forever if "
        "that subscript raises."
    )


def test_the_memo_actually_lands_in_the_instance_dict():
    with model_test_env(MemoThing) as env:
        assert "_field_cache_memo" not in vars(env), (
            "the memo is populated before first access; this test can no "
            "longer tell warm from cold"
        )
        env._field_cache_memo
        assert "_field_cache_memo" in vars(env), (
            "accessing env._field_cache_memo did not write it into the "
            "instance __dict__, so the string-key fast path can never hit"
        )


def test_a_warm_read_does_not_fall_back_to_get_cache(monkeypatch):
    """The behavioural assertion: the fast path is *taken*, not merely available.

    `_get_cache` is the fallback. Once the memo holds an entry for the field,
    reading through it must not call `_get_cache` at all -- if it does, the
    subscript is missing and every read is paying the slow path.
    """
    with model_test_env(MemoThing) as env:
        model = env["memo.thing"]
        field = model._fields["name"]

        # Warm the memo the way production does.
        field._get_cache(env)
        assert field in env.__dict__["_field_cache_memo"]

        calls = []
        original = type(field)._get_cache
        monkeypatch.setattr(
            type(field),
            "_get_cache",
            lambda self, e: (calls.append(self), original(self, e))[1],
        )

        # Exactly what the hot paths do.
        field_cache = env.__dict__["_field_cache_memo"][field]

        assert field_cache is not None
        assert calls == [], (
            "_get_cache was called on a warm read, so the fast path is not being taken"
        )


@pytest.mark.parametrize(("relpath", "expected"), _FAST_PATH_SITES)
def test_the_fast_path_sites_are_where_we_think(relpath, expected):
    """If a site moves or is deleted, this file's premise needs re-checking.

    Not a prohibition -- removing a fast path is fine. But it should be a
    decision, and the count above should move with it.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    source = (root / relpath).read_text(encoding="utf-8")
    found = source.count('__dict__["_field_cache_memo"]')
    assert found == expected, (
        f"{relpath} has {found} string-key memo reads, expected {expected}. "
        "Update _FAST_PATH_SITES in the same commit."
    )
