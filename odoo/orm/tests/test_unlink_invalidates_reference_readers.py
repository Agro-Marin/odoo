"""A delete must not leave a dereferenced record's name cached.

`_invalidate_after_delete` replaced a blanket `invalidate_all` with a targeted
sweep driven by `Registry.fields_by_comodel` -- an index of relations whose
comodel is fixed at setup. A `Many2oneReference` names its model in a sibling
column instead, so it sits in no comodel bucket and no sweep keyed on the
deleted model can reach a field computed from one. Such a field caches a value
read out of a model the registry cannot associate with it, and nothing it
declares as a dependency changes when that record is deleted, so it keeps
reporting a record that is gone.

`Registry.fields_reading_through_a_reference` is the index that closes that,
and these tests pin both halves: the index finds the field, and the delete
clears it.
"""

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
    # The shape this is all about: non-stored, and computed by browsing a model
    # named in a sibling column (cf. `documents.document.res_name`,
    # `ir.attachment.res_name`, `mail.message.record_name`).
    res_name = fields.Char(compute="_compute_res_name")
    # A stored sibling, to pin that the index leaves those alone: its value
    # lives in the row, so a dropped cache entry is re-read, not recomputed.
    res_name_stored = fields.Char(compute="_compute_res_name_stored", store=True)

    @api.depends("res_model", "res_id")
    def _compute_res_name(self):
        for record in self:
            target = self.env[record.res_model].browse(record.res_id)
            record.res_name = target.exists().name or False

    # `Reference` is the other dynamic-model field type: it names its model
    # inside its own "model,id" value, so it is absent from `fields_by_comodel`
    # for exactly the same reason. Core has no non-stored compute reading
    # through one today, which is why this test defines one -- an empty type is
    # a hole nobody would notice reopening.
    ref = fields.Reference(selection=[("uirr.target", "Target")])
    ref_name = fields.Char(compute="_compute_ref_name")

    @api.depends("res_model", "res_id")
    def _compute_res_name_stored(self):
        for record in self:
            record.res_name_stored = record.res_id and "stored"

    @api.depends("ref")
    def _compute_ref_name(self):
        for record in self:
            record.ref_name = record.ref.exists().name if record.ref else False


class Bystander(models.Model):
    _name = "uirr.bystander"
    _module = _MOD
    _description = "unrelated to the pointer in every index"
    _log_access = False

    name = fields.Char()


def _env():
    return model_test_env(Target, Pointer, Bystander)


def _pointer_res_name(env):
    return env["uirr.pointer"]._fields["res_name"]


def test_the_index_finds_a_field_read_through_a_reference():
    with _env() as env:
        assert _pointer_res_name(env) in env.registry.fields_reading_through_a_reference


def test_the_index_covers_the_other_dynamic_reference_type():
    with _env() as env:
        ref_name = env["uirr.pointer"]._fields["ref_name"]
        assert ref_name in env.registry.fields_reading_through_a_reference
        by_comodel = env.registry.fields_by_comodel
        assert ref_name not in set(by_comodel.get("uirr.target", ())), (
            "the premise: a Reference has no comodel bucket either"
        )


def test_the_delete_sweep_drops_a_reference_readers_cache():
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create({"ref": f"uirr.target,{target.id}"})
        assert pointer.ref_name == "Target"
        assert _is_cached(env, pointer, "ref_name")

        env["uirr.bystander"]._invalidate_after_delete()

        assert not _is_cached(env, pointer, "ref_name")


def test_the_index_leaves_stored_fields_alone():
    with _env() as env:
        stored = env["uirr.pointer"]._fields["res_name_stored"]
        assert stored not in env.registry.fields_reading_through_a_reference


def test_no_comodel_bucket_can_reach_the_field():
    """The premise: this is why the sweep keyed on the deleted model misses it."""
    with _env() as env:
        by_comodel = env.registry.fields_by_comodel
        reachable = set(by_comodel.get("uirr.target", ()))
        assert _pointer_res_name(env) not in reachable


def _is_cached(env, record, fname):
    return env.cache.contains(record, record._fields[fname])


def test_the_delete_sweep_drops_the_cached_name():
    """`_invalidate_after_delete` is the sweep `unlink` runs after the DELETE.

    It is called directly here: the harness registry carries only the models
    under test, and the full `unlink` reaches `ir.model.data` and
    `ir.attachment`. What the sweep does with the cache is the whole of the
    change, and it is what the caller depends on.
    """
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create(
            {"res_model": "uirr.target", "res_id": target.id}
        )
        assert pointer.res_name == "Target"
        assert _is_cached(env, pointer, "res_name"), "cached before the delete"

        target._invalidate_after_delete()

        assert not _is_cached(env, pointer, "res_name"), (
            "the sweep must drop it, so the next read reruns the compute and "
            "finds the record gone, rather than serving the stale name"
        )


def test_the_sweep_runs_whatever_was_deleted():
    """Whether a delete matters to a reference reader is not knowable here.

    The column that would say so is exactly the one no comodel index can
    consult, so the set is swept on every delete. Pinning that keeps the cost
    visible instead of making it look conditional on the deleted model.
    """
    with _env() as env:
        target = env["uirr.target"].create({"name": "Target"})
        pointer = env["uirr.pointer"].create(
            {"res_model": "uirr.target", "res_id": target.id}
        )
        assert pointer.res_name == "Target"

        # Deleting the pointer's OWN model would clear the field via the
        # per-model loop, proving nothing. `uirr.bystander` is in neither
        # index for `uirr.pointer`, so only the reference sweep can reach it.
        env["uirr.bystander"]._invalidate_after_delete()

        assert not _is_cached(env, pointer, "res_name")
