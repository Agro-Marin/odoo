from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_unlink_invalidates_reference_readers"


class Target(models.Model):
    _name = "uirr.target"
    _module = _MOD
    _description = "the referenced record"
    _log_access = False

    name = fields.Char()


class Pointer(models.Model):
    _name = "uirr.pointer"
    _module = _MOD
    _description = "reads a record chosen at runtime"
    _log_access = False

    res_model = fields.Char()
    res_id = fields.Many2oneReference(model_field="res_model")
    res_name = fields.Char(compute="_compute_res_name")
    res_name_stored = fields.Char(compute="_compute_res_name_stored", store=True)

    @api.depends("res_model", "res_id")
    def _compute_res_name(self):
        for record in self:
            target = self.env[record.res_model or ""].browse(record.res_id)
            record.res_name = target.exists()["name"] or False

    ref = fields.Reference(selection=[("uirr.target", "Target")])
    ref_name = fields.Char(compute="_compute_ref_name")

    @api.depends("res_model", "res_id")
    def _compute_res_name_stored(self):
        for record in self:
            record.res_name_stored = record.res_id and "stored"

    @api.depends("ref")
    def _compute_ref_name(self):
        for record in self:
            record.ref_name = (
                record.ref.exists().name if record.ref else False  # type: ignore[attr-defined]
            )


class Counter(models.Model):
    _name = "uirr.counter"
    _module = _MOD
    _description = "counts targets through a search"
    _log_access = False

    target_count = fields.Integer(compute="_compute_target_count")

    def _compute_target_count(self):
        for record in self:
            record.target_count = self.env["uirr.target"].search_count([])


class Bystander(models.Model):
    _name = "uirr.bystander"
    _module = _MOD
    _description = "unrelated to the pointer in every index"
    _log_access = False

    name = fields.Char()


def _env():
    return model_test_env(Target, Pointer, Counter, Bystander)


def _pointer_res_name(env):
    return env["uirr.pointer"]._fields["res_name"]


def test_the_delete_sweep_drops_a_reference_readers_cache():
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create({"ref": f"uirr.target,{target.id}"})
        assert pointer.ref_name == "Target"
        assert _is_cached(env, pointer, "ref_name")

        env["uirr.bystander"]._invalidate_after_unlink()

        assert not _is_cached(env, pointer, "ref_name")


def _is_cached(env, record, fname):
    return env.cache.contains(record, record._fields[fname])


def test_the_delete_sweep_drops_the_cached_name():
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create(
            {"res_model": "uirr.target", "res_id": target.id}
        )
        assert pointer.res_name == "Target"
        assert _is_cached(env, pointer, "res_name"), "cached before the delete"

        target._invalidate_after_unlink()

        assert not _is_cached(env, pointer, "res_name"), (
            "the sweep must drop it, so the next read reruns the compute and "
            "finds the record gone, rather than serving the stale name"
        )


def test_the_sweep_runs_whatever_was_deleted():
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create(
            {"res_model": "uirr.target", "res_id": target.id}
        )
        assert pointer.res_name == "Target"

        env["uirr.bystander"]._invalidate_after_unlink()

        assert not _is_cached(env, pointer, "res_name")


def test_the_sweep_drops_a_compute_that_searched_the_deleted_rows():
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        counter = env["uirr.counter"].create({})
        assert counter.target_count == 1

        target.unlink()

        assert counter.target_count == 0


def test_the_sweep_leaves_stored_fields_cached():
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create(
            {"res_model": "uirr.target", "res_id": target.id}
        )
        env.flush_all()
        assert pointer.res_name_stored == "stored"

        env["uirr.bystander"]._invalidate_after_unlink()

        assert _is_cached(env, pointer, "res_name_stored")
