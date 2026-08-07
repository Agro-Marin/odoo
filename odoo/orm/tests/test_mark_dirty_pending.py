import pathlib
import re

from markupsafe import Markup

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_mark_dirty_pending"


class ResLang(models.AbstractModel):
    _name = "res.lang"
    _module = _MOD
    _description = "res.lang stub"

    @api.model
    def _get_data(self, code=None):
        return code in ("en_US", "fr_FR")

    @api.model
    def get_installed(self):
        return [("en_US", "English"), ("fr_FR", "French")]


class Thing(models.Model):
    _name = "x.thing"
    _module = _MOD
    _description = "thing"

    src = fields.Char()
    name_plain = fields.Char(compute="_compute_names", store=True, readonly=False)
    name_trans = fields.Char(
        compute="_compute_names", store=True, readonly=False, translate=True
    )
    body = fields.Html(translate=True, sanitize=False, store=False)

    @api.depends("src")
    def _compute_names(self):
        for record in self:
            value = (record.src or "") + "!"
            record.name_plain = value
            record.name_trans = value


def _write_survives_pending(env, field_name):
    record = env["x.thing"].create({"src": "a"})
    _warm = (record.name_plain, record.name_trans)
    record.write({"src": "b"})
    record.write({field_name: "manual"})
    field = record._fields[field_name]
    assert not env._core.has_pending_field(field) or (
        record.id not in (env._core.pending_ids(field) or ())
    ), f"pending recompute survived an explicit write of {field_name}"
    env.invalidate_all()
    return record[field_name]


def test_explicit_write_survives_pending_compute_plain():
    with model_test_env(ResLang, Thing) as env:
        assert _write_survives_pending(env, "name_plain") == "manual"


def test_explicit_write_survives_pending_compute_translated():
    with model_test_env(ResLang, Thing) as env:
        assert _write_survives_pending(env, "name_trans") == "manual"


def test_html_translate_keeps_en_us_fallback():
    with model_test_env(ResLang, Thing) as env:
        record = env["x.thing"].create({"src": "a"})
        record.body = "<p>hello</p>"
        value = record.body
        assert value == Markup("<p>hello</p>")
        fr_value = record.with_context(lang="fr_FR").body
        assert fr_value == Markup("<p>hello</p>"), (
            f"fr read must fall back to the en_US value, got {fr_value!r}"
        )
        assert isinstance(fr_value, Markup)


def test_every_mark_dirty_override_runs_the_prologue():
    fields_dir = pathlib.Path(__file__).resolve().parent.parent / "fields"
    pattern = re.compile(r"^(\s+)def mark_dirty\(", re.MULTILINE)
    markers = ("_mark_dirty_prologue(", "remove_to_compute(", ".mark_dirty(")
    found = 0
    for path in sorted(fields_dir.rglob("*.py")):
        text = path.read_text()
        for match in pattern.finditer(text):
            indent = match.group(1)
            body_start = match.end()
            rest = text[body_start:]
            end = re.search(rf"^{indent}(?:@|def |[A-Za-z_])", rest, re.MULTILINE)
            body = rest[: end.start()] if end else rest
            found += 1
            assert any(marker in body for marker in markers), (
                f"mark_dirty in {path.name} does not run the prologue"
            )
    assert found >= 6, f"expected the known mark_dirty overrides, found {found}"
