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
        field._get_cache(env)[r1.id] = _POISON
        (r1 + r2).write({"body": _POISON})
        assert "<script>" not in (r1.body or "")
        assert "<script>" not in (r2.body or "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
