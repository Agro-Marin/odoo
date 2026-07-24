"""``_mark_dirty_model_term_translation`` must survive legacy jsonb rows that
lack the ``en_US`` key (SQL-migrated data): it used to KeyError on
``old_translations["en_US"]`` and abort the whole write.
"""

from unittest.mock import patch

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_term_translation_missing_en_us"


def _whole_value_translate(callback, value):
    """Minimal callable-translate: the whole value is a single term."""
    if not value:
        return value
    return callback(value) or value


class ResLang(models.AbstractModel):
    _name = "res.lang"
    _module = _MOD
    _description = "res.lang stub"

    def _get_data(self, code=None, **kwargs):
        # en_US active, like a standard database
        return code == "en_US"


class Doc(models.Model):
    _name = "ttl.doc"
    _module = _MOD
    _description = "doc"
    _log_access = False

    name = fields.Char()
    body = fields.Text(translate=_whole_value_translate)


def test_write_over_legacy_row_without_en_us():
    with model_test_env(ResLang, Doc) as env:
        doc = env["ttl.doc"].create({"name": "d"})
        field = doc._fields["body"]
        # a migrated jsonb row carrying only a non-en_US translation
        legacy = {"fr_FR": "Bonjour"}
        with patch.object(field, "_get_stored_translations", return_value=legacy):
            # used to raise KeyError: 'en_US'
            field._mark_dirty_model_term_translation(doc, "Hello", "de_DE")
        cache = field._get_cache(doc.with_context(prefetch_langs=True).env)
        assert cache[doc.id] == {"fr_FR": "Hello", "de_DE": "Hello"}
