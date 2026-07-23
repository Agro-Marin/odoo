"""``translate=True`` prefetch_langs distribution writes full-shaped sub-keys.

The model-translation cache layout is one flat ``{id: value}`` sub-dict per
(lang + extra context) key, and *reads* always key by the full
``env.cache_key(field)`` (see ``Field._get_cache_impl``).  The prefetch_langs
distribution paths — ``BaseString._insert_cache`` (SQL fetched the whole JSONB)
and ``BaseString._update_cache`` (a ``{lang: scalar}`` cache value) — used to
build bare ``(lang,)`` 1-tuple sub-keys by hand: for a translated field with an
extra context dependency they populated dead sub-caches no read ever consults.
Both now derive their keys through ``BaseString._lang_cache_key`` — the same
machinery as the en_US fallback key — i.e. the full cache key with the lang
component (always first, normalized by ``get_depends``) swapped.

For plain ``('lang',)`` fields the keys remain the exact 1-tuples they always
were.
"""

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_translate_prefetch_subkeys"


class ResLang(models.AbstractModel):
    """Minimal ``res.lang`` stub: ``_insert_cache``'s prefetch_langs branch
    asks it which languages are installed."""

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
    # plain translated field: depends_context resolves to exactly ('lang',)
    name_translated = fields.Char(translate=True)


class Member(models.Model):
    _name = "tpls.member"
    _module = _MOD
    _description = "member"
    _log_access = False

    name = fields.Char()
    # non-stored plain translated field with an explicit extra context dep
    # (same idiom as test_translate_depends_context_guard)
    label = fields.Char(translate=True, store=False, depends_context=("scheme",))


def test_lang_cache_key_follows_real_cache_key():
    with model_test_env(ResLang, Container, Member) as env:
        field = env.registry["tpls.member"]._fields["label"]
        ctx_env = env(context={"scheme": "dark"})
        assert field._lang_cache_key(ctx_env, "en_US") == ("en_US", "dark")
        assert field._lang_cache_key(ctx_env, "fr_FR") == ("fr_FR", "dark")
        # plain ('lang',) field: byte-identical 1-tuples
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
        # sub-keys carry the extra context component, never a bare 1-tuple
        assert ("en_US", "dark") in field_data
        assert ("fr_FR", "dark") in field_data
        assert ("en_US",) not in field_data
        assert ("fr_FR",) not in field_data
        # round-trip: the normal read path (env.cache_key keyed) finds them
        assert dark.label == "Hello"
        assert dark.with_context(lang="fr_FR").label == "Bonjour"


def test_insert_cache_prefetch_langs_distributes_into_full_shaped_subcaches():
    with model_test_env(ResLang, Container, Member) as env:
        record = env["tpls.member"].create({"name": "m"})
        field = env.registry["tpls.member"]._fields["label"]
        dark = record.with_context(scheme="dark", prefetch_langs=True)
        # SQL-shaped value: the whole JSONB dict, es_ES missing on purpose
        field._insert_cache(dark, [{"en_US": "Hello", "fr_FR": "Bonjour"}])
        field_data = env._core.get_field_data(field)
        assert ("en_US", "dark") in field_data
        assert ("fr_FR", "dark") in field_data
        assert ("es_ES", "dark") in field_data  # filled from the en_US fallback
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
    # Behavior guard: for the overwhelmingly common ('lang',) shape the
    # distribution keys must remain the exact bare 1-tuples.
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
