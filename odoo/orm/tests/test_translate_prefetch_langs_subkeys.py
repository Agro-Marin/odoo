from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_translate_prefetch_subkeys"


class ResLang(models.AbstractModel):
    _name = "res.lang"
    _module = _MOD
    _description = "res.lang (test stub)"

    def get_installed(self):
        return [
            ("en_US", "English (US)"),
            ("fr_FR", "French"),
            ("es_ES", "Spanish"),
        ]


class Container(models.Model):
    _name = "tpls.container"
    _module = _MOD
    _description = "container"
    _log_access = False

    name = fields.Char()
    name_translated = fields.Char(translate=True)


class Member(models.Model):
    _name = "tpls.member"
    _module = _MOD
    _description = "member"
    _log_access = False

    name = fields.Char()
    label = fields.Char(translate=True, store=False, depends_context=("scheme",))


def test_lang_cache_key_follows_real_cache_key():
    with model_test_env(ResLang, Container, Member) as env:
        field = env.registry["tpls.member"]._fields["label"]
        ctx_env = env(context={"scheme": "dark"})
        assert field._lang_cache_key(ctx_env, "en_US") == ("en_US", "dark")
        assert field._lang_cache_key(ctx_env, "fr_FR") == ("fr_FR", "dark")
        plain = env.registry["tpls.container"]._fields["name_translated"]
        assert plain._lang_cache_key(env, "en_US") == ("en_US",)
        assert plain._lang_cache_key(env, "fr_FR") == ("fr_FR",)


def test_update_cache_dict_distributes_into_full_shaped_subcaches():
    with model_test_env(ResLang, Container, Member) as env:
        record = env["tpls.member"].create({"name": "m"})
        field = env.registry["tpls.member"]._fields["label"]
        dark = record.with_context(scheme="dark")
        field._update_cache(dark, {"en_US": "Hello", "fr_FR": "Bonjour"})
        field_data = env._core.get_field_data(field)
        assert ("en_US", "dark") in field_data
        assert ("fr_FR", "dark") in field_data
        assert ("en_US",) not in field_data
        assert ("fr_FR",) not in field_data
        assert dark.label == "Hello"
        assert dark.with_context(lang="fr_FR").label == "Bonjour"


def test_insert_cache_prefetch_langs_distributes_into_full_shaped_subcaches():
    with model_test_env(ResLang, Container, Member) as env:
        record = env["tpls.member"].create({"name": "m"})
        field = env.registry["tpls.member"]._fields["label"]
        dark = record.with_context(scheme="dark", prefetch_langs=True)
        field._insert_cache(dark, [{"en_US": "Hello", "fr_FR": "Bonjour"}])
        field_data = env._core.get_field_data(field)
        assert ("en_US", "dark") in field_data
        assert ("fr_FR", "dark") in field_data
        assert ("es_ES", "dark") in field_data
        assert all(len(key) == 2 for key in field_data)
        base = record.with_context(scheme="dark")
        assert base.label == "Hello"
        assert base.with_context(lang="fr_FR").label == "Bonjour"
        assert base.with_context(lang="es_ES").label == "Hello"


def test_insert_cache_prefetch_langs_none_value_full_shaped():
    with model_test_env(ResLang, Container, Member) as env:
        record = env["tpls.member"].create({"name": "m"})
        field = env.registry["tpls.member"]._fields["label"]
        dark = record.with_context(scheme="dark", prefetch_langs=True)
        field._insert_cache(dark, [None])
        field_data = env._core.get_field_data(field)
        assert all(len(key) == 2 for key in field_data)
        for lang in ("en_US", "fr_FR", "es_ES"):
            assert field_data[(lang, "dark")][record.id] is None


def test_plain_lang_field_keys_stay_1tuples():
    with model_test_env(ResLang, Container, Member) as env:
        record = env["tpls.container"].create({"name": "c"})
        field = env.registry["tpls.container"]._fields["name_translated"]
        field._update_cache(record, {"en_US": "Hello", "fr_FR": "Bonjour"})
        field_data = env._core.get_field_data(field)
        assert ("en_US",) in field_data
        assert ("fr_FR",) in field_data
        assert all(len(key) == 1 for key in field_data)
        assert record.name_translated == "Hello"
        assert record.with_context(lang="fr_FR").name_translated == "Bonjour"
        other = env["tpls.container"].create({"name": "c2"})
        field._insert_cache(other.with_context(prefetch_langs=True), [{"en_US": "Hi"}])
        assert all(len(key) == 1 for key in field_data)
        assert other.with_context(lang="es_ES").name_translated == "Hi"
