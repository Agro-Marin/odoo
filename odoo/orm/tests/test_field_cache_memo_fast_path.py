import functools
import pathlib

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment

_MOD = "test_field_cache_memo_fast_path"

_FIELDS_DIR = pathlib.Path(__file__).resolve().parents[1] / "fields"
_MEMO_READ = '__dict__["_field_cache_memo"]'
_THE_ONE_SITE = "base.py"


class MemoPartner(models.Model):
    _name = "memo.partner"
    _module = _MOD
    _description = "field cache memo probe, comodel"
    _log_access = False

    name = fields.Char()


class MemoThing(models.Model):
    _name = "memo.thing"
    _module = _MOD
    _description = "field cache memo probe"
    _log_access = False

    name = fields.Char()
    qty = fields.Integer()
    partner_id = fields.Many2one("memo.partner")
    blob = fields.Json()


def test_the_memo_is_an_instance_dict_cached_property():
    attr = Environment.__dict__.get("_field_cache_memo")
    assert isinstance(attr, functools.cached_property), (
        "Environment._field_cache_memo is no longer a functools.cached_property "
        f"(got {type(attr).__name__}). The Layer-1 fast path reads it as "
        "env.__dict__['_field_cache_memo'] and silently falls back forever if "
        "that subscript raises."
    )


def test_the_memo_actually_lands_in_the_instance_dict():
    with model_test_env(MemoPartner, MemoThing) as env:
        assert "_field_cache_memo" not in vars(env), (
            "the memo is populated before first access; this test can no "
            "longer tell warm from cold"
        )
        env._field_cache_memo
        assert "_field_cache_memo" in vars(env), (
            "accessing env._field_cache_memo did not write it into the "
            "instance __dict__, so the string-key fast path can never hit"
        )


@pytest.mark.parametrize("fname", ["name", "qty", "partner_id", "blob"])
def test_a_warm_read_does_not_fall_back_to_get_cache(monkeypatch, fname):
    with model_test_env(MemoPartner, MemoThing) as env:
        partner = env["memo.partner"].create({"name": "p"})
        record = env["memo.thing"].create(
            {"name": "x", "qty": 3, "partner_id": partner.id, "blob": {"a": 1}}
        )
        field = record._fields[fname]
        cold = record[fname]
        assert field in env.__dict__["_field_cache_memo"]

        calls = []
        original = fields.Field._get_cache
        monkeypatch.setattr(
            fields.Field,
            "_get_cache",
            lambda self, e: (  # type: ignore[func-returns-value]
                calls.append(self),  # type: ignore[func-returns-value]
                original(self, e),
            )[1],
        )

        warm = record[fname]

        assert warm == cold
        assert calls == [], (
            f"_get_cache was called on a warm read of {fname}, so the fast path "
            "is not being taken"
        )


def test_the_fast_path_is_spelled_once():
    sites = {
        path.relative_to(_FIELDS_DIR).as_posix(): path.read_text(
            encoding="utf-8"
        ).count(_MEMO_READ)
        for path in sorted(_FIELDS_DIR.rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    sites = {rel: n for rel, n in sites.items() if n}
    assert sites == {_THE_ONE_SITE: 1}, (
        f"string-key memo reads: {sites}. The probe lives in _prepare_fast_get "
        "and nowhere else; route a new fast __get__ through it instead of "
        "copying the prologue."
    )
