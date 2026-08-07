from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_sorted_prefetch_langs_shape"


def _identity_translate(callback, value):
    return value


class ResLang(models.AbstractModel):
    _name = "res.lang"
    _module = _MOD
    _description = "res.lang (test stub)"

    def get_installed(self):
        return [("en_US", "English (US)"), ("fr_FR", "French")]


class Doc(models.Model):
    _name = "spl.doc"
    _module = _MOD
    _description = "doc with a per-term-translated body"
    _log_access = False
    _order = "id"

    name = fields.Char()
    body = fields.Text(translate=_identity_translate)


def _make(env):
    return env["spl.doc"].create(
        [
            {"name": "c", "body": "ccc"},
            {"name": "a", "body": "aaa"},
            {"name": "b", "body": "bbb"},
        ]
    )


def test_cache_shape_differs_between_the_two_envs():
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        field = env.registry["spl.doc"]._fields["body"]
        assert callable(field.translate)

        plain = field._get_cache(docs.env)
        raw = field._get_cache(docs.with_context(prefetch_langs=True).env)
        assert type(raw) is not type(plain)
        assert plain.get(docs[0].id) == "ccc"
        assert isinstance(raw.get(docs[0].id), dict)


def test_sorted_under_prefetch_langs_matches_the_plain_env():
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        expected = ["aaa", "bbb", "ccc"]

        assert docs.sorted("body").mapped("body") == expected

        pl = docs.with_context(prefetch_langs=True)
        assert pl.sorted("body").ids == docs.sorted("body").ids
        assert pl.sorted("body", reverse=True).ids == docs.sorted("body").ids[::-1]
        assert pl.sorted("body desc").ids == docs.sorted("body").ids[::-1]


def test_sorted_under_prefetch_langs_multi_key_and_nulls():
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        empty = env["spl.doc"].create({"name": "z"})
        allrecs = (docs + empty).with_context(prefetch_langs=True)

        assert allrecs.sorted("body")._ids[-1] == empty.id
        assert allrecs.sorted("body desc")._ids[0] == empty.id
        assert allrecs.sorted("body, name").ids == allrecs.sorted("body").ids


def test_other_scan_modes_stay_correct_under_prefetch_langs():
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        pl = docs.with_context(prefetch_langs=True)
        assert pl.mapped("body") == ["ccc", "aaa", "bbb"]
        assert set(pl.grouped("body")) == {"aaa", "bbb", "ccc"}
        assert pl.filtered("body").ids == docs.ids
