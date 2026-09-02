import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.tools.translate import html_translate

_MOD = "test_lang_proxy_contract"


class ResLang(models.Model):
    _name = "res.lang"
    _module = _MOD
    _description = "res.lang stub"

    name = fields.Char()
    code = fields.Char()

    def _get_data(self, code):
        return code == "en_US"


class Doc(models.Model):
    _name = "lpc.doc"
    _module = _MOD
    _description = "Doc"
    _log_access = False

    name = fields.Char()
    body = fields.Html(translate=html_translate)


@pytest.fixture
def env():
    gen = model_test_env(ResLang, Doc)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def _proxy(env, record):
    field = record._fields["body"]
    return field._get_cache(env)


def test_two_records_updated_from_one_dict_do_not_share_cache(env):
    doc_a = env["lpc.doc"].create({"name": "a"})
    doc_b = env["lpc.doc"].create({"name": "b"})
    field = doc_a._fields["body"]
    shared = {"en_US": "<p>same</p>"}
    pl_env = env(context={"prefetch_langs": True})
    field._update_cache(doc_a.with_env(pl_env), shared)
    field._update_cache(doc_b.with_env(pl_env), shared)

    proxy = _proxy(env, doc_a)
    proxy[doc_a.id] = "<p>changed</p>"
    assert _proxy(env, doc_b)[doc_b.id] == "<p>same</p>", (
        "the single-record cache write stored the caller's dict by reference; "
        "a later per-language write on one record leaked into the other"
    )


def test_deleting_a_stored_null_entry_evicts_it(env):
    doc = env["lpc.doc"].create({"name": "a"})
    proxy = _proxy(env, doc)
    proxy._cache[doc.id] = None
    assert doc.id in set(proxy)
    del proxy[doc.id]
    assert doc.id not in set(proxy)


def test_deleting_a_missing_key_raises(env):
    doc = env["lpc.doc"].create({"name": "a"})
    proxy = _proxy(env, doc)
    with pytest.raises(KeyError):
        del proxy[999999]
    assert proxy.pop(999999, None) is None
