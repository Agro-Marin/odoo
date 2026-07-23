"""Self-tests for the DB-free ORM harness (:mod:`odoo.orm.model_test_env`).

This is a **Tier-2** suite (real ``import odoo``, no database).  Unlike the
Tier-1 component suites under ``orm/components/tests`` and
``libs/_field_access/tests`` — which register ``sys.modules`` stubs so they can
import leaf modules without the framework — this suite imports the *real* ORM.
The stubs are process-global, so this directory **must run in its own pytest
invocation**, separate from the stubbed suites::

    pytest odoo/orm/tests          # Tier-2: real import, no stubs

It is intentionally lightweight: it exercises the harness against **synthetic**
models (``h.*``) rather than the real ``addons/base`` models, so it needs no
database fixtures and stays fast and hermetic.

Coverage:

* the harness's documented contract (create/persist, write, search,
  filtered/mapped/sorted, lazy compute on ``new()``);
* a regression guard for the ``ir.default`` create() fix (``default_get`` calls
  ``self.env["ir.default"]`` on every create — the harness must provide it);
* model composition: ``_inherit`` (extension) and ``_inherits`` (delegation).
"""

import pytest

from odoo import Command, api, fields, models
from odoo.orm.model_test_env import (
    InMemorySqlNotSupported,
    ModelRegistry,
    model_test_env,
)

# All synthetic models share one module so the harness auto-discovers parents
# and extensions together; names are distinct so they never collide.
_MOD = "test_orm_harness"


class HWidget(models.Model):
    _name = "h.widget"
    _module = _MOD
    _description = "Harness Widget"

    name = fields.Char()
    price = fields.Float()
    qty = fields.Integer()
    total = fields.Float(compute="_compute_total", store=True)
    # Transitive: discounted depends on total, which depends on price/qty.
    discounted = fields.Float(compute="_compute_discounted", store=True)

    @api.depends("price", "qty")
    def _compute_total(self):
        for rec in self:
            rec.total = rec.price * rec.qty

    @api.depends("total")
    def _compute_discounted(self):
        for rec in self:
            rec.discounted = rec.total * 0.9


class HAnimal(models.Model):
    _name = "h.animal"
    _module = _MOD
    _description = "Harness Animal"

    name = fields.Char()
    sound = fields.Char()


class HAnimalLegs(models.Model):
    # _inherit extension: add a field + a method to an existing model in place.
    _inherit = "h.animal"
    _module = _MOD

    legs = fields.Integer(default=4)

    def describe(self):
        self.ensure_one()
        return f"{self.name} says {self.sound} on {self.legs} legs"


class HEngine(models.Model):
    _name = "h.engine"
    _module = _MOD
    _description = "Harness Engine"

    power = fields.Integer()


class HCar(models.Model):
    # _inherits delegation: a car has-an engine, exposing its fields.
    _name = "h.car"
    _module = _MOD
    _description = "Harness Car"
    _inherits = {"h.engine": "engine_id"}

    engine_id = fields.Many2one("h.engine", required=True, ondelete="cascade")
    brand = fields.Char()


class HOrder(models.Model):
    _name = "h.order"
    _module = _MOD
    _description = "Harness Order"

    name = fields.Char()
    line_ids = fields.One2many("h.line", "order_id")
    amount = fields.Float(compute="_compute_amount", store=True)

    @api.depends("line_ids.subtotal")
    def _compute_amount(self):
        for order in self:
            order.amount = sum(order.line_ids.mapped("subtotal"))


class HLine(models.Model):
    _name = "h.line"
    _module = _MOD
    _description = "Harness Order Line"

    order_id = fields.Many2one("h.order", ondelete="cascade")
    price = fields.Float()
    qty = fields.Integer()
    subtotal = fields.Float(compute="_compute_subtotal", store=True)

    @api.depends("price", "qty")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.price * line.qty


# The three models below disable _log_access to keep their assertions focused
# on what they exercise (m2m relation store, translated columns). The
# historical reason — write() after invalidate_all() crashed on the degraded
# write_uid Many2one — is gone: the harness now injects a res.users stub
# (see _TestResUsers and test_write_after_invalidate_with_log_access).


class HTag(models.Model):
    # Stored Many2many with implicit relation schema, plus an `active` field so
    # the active_test read semantics of the m2m paths can be exercised.
    _name = "h.tag"
    _module = _MOD
    _description = "Harness Tag"
    _log_access = False

    name = fields.Char()
    active = fields.Boolean(default=True)
    post_ids = fields.Many2many("h.post")


class HPost(models.Model):
    _name = "h.post"
    _module = _MOD
    _description = "Harness Post"
    _log_access = False

    name = fields.Char()
    tag_ids = fields.Many2many("h.tag")


class HBook(models.Model):
    # Translated field: the column value is a {lang: value} jsonb dict.
    _name = "h.book"
    _module = _MOD
    _description = "Harness Book"
    _log_access = False

    title = fields.Char(translate=True)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_create_persists_and_reads_back():
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        b = env["h.widget"].create({"name": "B", "price": 5.0, "qty": 10})
        assert a.id == 1 and b.id == 2
        assert a.name == "A" and a.price == 10.0 and a.qty == 3


def test_write_updates_field():
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        a.qty = 4
        assert a.qty == 4


def test_stored_compute_cascades_on_create():
    # The harness builds the real trigger graph, so stored computed fields are
    # recomputed automatically on create() — no explicit compute call needed.
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        b = env["h.widget"].create({"name": "B", "price": 5.0, "qty": 10})
        assert a.total == 30.0 and b.total == 50.0


def test_stored_compute_recomputes_on_write():
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        assert a.total == 30.0
        a.qty = 5  # writing a dependency must re-trigger the compute
        assert a.total == 50.0


def test_transitive_compute_cascade():
    # discounted <- total <- (price, qty): a change to price must cascade two
    # levels deep. This is the bug-prone path the old stubbed harness could not
    # exercise at all.
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        assert a.total == 30.0
        assert abs(a.discounted - 27.0) < 1e-9
        a.price = 20.0
        assert a.total == 60.0
        assert abs(a.discounted - 54.0) < 1e-9


def test_explicit_compute_still_works():
    # Invoking a compute method directly remains valid (and idempotent).
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        a._compute_total()
        assert a.total == 30.0


def test_relational_cascade_through_one2many():
    # The classic order/line total: amount <- line_ids.subtotal <- price/qty.
    # Recomputation has to cross models through the One2many/Many2one inverse —
    # the trickiest and most regression-prone path in the ORM.
    with model_test_env(HOrder) as env:
        order = env["h.order"].create({"name": "O1"})
        env["h.line"].create({"order_id": order.id, "price": 10.0, "qty": 2})
        line2 = env["h.line"].create({"order_id": order.id, "price": 5.0, "qty": 3})
        assert order.amount == 35.0  # 20 + 15, cascaded across models on create
        line2.qty = 5  # 25 -> order total must re-cascade to 45
        assert order.amount == 45.0


def test_new_record_lazy_compute():
    # A non-stored / transient `new()` record computes its field on read.
    with model_test_env(HWidget) as env:
        n = env["h.widget"].new({"price": 2.0, "qty": 5})
        assert n.total == 10.0


def test_filtered_mapped_sorted():
    with model_test_env(HWidget) as env:
        a = env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        b = env["h.widget"].create({"name": "B", "price": 5.0, "qty": 10})
        (a + b)._compute_total()
        both = a + b
        assert both.filtered(lambda r: r.total > 45).mapped("name") == ["B"]
        assert both.sorted("total").mapped("name") == ["A", "B"]


def test_search_via_in_memory_backend():
    with model_test_env(HWidget) as env:
        env["h.widget"].create({"name": "A", "price": 10.0, "qty": 3})
        env["h.widget"].create({"name": "B", "price": 5.0, "qty": 10})
        found = env["h.widget"].search([("price", ">", 7.0)])
        assert found.mapped("name") == ["A"]


def test_filtered_id_keeps_only_saved_records():
    # Regression: filtered("id") must keep records with a real id and drop
    # unsaved (NewId, falsy) ones. 'id' is never stored in the field cache, so
    # the cache-scan fast path would report every record as a miss; the special
    # case keeps this correct without the per-record fallback.
    with model_test_env(HWidget) as env:
        saved = env["h.widget"].create([{"name": "A"}, {"name": "B"}])
        draft = env["h.widget"].new({"name": "draft"})
        kept = (saved + draft).filtered("id")
        assert kept._ids == saved._ids


def test_write_multi_aliased_vals_not_uniform():
    # Regression: _write_multi([a, b, a]) with `a is a` was misread as uniform
    # (first-is-last identity) and persisted a's values onto b. Each row must
    # keep its own values.
    with model_test_env(HWidget) as env:
        recs = env["h.widget"].create([{"qty": 1}, {"qty": 2}, {"qty": 3}])
        a, b = {"qty": 100}, {"qty": 200}
        recs._write_multi([a, b, a])
        table = env["h.widget"]._table
        persisted = [env.cr.storage.get_row(table, i)["qty"] for i in recs._ids]
        assert persisted == [100, 200, 100]


# ---------------------------------------------------------------------------
# Regression: create() needs an ir.default provider
# ---------------------------------------------------------------------------


def test_ir_default_is_injected():
    # Without an injected ir.default, default_get() raises KeyError('ir.default')
    # on the very first create(). Guard the fix that injects the stub.
    with model_test_env(HWidget) as env:
        assert "ir.default" in env.registry
        assert env["ir.default"]._get_model_defaults("h.widget") == {}
        # And a create() with no explicit values must not raise.
        rec = env["h.widget"].create({})
        assert rec.id


# ---------------------------------------------------------------------------
# Composition: _inherit (extension) and _inherits (delegation)
# ---------------------------------------------------------------------------


def test_inherit_extension_adds_field_and_method():
    with model_test_env(HAnimal) as env:
        cat = env["h.animal"].create({"name": "Cat", "sound": "meow"})
        # Field from the extension class is present with its default.
        assert cat.legs == 4
        cat.legs = 3
        # Method from the extension class is callable.
        assert cat.describe() == "Cat says meow on 3 legs"


def test_inherits_delegation_exposes_parent_fields():
    with model_test_env(HCar) as env:
        engine = env["h.engine"].create({"power": 100})
        car = env["h.car"].create({"brand": "Acme", "engine_id": engine.id})
        # Delegated field is reachable through the child.
        assert car.power == 100
        assert car.brand == "Acme"


# ---------------------------------------------------------------------------
# Raw SQL is unsupported and must fail loud (no false green)
# ---------------------------------------------------------------------------


def test_raw_sql_fails_loud_instead_of_returning_empty():
    """A model method that drops to raw SQL must raise, not silently read ``[]``.

    Returning an empty result would let the test pass while the same code reads
    real rows on PostgreSQL — exactly the false confidence a fast DB-free tier
    must not introduce.  ``read_group`` is the common offender (it builds and
    executes ``SELECT ... GROUP BY`` directly).
    """
    with model_test_env(HWidget) as env:
        env["h.widget"].create({"name": "A", "price": 10.0, "qty": 1})
        # A direct raw query, and the real read_group path, both fail loud.
        with pytest.raises(InMemorySqlNotSupported):
            env.cr.execute("SELECT count(*) FROM h_widget")
        with pytest.raises(InMemorySqlNotSupported):
            env["h.widget"]._read_group([], ["name"], ["__count"])


def test_fixtures_opt_in_for_raw_sql():
    """``fixtures=`` lets a test that genuinely needs a raw query opt in."""
    with model_test_env(HWidget, fixtures={"SELECT 1": [(42,)]}) as env:
        env.cr.execute("SELECT 1")
        assert env.cr.fetchall() == [(42,)]
        # Still loud for anything not registered.
        with pytest.raises(InMemorySqlNotSupported):
            env.cr.execute("SELECT 2")


def test_dict_cursor_api_fails_loud_for_tuple_fixture():
    """The dict cursor API must not silently return ``[]`` / ``None`` when a
    tuple-shaped fixture holds rows.

    Fixtures carry no column names, so ``dictfetchall`` / ``dictfetchone`` cannot
    rebuild dict rows; returning empty would be a false green for a model method
    that consumes the dict API (the same failure mode ``execute`` guards).
    """
    with model_test_env(HWidget, fixtures={"SELECT 1": [(42,)], "SELECT 0": []}) as env:
        env.cr.execute("SELECT 1")
        # The tuple API serves the registered rows...
        assert env.cr.fetchall() == [(42,)]
        assert env.cr.fetchone() == (42,)
        # ...but the dict API cannot, and fails loud rather than returning empty.
        with pytest.raises(InMemorySqlNotSupported):
            env.cr.dictfetchall()
        with pytest.raises(InMemorySqlNotSupported):
            env.cr.dictfetchone()
        # A genuinely empty result is still a safe, silent [] / None.
        env.cr.execute("SELECT 0")
        assert env.cr.dictfetchall() == []
        assert env.cr.dictfetchone() is None


# ---------------------------------------------------------------------------
# Stored Many2many through the in-memory backend (no relation-table SQL)
# ---------------------------------------------------------------------------


def _fresh(env, records):
    """Flush pending writes and drop the cache, forcing re-reads from storage."""
    env.flush_all()
    env.invalidate_all()
    return records


def test_m2m_model_set_builds():
    # Regression: ModelRegistry.many2many_relations was a Collector (immutable
    # tuple buckets), so Many2many.setup_nonrelated crashed with AttributeError
    # ("tuple has no attribute add") and no m2m model set could even build.
    with model_test_env(HPost) as env:
        assert "h.post" in env.registry and "h.tag" in env.registry
        key = next(iter(env.registry.many2many_relations))
        assert key[0] == "h_post_h_tag_rel"


def test_m2m_create_set_roundtrips_through_backend():
    with model_test_env(HPost) as env:
        t1 = env["h.tag"].create({"name": "t1"})
        t2 = env["h.tag"].create({"name": "t2"})
        post = env["h.post"].create(
            {"name": "p", "tag_ids": [Command.set([t1.id, t2.id])]}
        )
        _fresh(env, post)
        # a fresh read goes storage -> backend.read_m2m_pairs (no SQL)
        assert post.tag_ids._ids == (t1.id, t2.id)
        # inverse field reads the same pair store with swapped columns
        assert t1.post_ids._ids == (post.id,)


def test_m2m_link_unlink_commands():
    with model_test_env(HPost) as env:
        t1 = env["h.tag"].create({"name": "t1"})
        t2 = env["h.tag"].create({"name": "t2"})
        post = env["h.post"].create({"name": "p"})
        post.write({"tag_ids": [Command.link(t1.id), Command.link(t2.id)]})
        _fresh(env, post)
        assert post.tag_ids._ids == (t1.id, t2.id)
        post.write({"tag_ids": [Command.unlink(t1.id)]})
        _fresh(env, post)
        assert post.tag_ids._ids == (t2.id,)
        # re-linking an existing pair is the ON CONFLICT DO NOTHING case
        post.write({"tag_ids": [Command.link(t2.id), Command.link(t1.id)]})
        _fresh(env, post)
        assert post.tag_ids._ids == (t1.id, t2.id)


def test_m2m_read_orders_by_comodel_order():
    # The SQL read orders pairs by the comodel query (comodel._order, here
    # "id"); the backend path must match regardless of link order.
    with model_test_env(HPost) as env:
        tags = env["h.tag"].create([{"name": n} for n in ("a", "b", "c")])
        post = env["h.post"].create(
            {"name": "p", "tag_ids": [Command.set([tags[2].id, tags[0].id])]}
        )
        _fresh(env, post)
        assert post.tag_ids._ids == (tags[0].id, tags[2].id)


def test_m2m_active_test_semantics():
    with model_test_env(HPost) as env:
        t1 = env["h.tag"].create({"name": "t1"})
        t2 = env["h.tag"].create({"name": "t2"})
        post = env["h.post"].create(
            {"name": "p", "tag_ids": [Command.set([t1.id, t2.id])]}
        )
        t2.active = False
        _fresh(env, post)
        # default context: archived corecords are filtered out on read
        assert post.tag_ids._ids == (t1.id,)
        # active_test=False: the archived link is still there
        both = post.with_context(active_test=False).tag_ids
        assert both._ids == (t1.id, t2.id)
        # SET must be able to drop the archived link too (write_real reads the
        # old relation with active_test=False to build the delta)
        post.write({"tag_ids": [Command.set([t1.id])]})
        _fresh(env, post)
        assert post.with_context(active_test=False).tag_ids._ids == (t1.id,)
        # and the pair really left the store, not just the cache
        assert env.cr.storage.row_count("h_post_h_tag_rel") == 1


def test_m2m_clear_command_empties_relation():
    with model_test_env(HPost) as env:
        t1 = env["h.tag"].create({"name": "t1"})
        post = env["h.post"].create({"name": "p", "tag_ids": [Command.link(t1.id)]})
        post.write({"tag_ids": [Command.clear()]})
        _fresh(env, post)
        assert not post.tag_ids
        assert env.cr.storage.row_count("h_post_h_tag_rel") == 0


# ---------------------------------------------------------------------------
# Translated fields: stored shape must be the plain dict (regression M6)
# ---------------------------------------------------------------------------


def test_translated_field_reads_back_after_invalidate():
    # The in-memory backend used to store convert_to_column_insert output
    # verbatim -- a psycopg Json adapter -- so after invalidate_all() the field
    # read back as Json({'en_US': 'Hello'}) instead of 'Hello'.
    with model_test_env(HBook) as env:
        book = env["h.book"].create({"title": "Hello"})
        _fresh(env, book)
        assert book.title == "Hello"
        found = env["h.book"].search([("title", "=", "Hello")])
        assert found._ids == (book.id,)
        # the stored column value is the parsed jsonb shape, as on PostgreSQL
        stored = env.cr.storage.get_row("h_book", book.id)["title"]
        assert stored == {"en_US": "Hello"}


def test_translated_field_update_path_merges_and_unwraps():
    # Same regression through update_rows (write -> flush), which must also
    # apply the SQL path's jsonb merge against the stored dict.
    with model_test_env(HBook) as env:
        book = env["h.book"].create({"title": "Hello"})
        _fresh(env, book)
        book.title = "World"
        _fresh(env, book)
        assert book.title == "World"
        stored = env.cr.storage.get_row("h_book", book.id)["title"]
        assert isinstance(stored, dict)
        assert stored["en_US"] == "World"


# ---------------------------------------------------------------------------
# commit() / rollback(): no silent no-ops (previous finding #8)
# ---------------------------------------------------------------------------


def test_commit_flushes_and_runs_postcommit_hooks():
    with model_test_env(HWidget) as env:
        fired = []
        env.cr.postcommit.add(lambda: fired.append("post"))
        rec = env["h.widget"].create({"name": "A"})
        rec.qty = 7  # dirty in cache only
        env.cr.commit()
        assert fired == ["post"]
        # commit ran flush: the dirty write reached storage
        assert env.cr.storage.get_row("h_widget", rec.id)["qty"] == 7
        # and the transaction was cleared, mirroring the production cursor
        assert not env.cr.precommit
        # records remain readable after commit (re-fetched from storage)
        assert rec.qty == 7


def test_rollback_fails_loud():
    # No snapshot exists to restore, and a silent no-op would diverge from
    # production ROLLBACK -- the harness raises instead.
    with model_test_env(HWidget) as env:
        env["h.widget"].create({"name": "A"})
        with pytest.raises(InMemorySqlNotSupported):
            env.cr.rollback()


# ---------------------------------------------------------------------------
# ModelRegistry gaps (previous finding #14)
# ---------------------------------------------------------------------------


def test_clear_cache_honors_names():
    with model_test_env(HWidget) as env:
        caches = env.registry._Registry__caches
        caches["default"]["k"] = 1
        caches["templates.cached_values"]["k"] = 1
        caches["assets"]["k"] = 1
        env.registry.clear_cache()  # defaults to the "default" group
        assert not caches["default"]
        # "templates.cached_values" is in the "default" group (production map)
        assert not caches["templates.cached_values"]
        # ...but unrelated caches survive (the old code wiped everything)
        assert caches["assets"] == {"k": 1}
        env.registry.clear_cache("assets")
        assert not caches["assets"]
        # dotted composite names are rejected exactly like production
        with pytest.raises(ValueError):
            env.registry.clear_cache("templates.cached_values")


def test_discard_fields_works_without_attributeerror():
    # ModelRegistry inherits @locked _discard_fields; it used to lack the
    # _lock attribute the decorator acquires.
    registry = ModelRegistry([HWidget])
    field = registry["h.widget"]._fields["total"]
    registry._discard_fields([field])  # must not raise
    assert field not in registry.field_depends


class HAudit(models.Model):
    """Default _log_access: exercises the injected res.users stub."""

    _name = "h.audit"
    _module = _MOD
    _description = "log-access model"

    name = fields.Char()


def test_write_after_invalidate_with_log_access():
    """Regression: with default _log_access, a write() after invalidate_all()
    crashed with KeyError 'res.users' in Many2one._update_inverses because the
    magic create_uid/write_uid comodel had no model class. The harness now
    injects _TestResUsers (backed by the seeded superuser row)."""
    with model_test_env(HAudit) as env:
        record = env["h.audit"].create({"name": "a"})
        env.invalidate_all()
        record.write({"name": "b"})
        assert record.name == "b"
        assert record.write_uid.id == 1
        assert env["res.users"].browse(1).login == "admin"


def test_user_supplied_res_users_wins_over_stub():
    class MyUsers(models.Model):
        _name = "res.users"
        _module = _MOD
        _description = "custom users"
        _log_access = False

        name = fields.Char()
        custom_flag = fields.Boolean()

    with model_test_env(HAudit, MyUsers) as env:
        assert "custom_flag" in env["res.users"]._fields
