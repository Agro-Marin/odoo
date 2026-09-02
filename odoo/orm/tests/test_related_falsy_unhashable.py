import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_related_falsy_unhashable"


class JsonSource(models.Model):
    _name = "json.source"
    _module = _MOD
    _description = "Json Source"

    data = fields.Json()


class JsonMirror(models.Model):
    _name = "json.mirror"
    _module = _MOD
    _description = "Json Mirror"

    source_id = fields.Many2one("json.source")
    data = fields.Json(related="source_id.data")


@pytest.fixture
def env():
    gen = model_test_env(JsonSource, JsonMirror)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_a_falsy_related_json_batch_computes_correctly(env):
    # {} normalises to False before the falsy grouping, so no shipped field
    # type reaches the unhashable-key path today; the guard in
    # _compute_related is parity with _inverse_related, and this pins the
    # observable batch behaviour around it
    sources = env["json.source"].create(
        [{"data": {}}, {"data": {}}, {"data": {"k": 1}}]
    )
    mirrors = env["json.mirror"].create(
        [{"source_id": source.id} for source in sources]
    )
    # a falsy Json normalises to False in cache; the point is that computing
    # the related batch neither crashes on the unhashable {} nor loses the
    # truthy value
    assert [m.data for m in mirrors] == [False, False, {"k": 1}]
