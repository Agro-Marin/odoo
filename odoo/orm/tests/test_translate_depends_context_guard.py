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
    badge = fields.Char(translate=True, depends_context=("scheme",))
    container_id = fields.Many2one(
        "tcg.container",
        compute="_compute_container_id",
        search="_search_container_id",
    )
    ctx_name_translated = fields.Char(related="container_id.name_translated")
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


def test_stored_translate_strips_extra_context_deps(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="odoo.fields"):
        with model_test_env(Container, Member) as env:
            field = env.registry["tcg.member"]._fields["badge"]
            assert tuple(env.registry.field_depends_context[field]) == ("lang",)
            record = env["tcg.member"].create({"name": "m"})
            record.with_context(scheme="dark").badge = "B"
            assert env.cache_key(field) == ("en_US",)
            assert record.badge == "B"
    assert any("cannot depend on context" in m for m in caplog.messages)


def test_en_us_fallback_with_extra_context_dep():
    with model_test_env(Container, Member) as env:
        base = env["tcg.member"].create({"name": "m"})
        new = base.with_context(scheme="dark").new(origin=base)
        new.label = "Hello"
        assert new.label == "Hello"
        assert new.with_context(lang="fr_FR").label == "Hello"
