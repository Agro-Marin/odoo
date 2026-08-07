import sys

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_traversal_translate_fastpath"


def _term_translate(_callback, value):
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
    c = model.create({"name": "", "plain": "3"})
    return model, a, b, c


def test_sorted_by_translated_field_matches_general_path():
    with model_test_env(TransThing) as env:
        _model, a, b, c = _make(env)
        recs = b + a + c
        expected = tuple(r.id for r in sorted(recs, key=lambda r: r.name or ""))
        assert recs.sorted("name")._ids == expected


def test_filtered_by_translated_field_matches_general_path():
    with model_test_env(TransThing) as env:
        _model, a, b, c = _make(env)
        recs = b + a + c
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
