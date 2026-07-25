"""``sorted(field)`` must not key on a raw ``{lang: value}`` cache dict.

The five raw-cache scan modes ask ``models/mixins/_cache_scan.py`` whether a
field's cache value may be used directly; the sixth --
``TraversalMixin._sorted_order_to_function``, the *fallback* Python sort that
runs whenever ``_sorted_by_ids`` bails -- did not, and read
``field._get_cache(env).get(id)`` for every non-boolean, non-property scalar.

That read is shape-dependent, and the shape is a property of the ENVIRONMENT,
not only of the field: ``Field._get_cache`` normally hands a per-term-translated
field a ``LangProxyDict`` view resolving the active language (so the raw value
is a scalar), but ``prefetch_langs=True`` bypasses the view and exposes the raw
``{id: {lang: value}}`` dict (``BaseString._get_cache_impl``).  Sorting then
compared dicts::

    TypeError: '<' not supported between instances of 'dict' and 'dict'

reachable from ordinary code -- ``ir.ui.view.arch_db`` is
``translate=xml_translate``, and ``prefetch_langs=True`` is set by
http_routing, website, html_editor and enterprise callers.

The branch now consults ``caches_lang_dicts(field, env)`` and falls back to
``Field.__get__``, which owns the shape decode.  Guarded here rather than only
in an integration test because the whole point of the seam is that it is
decidable without a database.
"""

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_sorted_prefetch_langs_shape"


def _identity_translate(callback, value):
    """Minimal per-term ``translate`` callable (term-by-term, no rewriting).

    Only its *callability* matters here: it is what routes the field onto the
    ``{lang: value}`` cache layout.
    """
    return value


class ResLang(models.AbstractModel):
    """Minimal ``res.lang`` stub: the prefetch_langs cache-distribution paths
    ask it which languages are installed."""

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
    """Create three docs whose bodies sort differently from their ids."""
    return env["spl.doc"].create(
        [
            {"name": "c", "body": "ccc"},
            {"name": "a", "body": "aaa"},
            {"name": "b", "body": "bbb"},
        ]
    )


def test_cache_shape_differs_between_the_two_envs():
    """Pin the premise: prefetch_langs really does change the cache shape."""
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
    """The regression: sorting must work, and agree with the resolved read."""
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        expected = ["aaa", "bbb", "ccc"]

        assert docs.sorted("body").mapped("body") == expected

        pl = docs.with_context(prefetch_langs=True)
        assert pl.sorted("body").ids == docs.sorted("body").ids
        assert pl.sorted("body", reverse=True).ids == docs.sorted("body").ids[::-1]
        assert pl.sorted("body desc").ids == docs.sorted("body").ids[::-1]


def test_sorted_under_prefetch_langs_multi_key_and_nulls():
    """A composite order and a NULL body keep working through the fallback."""
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        empty = env["spl.doc"].create({"name": "z"})
        allrecs = (docs + empty).with_context(prefetch_langs=True)

        assert allrecs.sorted("body")._ids[-1] == empty.id
        assert allrecs.sorted("body desc")._ids[0] == empty.id
        assert allrecs.sorted("body, name").ids == allrecs.sorted("body").ids


def test_other_scan_modes_stay_correct_under_prefetch_langs():
    """The sibling raw-scan modes already excluded callable-translate; keep it."""
    with model_test_env(ResLang, Doc) as env:
        docs = _make(env)
        pl = docs.with_context(prefetch_langs=True)
        assert pl.mapped("body") == ["ccc", "aaa", "bbb"]
        assert set(pl.grouped("body")) == {"aaa", "bbb", "ccc"}
        assert pl.filtered("body").ids == docs.ids
