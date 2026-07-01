"""Regression: recordset fast paths must not feed a translated cache to Rust.

Per-term-translated char/text fields (``translate=<callable>``) cache their
value as a ``{lang: value}`` dict (a ``LangProxyDict``), not a scalar. The
C-accelerated ``sorted``/``filtered`` scanners require plain-dict scalar values,
so the fast-path type gate must exclude these fields exactly as ``mapped`` and
``grouped`` already do. Before the fix ``sorted``/``filtered`` raised ``TypeError``
on a Rust build. These tests assert the fast paths agree with the general
per-record path. Tier-2 suite: real ``import odoo``, no database.
"""

import sys

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_traversal_translate_fastpath"


def _term_translate(_callback, value):
    """Minimal per-term translate callable (shape of xml_translate)."""
    return value


class TransThing(models.Model):
    _name = "trans.thing"
    _module = _MOD
    _description = "callable-translate char field"

    name = fields.Char(translate=_term_translate)
    plain = fields.Char()


def _make(env):
    model = env["trans.thing"]
    b = model.create({"name": "bbb", "plain": "2"})
    a = model.create({"name": "aaa", "plain": "1"})
    c = model.create({"name": "", "plain": "3"})  # falsy translated value
    return model, a, b, c


def test_sorted_by_translated_field_matches_general_path():
    with model_test_env(TransThing) as env:
        _model, a, b, c = _make(env)
        recs = b + a + c
        # Fast path (was crashing) must equal the naive Python sort.
        expected = tuple(
            r.id for r in sorted(recs, key=lambda r: r.name or "")
        )
        assert recs.sorted("name")._ids == expected


def test_filtered_by_translated_field_matches_general_path():
    with model_test_env(TransThing) as env:
        _model, a, b, c = _make(env)
        recs = b + a + c
        # ``c`` has a falsy name and must be dropped, order preserved.
        got = recs.filtered("name")
        expected = recs.browse(r.id for r in recs if r.name)
        assert got._ids == expected._ids == (b.id, a.id)


def test_mapped_and_grouped_still_agree():
    with model_test_env(TransThing) as env:
        _model, a, b, c = _make(env)
        recs = b + a + c
        assert recs.mapped("name") == [r.name for r in recs]
        grouped = recs.grouped("name")
        assert set(grouped) == {"bbb", "aaa", ""}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
