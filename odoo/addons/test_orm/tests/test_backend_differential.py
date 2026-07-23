"""Differential tests: DB-free harness backend vs. the real SQL backend.

Motivation
==========
The DB-free harness :mod:`odoo.orm.model_test_env` reuses the *real* ORM
machinery except for the storage backend.  Two components re-implement row I/O
in parallel to the SQL path:

* :class:`~odoo.orm.components.storage.DictBackend` — the in-memory row store;
* :class:`~odoo.orm.runtime.backend.InMemoryBackend` — the in-memory variant of
  create / write / fetch / search / delete and the Many2many relation-table ops.

Those parallel implementations are the main *fidelity risk* of the fast tier: a
divergence between them and PostgreSQL makes a DB-free test go **green while
production behaves differently**.  This suite runs the *same* scripted ORM
scenario through **both** backends and asserts the observable results are
identical.  A future, undeclared divergence therefore fails a test instead of
silently rotting.  Divergences that are *expected* (record rules, raw SQL,
savepoints, ``ilike`` unaccent, ``_parent_store``) are pinned as explicit
``test_divergence_*`` methods — if any of them ever changes, the pin fails and
forces a conscious update.

Side-B (real-registry) mapping — design choice
==============================================
Each scenario runs against an *existing* ``test_orm`` model (``test_orm.foo``,
``test_orm.move``/``move_line``, ``test_orm.model_a``/``model_b`` …), **not** a
dynamically-created ``ir.model``.  test_orm declares no dynamic-model precedent,
and reusing the shipped models guarantees the two sides share the exact same
field shapes: side A feeds the *very same Python model class* to the harness, so
there is zero chance of a side-A/side-B schema drift masking a backend bug.

Building the harness registry inside a full Odoo boot needs care.
:func:`model_test_env` auto-discovers every model of a class's ``_module`` **plus
the whole ``base`` module**.  Under a live server ``base`` is fully imported, so
the harness would pull in the real ``ir.default`` / ``ir.config_parameter``
(whose methods run raw SQL and hit ``ormcache``) and crash.  In its intended
Tier-2 pytest context ``base`` is *not* imported, so the harness falls back to
its lightweight stubs (``_TestBase`` / ``_TestIrDefault`` / ``_TestResUsers`` /
``_TestResCompany``).  :func:`_isolated_registry` reproduces those Tier-2
semantics here: it hides ``MetaModel._module_to_models__`` for the duration of
the build so only the explicitly-passed classes (+ the injected stubs) are
registered, then it swaps the registry's plain-dict ormcache store for real
``LRU`` objects (the harness's ``defaultdict(dict)`` lacks the ``.generation``
attribute ``ormcache`` reads — see the module-level note below).

Observation normalisation
=========================
Scenarios never compare raw ``id`` integers (they differ between an empty
in-memory store and a populated database).  Every observation is expressed in
terms of *business keys* — field values, ``name`` sequences, ordered related-
record names — so record identity is compared through a stable mapping rather
than by primary key.

NOTE for the ORM maintainer (harness robustness, not a false-green):
``ModelRegistry._Registry__caches`` is ``defaultdict(dict)``; ``ormcache``'s
``lookup`` reads ``d.generation`` (an ``LRU`` attribute), so *any*
ormcache-decorated method invoked through the harness raises
``AttributeError: 'dict' object has no attribute 'generation'``.  The existing
Tier-2 self-tests never invoke such a method, so it stays latent.  This suite
works around it (LRU swap) but the harness itself would be more robust using an
``LRU``-backed store.
"""

import logging
from collections import defaultdict
from datetime import datetime

from odoo import models
from odoo.fields import Command
from odoo.libs.lru import LRU
from odoo.orm.model_test_env import (
    InMemoryRecordRulesNotSupported,
    InMemorySqlNotSupported,
    ModelRegistry,
    model_test_env,
)
from odoo.orm.models.metaclass import MetaModel
from odoo.tests import TransactionCase, tagged

from odoo.addons.test_orm.models.test_orm import (
    CalendarTest,
    TestOrmAutovacuumed,
    TestOrmCategory,
    TestOrmFoo,
    TestOrmModel_A,
    TestOrmModel_B,
    TestOrmMove,
    TestOrmMove_Line,
    TestOrmMultiTag,
    TestOrmPayment,
    TestOrmRelated_Translation_1,
)

_logger = logging.getLogger(__name__)

_STUB_MODULE = "test_orm_diff_stub"


class _StubIrModelData(models.Model):
    """Minimal ``ir.model.data`` so ``unlink()`` runs DB-free.

    ``unlink()`` unconditionally resolves ``self.env["ir.model.data"]`` (and
    ``ir.attachment``) to collect xmlid / attachment cleanup targets, but the
    harness only injects ``ir.default`` / ``res.users`` / ``res.company`` stubs.
    On the in-memory path ``InMemoryBackend.delete`` only ``.browse()``s these
    two models and returns them empty, so a bare, field-less stub is enough.

    NOTE for the ORM maintainer: this gap means a DB-free test that calls
    ``unlink()`` currently raises ``KeyError: 'ir.model.data'``; injecting these
    two stubs in ``model_test_env`` (as it already does for ``ir.default`` etc.)
    would make ``unlink()`` usable out of the box.
    """

    _name = "ir.model.data"
    _module = _STUB_MODULE
    _description = "ir.model.data (differential test stub)"
    _log_access = False


class _StubIrAttachment(models.Model):
    """Minimal ``ir.attachment`` so ``unlink()`` runs DB-free (see stub above)."""

    _name = "ir.attachment"
    _module = _STUB_MODULE
    _description = "ir.attachment (differential test stub)"
    _log_access = False


def _isolated_registry(*classes):
    """Build a Tier-2-style harness registry for *classes* under a live server.

    Hides ``MetaModel._module_to_models__`` during the build so the harness uses
    its lightweight ``base`` stubs (instead of pulling the fully-imported real
    ``base`` module, which runs raw SQL and crashes), then swaps in ``LRU``
    ormcache stores so ``ormcache``'s ``.generation`` read works.  Restores the
    global metamodel state before returning, whatever happens.
    """
    saved = MetaModel._module_to_models__
    try:
        MetaModel._module_to_models__ = defaultdict(list)
        registry = ModelRegistry([*classes, _StubIrModelData, _StubIrAttachment])
    finally:
        MetaModel._module_to_models__ = saved
    registry._Registry__caches = defaultdict(lambda: LRU(4096))
    return registry


@tagged("post_install", "-at_install")
class TestBackendDifferential(TransactionCase):
    """Run identical scenarios through the harness and the real SQL backend."""

    # -- executor ----------------------------------------------------------

    def _diff(self, classes, script, msg=""):
        """Run *script* on both backends and assert identical observations.

        *classes* are the model definition classes the harness registry needs
        (must include every comodel the scenario touches).  *script* is a
        side-agnostic callable ``env -> observations``; it must return only
        normalised, business-key-based data (never raw ids).
        """
        registry = _isolated_registry(*classes)
        with model_test_env(registry=registry) as env_a:
            obs_a = script(env_a)
        # Side B runs against the real registry; TransactionCase gives this test
        # method its own savepoint, so nothing created here survives the method.
        obs_b = script(self.env)
        self.assertEqual(
            obs_a,
            obs_b,
            f"DB-free harness diverged from SQL backend{': ' + msg if msg else ''}\n"
            f"  harness (side A): {obs_a!r}\n"
            f"  SQL     (side B): {obs_b!r}",
        )
        return obs_a

    # =====================================================================
    # create / write / read round-trips
    # =====================================================================

    def test_create_read_defaults_and_falsy(self):
        def script(env):
            F = env["test_orm.foo"]
            # explicit falsy values (0, "") + a record relying entirely on
            # defaults. Names are distinct so ordering is unambiguous.
            F.create({"name": "falsy", "value1": 0, "value2": 0, "text": ""})
            F.create({"name": "filled", "value1": 7, "value2": -3, "text": "hi"})
            F.create({"name": "defaulted"})  # value1/value2/text defaulted
            env.flush_all()
            env.invalidate_all()  # force a storage round-trip, not a cache read
            recs = F.search(
                [("name", "in", ["falsy", "filled", "defaulted"])], order="name"
            )
            return [
                {
                    "name": r.name,
                    "value1": r.value1,
                    "value2": r.value2,
                    # "" vs False normalisation must agree across backends
                    "text": r.text,
                    "text_is_falsy": not r.text,
                }
                for r in recs
            ]

        self._diff((TestOrmFoo,), script, "create defaults / falsy round-trip")

    def test_boolean_default_true(self):
        def script(env):
            move = env["test_orm.move"].create(
                {"line_ids": [Command.create({"quantity": 4})]}
            )
            env.flush_all()
            env.invalidate_all()
            line = move.line_ids
            # 'visible' defaults to True; 'quantity' set; both read from storage
            return {"visible": line.visible, "quantity": line.quantity}

        self._diff(
            (TestOrmMove, TestOrmMove_Line, TestOrmMultiTag, TestOrmPayment),
            script,
            "Boolean default=True round-trip",
        )

    def test_write_roundtrip(self):
        def script(env):
            r = env["test_orm.foo"].create({"name": "a", "value1": 1})
            r.write({"name": "b", "value1": 2, "value2": 9})
            env.flush_all()
            env.invalidate_all()
            return {"name": r.name, "value1": r.value1, "value2": r.value2}

        self._diff((TestOrmFoo,), script, "write round-trip")

    def test_unlink(self):
        def script(env):
            F = env["test_orm.foo"]
            a = F.create({"name": "a"})
            F.create({"name": "b"})
            c = F.create({"name": "c"})
            (a + c).unlink()
            env.flush_all()
            env.invalidate_all()
            return sorted(F.search([]).mapped("name"))

        self._diff((TestOrmFoo,), script, "unlink")

    # =====================================================================
    # search operators
    # =====================================================================

    def _make_foos(self, env, rows):
        F = env["test_orm.foo"]
        for name, v1 in rows:
            F.create({"name": name, "value1": v1})
        env.flush_all()
        env.invalidate_all()
        return F

    def test_search_equality_operators(self):
        rows = [("alpha", 1), ("beta", 2), ("gamma", 3), ("delta", 2)]
        names = [n for n, _ in rows]

        def script(env):
            F = self._make_foos(env, rows)
            scope = [("name", "in", names)]
            return {
                "eq": sorted(F.search([*scope, ("value1", "=", 2)]).mapped("name")),
                "ne": sorted(F.search([*scope, ("value1", "!=", 2)]).mapped("name")),
                "in": sorted(
                    F.search([*scope, ("value1", "in", [1, 3])]).mapped("name")
                ),
                "not_in": sorted(
                    F.search([*scope, ("value1", "not in", [1, 3])]).mapped("name")
                ),
                "name_eq": sorted(
                    F.search([*scope, ("name", "=", "beta")]).mapped("name")
                ),
                "name_false": sorted(
                    F.search([*scope, ("name", "!=", False)]).mapped("name")
                ),
            }

        self._diff((TestOrmFoo,), script, "= / != / in / not in")

    def test_search_comparison_operators(self):
        rows = [("a", 1), ("b", 2), ("c", 3), ("d", 4)]
        names = [n for n, _ in rows]

        def script(env):
            F = self._make_foos(env, rows)
            scope = [("name", "in", names)]
            return {
                "lt": sorted(F.search([*scope, ("value1", "<", 3)]).mapped("name")),
                "le": sorted(F.search([*scope, ("value1", "<=", 3)]).mapped("name")),
                "gt": sorted(F.search([*scope, ("value1", ">", 2)]).mapped("name")),
                "ge": sorted(F.search([*scope, ("value1", ">=", 2)]).mapped("name")),
            }

        self._diff((TestOrmFoo,), script, "< / <= / > / >=")

    def test_search_like_ilike_ascii(self):
        # ASCII-only data: like/ilike must agree on both backends (the accent-
        # sensitive divergence is pinned separately in test_divergence_*).
        rows = [("Apple", 0), ("apricot", 0), ("Banana", 0), ("grApe", 0)]
        names = [n for n, _ in rows]

        def script(env):
            F = self._make_foos(env, rows)
            scope = [("name", "in", names)]
            return {
                "like_ap": sorted(
                    F.search([*scope, ("name", "like", "ap")]).mapped("name")
                ),
                "ilike_ap": sorted(
                    F.search([*scope, ("name", "ilike", "ap")]).mapped("name")
                ),
                "not_like": sorted(
                    F.search([*scope, ("name", "not like", "an")]).mapped("name")
                ),
                "ilike_a": sorted(
                    F.search([*scope, ("name", "ilike", "a")]).mapped("name")
                ),
            }

        self._diff((TestOrmFoo,), script, "like / ilike (ASCII)")

    # =====================================================================
    # ordering, limit, offset
    # =====================================================================

    def test_search_order_asc_desc(self):
        rows = [("a", 3), ("b", 1), ("c", 2)]
        names = [n for n, _ in rows]

        def script(env):
            F = self._make_foos(env, rows)
            scope = [("name", "in", names)]
            return {
                "asc": F.search(scope, order="value1 asc").mapped("name"),
                "desc": F.search(scope, order="value1 desc").mapped("name"),
            }

        self._diff((TestOrmFoo,), script, "order asc/desc")

    def test_search_order_multikey(self):
        rows = [("a", 2), ("b", 1), ("c", 2), ("d", 1)]
        names = [n for n, _ in rows]

        def script(env):
            F = self._make_foos(env, rows)
            scope = [("name", "in", names)]
            return {
                # value1 asc, then name desc as the tie-breaker
                "multi": F.search(scope, order="value1 asc, name desc").mapped("name"),
            }

        self._diff((TestOrmFoo,), script, "multi-key order")

    def test_search_order_nulls(self):
        # NULL sort placement: PostgreSQL defaults to NULLS LAST for ASC and
        # NULLS FIRST for DESC; the in-memory .sorted() must match.
        def script(env):
            F = env["test_orm.foo"]
            F.create({"name": "b"})
            F.create({})  # name is NULL / False
            F.create({"name": "a"})
            env.flush_all()
            env.invalidate_all()
            return {
                "asc": F.search([], order="name asc").mapped("name"),
                "desc": F.search([], order="name desc").mapped("name"),
            }

        self._diff((TestOrmFoo,), script, "NULLS ordering")

    def test_search_limit_offset(self):
        rows = [(f"n{i}", i) for i in range(6)]
        names = [n for n, _ in rows]

        def script(env):
            F = self._make_foos(env, rows)
            scope = [("name", "in", names)]
            return {
                "limit": F.search(scope, order="value1", limit=3).mapped("name"),
                "offset": F.search(scope, order="value1", offset=2).mapped("name"),
                "both": F.search(scope, order="value1", limit=2, offset=3).mapped(
                    "name"
                ),
                "count": F.search_count(scope),
            }

        self._diff((TestOrmFoo,), script, "limit / offset / count")

    # =====================================================================
    # Many2many
    # =====================================================================

    def test_m2m_set_link_unlink(self):
        def script(env):
            A = env["test_orm.model_a"]
            B = env["test_orm.model_b"]
            b1 = B.create({"name": "b1"})
            b2 = B.create({"name": "b2"})
            b3 = B.create({"name": "b3"})
            a = A.create(
                {"name": "a", "a_restricted_b_ids": [Command.set([b1.id, b2.id])]}
            )

            def snap():
                env.flush_all()
                env.invalidate_all()
                return a.a_restricted_b_ids.mapped("name")

            steps = {"after_set": snap()}
            a.write({"a_restricted_b_ids": [Command.link(b3.id)]})
            steps["after_link"] = snap()
            a.write({"a_restricted_b_ids": [Command.unlink(b1.id)]})
            steps["after_unlink"] = snap()
            a.write({"a_restricted_b_ids": [Command.set([b3.id])]})
            steps["after_reset"] = snap()
            a.write({"a_restricted_b_ids": [Command.clear()]})
            steps["after_clear"] = snap()
            return steps

        self._diff(
            (TestOrmModel_A, TestOrmModel_B), script, "m2m link/unlink/set/clear"
        )

    def test_m2m_read_ordering(self):
        # The m2m read orders corecords by the comodel _order (here 'id', i.e.
        # creation order), regardless of link order.
        def script(env):
            A = env["test_orm.model_a"]
            B = env["test_orm.model_b"]
            b1 = B.create({"name": "b1"})
            b2 = B.create({"name": "b2"})
            b3 = B.create({"name": "b3"})
            a = A.create(
                {
                    "name": "a",
                    # linked in a deliberately scrambled order
                    "a_restricted_b_ids": [Command.set([b3.id, b1.id, b2.id])],
                }
            )
            env.flush_all()
            env.invalidate_all()
            return a.a_restricted_b_ids.mapped("name")

        self._diff((TestOrmModel_A, TestOrmModel_B), script, "m2m read ordering")

    # =====================================================================
    # One2many Command processing
    # =====================================================================

    def test_o2m_commands(self):
        def script(env):
            M = env["test_orm.move"]
            move = M.create(
                {
                    "line_ids": [
                        Command.create({"quantity": 5, "visible": True}),
                        Command.create({"quantity": 3, "visible": True}),
                    ]
                }
            )

            def snap():
                env.flush_all()
                env.invalidate_all()
                return {
                    "lines": sorted(move.line_ids.mapped("quantity")),
                    "quantity": move.quantity,  # stored compute = sum(lines)
                }

            steps = {"after_create": snap()}
            first = move.line_ids.sorted("quantity")[0]
            move.write({"line_ids": [Command.update(first.id, {"quantity": 10})]})
            steps["after_update"] = snap()
            move.write({"line_ids": [Command.create({"quantity": 1, "visible": True})]})
            steps["after_add"] = snap()
            biggest = move.line_ids.sorted("quantity")[-1]
            move.write({"line_ids": [Command.delete(biggest.id)]})
            steps["after_delete"] = snap()
            move.write({"line_ids": [Command.clear()]})
            steps["after_clear"] = snap()
            return steps

        self._diff(
            (TestOrmMove, TestOrmMove_Line, TestOrmMultiTag, TestOrmPayment),
            script,
            "o2m Command processing",
        )

    # =====================================================================
    # translated field (en_US)
    # =====================================================================

    def test_translated_field_en_us_roundtrip(self):
        # Exercises the jsonb translated-column path: create stores {en_US: v},
        # write merges into the stored dict, read projects the en_US scalar.
        def script(env):
            M = env["test_orm.related_translation_1"]
            r = M.create({"name": "Hello"})
            env.flush_all()
            env.invalidate_all()
            created = r.name
            r.name = "World"
            env.flush_all()
            env.invalidate_all()
            written = r.name
            found = M.search([("name", "=", "World")]).mapped("name")
            return {"created": created, "written": written, "found": sorted(found)}

        self._diff(
            (TestOrmRelated_Translation_1,), script, "translated en_US round-trip"
        )

    # =====================================================================
    # date / datetime boundary comparisons
    # =====================================================================

    def test_datetime_boundaries(self):
        moments = [
            datetime(2020, 1, 1, 12, 0, 0),
            datetime(2020, 6, 15, 8, 30, 0),
            datetime(2021, 3, 3, 0, 0, 0),
        ]

        def script(env):
            M = env["test_orm.autovacuumed"]
            for m in moments:
                M.create({"expire_at": m})
            env.flush_all()
            env.invalidate_all()
            b = datetime(2020, 6, 15, 8, 30, 0)  # exactly equals moments[1]
            return {
                "lt": M.search_count([("expire_at", "<", b)]),
                "le": M.search_count([("expire_at", "<=", b)]),
                "gt": M.search_count([("expire_at", ">", b)]),
                "ge": M.search_count([("expire_at", ">=", b)]),
                "eq": M.search_count([("expire_at", "=", b)]),
                "order": [
                    dt.isoformat()
                    for dt in M.search([], order="expire_at desc").mapped("expire_at")
                ],
            }

        self._diff((TestOrmAutovacuumed,), script, "datetime boundaries")

    def test_date_boundaries(self):
        from datetime import date

        dates = [date(2020, 1, 1), date(2020, 6, 15), date(2021, 3, 3)]

        def script(env):
            M = env["calendar.test"]
            for d in dates:
                M.create({"x_date_start": d})
            env.flush_all()
            env.invalidate_all()
            b = date(2020, 6, 15)
            return {
                "lt": M.search_count([("x_date_start", "<", b)]),
                "ge": M.search_count([("x_date_start", ">=", b)]),
                "eq": M.search_count([("x_date_start", "=", b)]),
                "order": [
                    d.isoformat()
                    for d in M.search([], order="x_date_start").mapped("x_date_start")
                ],
            }

        self._diff((CalendarTest,), script, "date boundaries")

    # =====================================================================
    # EXPECTED, DECLARED divergences
    # ---------------------------------------------------------------------
    # These backends intentionally differ.  Each pin asserts the *current*
    # divergence so a future change (in either direction) fails loudly and
    # forces a conscious decision, rather than a silent false-green.
    # =====================================================================

    def test_divergence_record_rules_not_enforced(self):
        """Harness has no ``ir.rule`` model: record rules are NOT enforced.

        ``search()`` dispatches to the in-memory backend before the security
        domain, so the harness raises on ``ir.rule`` access instead of silently
        skipping rules (``InMemoryBackend.supports_record_rules is False``).
        The real backend enforces them.
        """
        registry = _isolated_registry(TestOrmFoo)
        with model_test_env(registry=registry) as env_a:
            # The harness backend advertises that it does NOT enforce rules...
            self.assertFalse(env_a.backend.supports_record_rules)
            # ...and accessing ir.rule fails loud rather than skipping silently.
            with self.assertRaises(InMemoryRecordRulesNotSupported):
                _ = env_a["ir.rule"]  # access triggers the guard
        # Side B: the SQL path has no backend object and ir.rule is a real,
        # enforced model (an empty recordset is falsy, so assert on the registry).
        self.assertIsNone(self.env.backend)
        self.assertIn("ir.rule", self.env.registry)

    def test_divergence_raw_sql_fails_loud(self):
        """Raw SQL runs on the DB but fails loud in the harness (no false green)."""
        registry = _isolated_registry(TestOrmFoo)
        with model_test_env(registry=registry) as env_a:
            with self.assertRaises(InMemorySqlNotSupported):
                env_a.cr.execute('SELECT count(*) FROM "test_orm_foo"')
        # Side B: the same raw SQL executes.
        self.env["test_orm.foo"].create({"name": "x"})
        self.env.flush_all()
        self.env.cr.execute('SELECT count(*) FROM "test_orm_foo"')
        self.assertGreaterEqual(self.env.cr.fetchone()[0], 1)

    def test_divergence_rollback_and_savepoint_fail_loud(self):
        """DictBackend keeps no snapshot, so rollback/savepoint fail loud.

        The DB backend supports both; the harness raises rather than silently
        no-op'ing (which would diverge from a real ROLLBACK discarding writes).
        """
        registry = _isolated_registry(TestOrmFoo)
        with model_test_env(registry=registry) as env_a:
            with self.assertRaises(InMemorySqlNotSupported):
                env_a.cr.rollback()
            with self.assertRaises(InMemorySqlNotSupported):
                env_a.cr.savepoint()
        # Side B: a real savepoint rolls back cleanly.
        F = self.env["test_orm.foo"]
        sp = self.env.cr.savepoint()
        F.create({"name": "temp"})
        sp.close(rollback=True)
        self.assertFalse(F.search([("name", "=", "temp")]))

    def test_divergence_ilike_unaccent(self):
        """``ilike`` is accent-INsensitive on PostgreSQL (unaccent) but accent-
        SENSITIVE in the harness (``ModelRegistry.unaccent`` is the identity).

        This is the documented ``ilike`` unaccent divergence.  Pinned so that if
        the harness ever gains unaccent (or the DB loses it) the mismatch is
        caught instead of silently flipping a fast-tier result.
        """

        def script(env):
            F = env["test_orm.foo"]
            F.create({"name": "Café"})
            F.create({"name": "Cafe"})
            env.flush_all()
            env.invalidate_all()
            scope = [("name", "in", ["Café", "Cafe"])]
            return sorted(F.search([*scope, ("name", "ilike", "cafe")]).mapped("name"))

        registry = _isolated_registry(TestOrmFoo)
        with model_test_env(registry=registry) as env_a:
            obs_a = script(env_a)
        obs_b = script(self.env)
        # Harness: accent-sensitive -> only the ASCII spelling matches.
        self.assertEqual(obs_a, ["Cafe"])
        # PostgreSQL: unaccent -> both spellings match.
        self.assertEqual(obs_b, ["Cafe", "Café"])
        self.assertNotEqual(obs_a, obs_b)

    def test_divergence_parent_store_and_child_of(self):
        """The harness does not maintain ``parent_path`` (``InMemoryBackend.
        supports_parent_store is False``), so ``_parent_store`` bookkeeping and
        ``child_of`` diverge from the DB.

        FIXME(coordinator): the harness leaves ``parent_path`` unset (``False``)
        and a subsequent ``child_of`` search then *crashes* with a ``TypeError``
        (``bool`` vs ``str`` while building the ``parent_path LIKE`` domain),
        rather than failing loud with an explanatory ``NotImplemented`` message
        the way ``ir.rule`` / raw-SQL / savepoints do.  Consider either
        maintaining ``parent_path`` in ``InMemoryBackend`` or raising a clear
        "parent_store not supported" error in ``odoo/orm/runtime/backend.py``.
        Declared-and-expected for now; not a false-green (it is a hard error).
        """

        def build_tree(env):
            C = env["test_orm.category"]
            root = C.create({"name": "root"})
            child = C.create({"name": "child", "parent": root.id})
            grand = C.create({"name": "grand", "parent": child.id})
            env.flush_all()
            env.invalidate_all()
            return C, root, child, grand

        registry = _isolated_registry(TestOrmCategory)
        with model_test_env(registry=registry) as env_a:
            C_a, root_a, _child_a, grand_a = build_tree(env_a)
            # Divergence 1: parent_path is NOT maintained in the harness.
            self.assertFalse(grand_a.parent_path)
            # Divergence 2: child_of therefore does not work (it errors).
            with self.assertRaises(TypeError):
                C_a.search([("id", "child_of", root_a.id)])

        # Side B: parent_path is maintained and child_of returns the subtree.
        C_b, root_b, child_b, grand_b = build_tree(self.env)
        self.assertTrue(grand_b.parent_path)
        self.assertEqual(grand_b.parent_path.count("/"), 3)
        subtree = C_b.search(
            [
                ("id", "child_of", root_b.id),
                ("id", "in", (root_b + child_b + grand_b).ids),
            ]
        )
        self.assertEqual(sorted(subtree.mapped("name")), ["child", "grand", "root"])
