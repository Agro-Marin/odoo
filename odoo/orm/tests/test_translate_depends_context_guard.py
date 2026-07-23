"""``translate=True`` fields with extra context dependencies: the language is
normalized FIRST in the cache key, and the en_US fallback key is derived from
the real cache-key machinery.

The model-translation cache layout is one flat ``{id: value}`` sub-dict per
(lang + extra context) key.  Extra context deps are legitimate (e.g. a
translated field related through a ``depends_context`` compute, mirrored from
``test_orm.compute.member``), but two consumers must single out the lang
component; both used to hard-code a ``(lang,)`` 1-tuple:

* the en_US fallback for no-DB-row records probed a dead ``("en_US",)`` key
  that a normal cache write (which keys by the FULL context) never populates,
  so cross-language fallback silently returned nothing;
* ``get_column_update`` read ``cache_key[0]`` as the language, which held an
  arbitrary context component when 'lang' was not first.
"""

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_translate_ctx_guard"


class Container(models.Model):
    _name = "tcg.container"
    _module = _MOD
    _description = "container"
    _log_access = False

    name = fields.Char()
    name_translated = fields.Char(translate=True)


class Member(models.Model):
    _name = "tcg.member"
    _module = _MOD
    _description = "member"
    _log_access = False

    name = fields.Char()
    container_id = fields.Many2one(
        "tcg.container",
        compute="_compute_container_id",
        search="_search_container_id",  # searchable: silence the resolve warning
    )
    # translated related through a context-dependent compute: its
    # depends_context legitimately resolves to lang + uid
    ctx_name_translated = fields.Char(related="container_id.name_translated")
    # non-stored plain translated field with an explicit extra context dep
    label = fields.Char(translate=True, store=False, depends_context=("scheme",))

    @api.depends_context("uid")
    def _compute_container_id(self):
        for record in self:
            record.container_id = False

    def _search_container_id(self, operator, value):
        return []


def test_plain_translate_field_resolves_to_lang_only():
    with model_test_env(Container, Member) as env:
        field = env.registry["tcg.container"]._fields["name_translated"]
        assert tuple(env.registry.field_depends_context[field]) == ("lang",)


def test_extra_depends_context_is_lang_first():
    with model_test_env(Container, Member) as env:
        registry = env.registry
        # the related chain yields ('uid', 'lang'); normalization puts lang first
        related = registry["tcg.member"]._fields["ctx_name_translated"]
        assert tuple(registry.field_depends_context[related]) == ("lang", "uid")
        explicit = registry["tcg.member"]._fields["label"]
        assert tuple(registry.field_depends_context[explicit]) == ("lang", "scheme")


def test_fallback_key_follows_real_cache_key():
    with model_test_env(Container, Member) as env:
        env = env(context={"scheme": "dark"})
        field = env.registry["tcg.member"]._fields["label"]
        cache_key = env.cache_key(field)
        assert cache_key == ("en_US", "dark")
        assert field._lang_fallback_cache_key(env) == ("en_US", "dark")
        fr_env = env(context={"scheme": "dark", "lang": "fr_FR"})
        assert fr_env.cache_key(field) == ("fr_FR", "dark")
        assert field._lang_fallback_cache_key(fr_env) == ("en_US", "dark")


def test_en_us_fallback_with_extra_context_dep():
    # A no-DB-row record written in en_US must be readable from another
    # language via the fallback — previously the fallback probed the dead
    # ("en_US",) key and found nothing.
    with model_test_env(Container, Member) as env:
        base = env["tcg.member"].create({"name": "m"})
        new = base.with_context(scheme="dark").new(origin=base)
        new.label = "Hello"
        assert new.label == "Hello"
        assert new.with_context(lang="fr_FR").label == "Hello"
