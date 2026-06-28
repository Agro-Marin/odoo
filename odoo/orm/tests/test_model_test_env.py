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

from odoo import api, fields, models
from odoo.orm.model_test_env import InMemorySqlNotSupported, model_test_env

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
