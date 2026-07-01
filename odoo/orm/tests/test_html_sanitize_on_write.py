"""Regression: a validated Html write always sanitizes.

The old fast path skipped ``html_sanitize`` when the written value equalled the
cached one, trusting it as "already sanitized on a previous write". But the cache
is also filled from raw DB reads, so a value stored before a sanitize-rule change
/ via SQL / by a migration was trusted forever, and on a multi-record write only
the first record's cache was the witness for the whole batch. Tier-2 suite: real
``import odoo``, no database.
"""

import sys

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_html_sanitize_on_write"

_POISON = "<script>alert(1)</script><p>hello</p>"


class HtmlDoc(models.Model):
    _name = "html.doc"
    _module = _MOD
    _description = "html sanitize model"

    body = fields.Html()


def test_write_sanitizes_even_when_cache_holds_unsanitized_value():
    with model_test_env(HtmlDoc) as env:
        model = env["html.doc"]
        r1 = model.create({"body": "<p>ok</p>"})
        r2 = model.create({"body": "<p>ok</p>"})
        field = model._fields["body"]
        # simulate a raw / stale DB value reaching the cache unsanitized
        field._get_cache(env)[r1.id] = _POISON
        # the first record's cache must not be a trusted witness for the batch
        (r1 + r2).write({"body": _POISON})
        assert "<script>" not in (r1.body or "")
        assert "<script>" not in (r2.body or "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
