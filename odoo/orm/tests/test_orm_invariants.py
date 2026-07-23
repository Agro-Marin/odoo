"""Regression guards for subtle ORM invariants (engine audit, June 2026).

Each test locks in a behaviour that is correct today but easy to break, and
whose breakage would be silent (a perf cliff, a stale optimisation, a test that
passes while production misbehaves). Tier-2 suite: real ``import odoo``, no
database — runs in its own pytest invocation like ``test_model_test_env``.

Covers:

* ``INVERSE_OPERATOR`` is the exact negation map (it is *derived* from
  ``NEGATIVE_CONDITION_OPERATORS``; this pins the full result so the derivation
  cannot drift);
* ``Domain.optimize`` never mutates the original node — so reusing an
  *un-optimised* domain across models is safe — while the optimised *output* is
  model-specific and must not be reused across models;
* the scalar read/traversal fast paths agree on the "no value" sentinel for
  every fast-path scalar type (``convert_to_record(None, None)`` ==
  ``convert_to_record(None, rec[:1])``);
* ``model_test_env`` tolerates a missing comodel *visibly* and lets a real
  dependency-resolution error propagate instead of degrading to no-triggers;
* ``Monetary`` column conversion resolves its currency without prefetching.
"""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.orm.domain.constants import INVERSE_OPERATOR, NEGATIVE_CONDITION_OPERATORS
from odoo.orm.model_test_env import model_test_env

_MOD = "test_orm_invariants"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class IScalars(models.Model):
    """Host for every fast-path scalar field type."""

    _name = "i.scalars"
    _module = _MOD
    _description = "All fast-path scalar types"

    f_bool = fields.Boolean()
    f_int = fields.Integer()
    f_float = fields.Float()
    f_char = fields.Char()
    f_text = fields.Text()
    f_sel = fields.Selection([("a", "A"), ("b", "B")])
    f_date = fields.Date()
    f_dt = fields.Datetime()
    f_money = fields.Monetary()
    currency_id = fields.Many2one("res.currency")


class IAlpha(models.Model):
    """Non-stored searchable field whose optimisation is model-dependent."""

    _name = "i.alpha"
    _module = _MOD
    _description = "Non-stored searchable field"

    ref = fields.Char(compute="_compute_ref", search="_search_ref", store=False)

    def _compute_ref(self) -> None:
        """Assign a constant so the field is readable."""
        for rec in self:
            rec.ref = "x"

    def _search_ref(self, operator: str, value: object) -> list:
        """Substitute a concrete id domain during optimisation."""
        return [("id", "in", [11, 22])]


class IBeta(models.Model):
    """Plain stored field of the same name as :class:`IAlpha` (no search)."""

    _name = "i.beta"
    _module = _MOD
    _description = "Plain stored field, different semantics"

    ref = fields.Char()


class ICurrency(models.Model):
    """Minimal ``res.currency`` double so the Monetary path runs DB-free."""

    _name = "res.currency"
    _module = _MOD
    _description = "Currency (test double)"

    name = fields.Char()
    rounding = fields.Float(default=0.01)

    def round(self, amount: float) -> float:
        """Round ``amount`` to this currency's ``rounding`` precision."""
        self.ensure_one()
        prec = self.rounding or 0.01
        return round(amount / prec) * prec


class IInvoice(models.Model):
    """Monetary host with a currency."""

    _name = "i.invoice"
    _module = _MOD
    _description = "Monetary host"

    currency_id = fields.Many2one("res.currency")
    amount = fields.Monetary()


_FASTPATH_SCALARS = (
    "f_bool",
    "f_int",
    "f_float",
    "f_char",
    "f_text",
    "f_sel",
    "f_date",
    "f_dt",
    "f_money",
)


# ---------------------------------------------------------------------------
# Domain operator constants
# ---------------------------------------------------------------------------
def test_inverse_operator_is_exact_negation_map() -> None:
    """Pin the full negation map so the derivation cannot silently drift.

    ``INVERSE_OPERATOR`` is derived from ``NEGATIVE_CONDITION_OPERATORS``.
    """
    expected = {
        # negative -> positive (every NEGATIVE_CONDITION_OPERATORS entry)
        "not any": "any",
        "not any!": "any!",
        "not in": "in",
        "not like": "like",
        "not ilike": "ilike",
        "not =like": "=like",
        "not =ilike": "=ilike",
        "!=": "=",
        "<>": "=",
        # positive -> negative (reverse; "=" canonicalises to "!=", not "<>")
        "any": "not any",
        "any!": "not any!",
        "in": "not in",
        "like": "not like",
        "ilike": "not ilike",
        "=like": "not =like",
        "=ilike": "not =ilike",
        "=": "!=",
    }
    assert expected == INVERSE_OPERATOR
    # the negative->positive half must equal NEGATIVE_CONDITION_OPERATORS exactly
    for neg, pos in NEGATIVE_CONDITION_OPERATORS.items():
        assert INVERSE_OPERATOR[neg] == pos


def test_inverse_operator_is_an_involution_on_canonical_operators() -> None:
    """Applying the inverse twice returns the original (canonical operators).

    ``<>`` is a legacy alias of ``!=`` and is intentionally one-way.
    """
    for op, inv in INVERSE_OPERATOR.items():
        if op == "<>":
            continue
        assert INVERSE_OPERATOR[inv] == op, f"{op} -> {inv} -> {INVERSE_OPERATOR[inv]}"


# ---------------------------------------------------------------------------
# Domain optimisation: original immutability + output is model-specific
# ---------------------------------------------------------------------------
def test_optimize_does_not_mutate_the_original_domain() -> None:
    """The optimiser returns new nodes; the original is never advanced.

    This is what makes reusing an *un-optimised* domain across models safe.
    """
    with model_test_env(IAlpha, IBeta) as env:
        original = Domain([("ref", "=", "x")])
        level_before = original._opt_level

        out_alpha = original.optimize_full(env["i.alpha"])
        assert original._opt_level == level_before  # untouched
        assert out_alpha is not original

        # Re-optimising the SAME original against a different model yields that
        # model's result, not a cached one.
        out_beta = original.optimize_full(env["i.beta"])
        assert list(out_alpha) == [("id", "in", [11, 22])]  # search() substituted
        assert list(out_beta) == [("ref", "in", ["x"])]  # plain stored field


def test_optimized_output_is_model_specific_not_reusable_across_models() -> None:
    """An optimised *output* is fully resolved for exactly ONE model.

    Reusing it against another model returns the first model's (stale) result —
    documented here so a future change that reuses optimised outputs
    cross-model is caught.
    """
    with model_test_env(IAlpha, IBeta) as env:
        out_alpha = Domain([("ref", "=", "x")]).optimize_full(env["i.alpha"])
        # The output is already FULL: re-optimising it against beta is a no-op,
        # so it keeps alpha's substitution. This is *why* callers must optimise
        # a fresh domain per model (every ORM call site does).
        reused = out_alpha.optimize_full(env["i.beta"])
        assert list(reused) == [("id", "in", [11, 22])]  # alpha's result, stale


# ---------------------------------------------------------------------------
# Scalar fast-path "no value" sentinel agreement
# ---------------------------------------------------------------------------
def test_scalar_none_value_is_record_independent() -> None:
    """The scalar fast paths must agree on the "no value" sentinel.

    ``read._read_format`` passes ``convert_to_record(None, None)`` while
    ``traversal.mapped``/``sorted`` pass ``(None, rec[:1])``. They MUST agree
    for every fast-path scalar type, else the same empty value reads differently
    depending on the access method.
    """
    with model_test_env(IScalars, ICurrency) as env:
        model = env["i.scalars"]
        rec = model.create({})
        for fname in _FASTPATH_SCALARS:
            field = model._fields[fname]
            via_none = field.convert_to_record(None, None)
            via_rec = field.convert_to_record(None, rec[:1])
            assert via_none == via_rec, fname


def _fastpath_cache_to_record(field: fields.Field) -> Callable[[Any], Any] | None:
    """Extract the ``cache_to_record`` lambda from a ``_make_scalar_get`` getter.

    Returns the lambda baked into the field's ``__get__`` closure, or ``None``
    if the field does not use that fast path.
    """
    for klass in type(field).__mro__:
        fn = klass.__dict__.get("__get__")
        if fn is None:
            continue
        freevars = getattr(getattr(fn, "__code__", None), "co_freevars", ())
        if "cache_to_record" in freevars:
            return fn.__closure__[freevars.index("cache_to_record")].cell_contents
        return None  # first __get__ in MRO is not a _make_scalar_get one
    return None


_FASTPATH_CACHE_SAMPLES = {
    "f_bool": [None, False, True],
    "f_int": [None, 0, 7],
    "f_float": [None, 0.0, 3.5],
    "f_money": [None, 0.0, 3.5],
    "f_sel": [None, "a"],
    "f_date": [None, date(2020, 1, 2)],
    "f_dt": [None, datetime(2020, 1, 2, 3, 4)],
}


def test_scalar_fastpath_lambda_matches_convert_to_record() -> None:
    """The fast-path getter's cache->record lambda MUST equal convert_to_record.

    ``_make_scalar_get`` bakes a lambda (e.g. ``v or 0``) into ``__get__`` for a
    singleton cache hit; a cache miss falls back to ``Field.__get__`` →
    ``convert_to_record``. They are written separately per field type, so this
    pins them together — otherwise the same cached value would read differently
    via the Rust fast path than via the Python fallback (a silent, test-evading
    divergence). The pre-existing sentinel test only compares ``convert_to_record``
    to itself; this one compares it to the actual fast-path lambda.
    """
    with model_test_env(IScalars, ICurrency) as env:
        model = env["i.scalars"]
        rec = model.create({})[:1]
        checked = []
        for fname in _FASTPATH_SCALARS:
            field = model._fields[fname]
            cache_to_record = _fastpath_cache_to_record(field)
            if cache_to_record is None:
                continue  # Char/Text use BaseString.__get__, not the lambda path
            checked.append(fname)
            for v in _FASTPATH_CACHE_SAMPLES[fname]:
                fast = cache_to_record(v)
                slow = field.convert_to_record(v, rec)
                assert fast == slow, (
                    f"{fname}: fast-path lambda({v!r})={fast!r} != "
                    f"convert_to_record({v!r})={slow!r}"
                )
        # guard against the fast paths silently disappearing (e.g. a refactor
        # that drops _make_scalar_get) — that would make this test vacuous.
        assert set(checked) == set(_FASTPATH_CACHE_SAMPLES), checked


# ---------------------------------------------------------------------------
# model_test_env degradation is visible, real errors propagate
# ---------------------------------------------------------------------------
def test_missing_comodel_is_tolerated_and_recorded() -> None:
    """A missing comodel degrades the field but the degradation stays visible.

    It is recorded in ``registry.degraded_fields``.
    """

    class WithGhost(models.Model):
        """Field pointing at an absent comodel."""

        _name = "i.withghost"
        # Own module: model_test_env auto-discovers a whole module, and this
        # model is intentionally degraded — keep it out of other tests' builds.
        _module = _MOD + ".ghost"
        _description = "Absent-comodel host"

        name = fields.Char()
        ghost_id = fields.Many2one("i.does.not.exist")

    with model_test_env(WithGhost) as env:
        degraded = {f"{f.model_name}.{f.name}" for f in env.registry.degraded_fields}
        assert "i.withghost.ghost_id" in degraded
        # harness remains usable for the well-formed fields
        assert env["i.withghost"].create({"name": "ok"}).name == "ok"


def test_real_dependency_error_propagates_not_swallowed() -> None:
    """A genuine ``@depends`` failure must fail the build, not degrade silently.

    Only a missing comodel is tolerated; otherwise tests would pass while a
    stored computed field stops recomputing in production.
    """

    class BadDepends(models.Model):
        """A model whose dependency resolution raises by design."""

        _name = "i.bad"
        # Own module: this model raises during dependency resolution by design;
        # isolating it prevents module auto-discovery from poisoning other builds.
        _module = _MOD + ".bad"
        _description = "Broken @depends"

        a = fields.Integer()
        b = fields.Integer(compute="_compute_b", store=True)

        @api.depends(lambda self: 1 / 0)  # raises during get_depends
        def _compute_b(self) -> None:
            """Never reached: dependency resolution fails first."""
            for rec in self:
                rec.b = rec.a

    raised = False
    try:
        with model_test_env(BadDepends):
            pass
    except ZeroDivisionError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# Monetary currency resolution
# ---------------------------------------------------------------------------
def test_monetary_column_rounds_via_currency() -> None:
    """``Monetary.convert_to_column`` rounds through the record's currency.

    It falls back to a raw float when no currency is set.
    """
    with model_test_env(ICurrency, IInvoice) as env:
        cur = env["res.currency"].create({"name": "USD", "rounding": 0.01})
        inv = env["i.invoice"].create({"currency_id": cur.id, "amount": 3.14159})
        field = env["i.invoice"]._fields["amount"]

        assert field._currency_record(inv) == cur
        assert abs(field.convert_to_column(3.14159, inv) - 3.14) < 1e-9

        # no currency -> raw passthrough (no rounding)
        plain = env["i.invoice"].create({"amount": 9.999})
        assert abs(field.convert_to_column(9.999, plain) - 9.999) < 1e-9


# ---------------------------------------------------------------------------
# Recordset construction
# ---------------------------------------------------------------------------
def test_every_construction_path_sets_all_slots() -> None:
    """All recordset-construction paths populate the full ``__slots__`` set.

    ``BaseModel._spawn`` is the single source of truth for the slots; a handful
    of per-record hot loops (``__iter__``, ``__reversed__``, ``RecomputeMixin._flush``,
    ``Environment.__getitem__``) inline the same assignments for speed. This
    guards against a new slot being added to ``__slots__``/``_spawn`` while a
    hot-loop mirror or a construction helper forgets to set it — which would
    silently yield records missing state.
    """
    from odoo.orm.models.base import BaseModel

    slots = tuple(BaseModel.__slots__)
    assert slots, "BaseModel must declare __slots__"

    with model_test_env(IScalars, ICurrency) as env:
        Model = env["i.scalars"]
        recs = Model.create([{"f_int": i} for i in range(3)])

        def assert_full(rec: BaseModel, label: str) -> None:
            for slot in slots:
                assert hasattr(rec, slot), f"{label}: record missing slot {slot!r}"

        # canonical builder + the construction helpers that delegate to it
        assert_full(Model._spawn(env, (1,), (1,)), "_spawn")
        assert_full(Model.browse((1, 2)), "browse")
        assert_full(recs.with_env(env), "with_env")
        assert_full(recs.with_prefetch((1,)), "with_prefetch")
        assert_full(recs[1:], "__getitem__ slice")
        assert_full(recs[0], "__getitem__ int")
        assert_full(recs.sorted("f_int"), "sorted")
        # the inline-mirror hot paths (size > 1 to hit the per-record loops)
        assert_full(next(iter(recs)), "__iter__")
        assert_full(next(reversed(recs)), "__reversed__")
        assert_full(env["i.scalars"], "Environment.__getitem__")


# ---------------------------------------------------------------------------
# Persistence backend seam (ADR-0011)
# ---------------------------------------------------------------------------
def test_persistence_backend_seam_is_wired() -> None:
    """CRUD dispatches through ``env.backend``, not ``transaction.storage``.

    The DB-free tier opens its transaction with a storage backend, so
    ``env.backend`` must resolve to an :class:`InMemoryBackend` (production opens
    with no storage and gets ``None`` — the SQL fast path). This pins the seam
    that ADR-0011 introduced; if the backend stopped being wired, the in-memory
    CRUD paths would silently fall through to SQL and the whole Tier-2 suite
    would break with obscure cursor errors instead of failing here clearly.
    """
    from odoo.orm.runtime.backend import InMemoryBackend

    with model_test_env(IScalars) as env:
        backend = env.backend
        assert isinstance(backend, InMemoryBackend), (
            f"env.backend must be an InMemoryBackend in the DB-free tier, "
            f"got {backend!r}"
        )
        # this backend has no hierarchy support; create/write skip parent_path
        assert backend.supports_parent_store is False
        # it is derived once from the transaction's storage, not re-created
        assert env.backend is env.transaction.backend


# ---------------------------------------------------------------------------
# Field cache shape (Theme A1)
# ---------------------------------------------------------------------------
# FieldCache owns the single decode of the context-dependent cache shape
# ({cache_key: {id: value}}); Field supplies only the shape bit
# (_is_context_dependent) and delegates via env._core.invalidate /
# all_cached_ids. These pin the one subtlety the Tier-2 model suite does not
# otherwise exercise: the *mixed* setup-window state where stale flat entries
# (written before field_depends_context was populated) coexist with
# per-context sub-dicts. The discriminator is the KEY (cache keys are tuples,
# record ids never are) — never the value, which would mistake dict-valued
# caches (company-dependent Json/Properties) for per-context sub-dicts.
def test_all_cached_ids_spans_per_context_subdicts() -> None:
    """A context-dependent field's ids are merged across per-context sub-dicts."""
    from odoo.orm.components.cache import FieldCache

    cache = FieldCache()
    cache._data["G"] = {("en_US",): {1: "a"}, ("fr_FR",): {2: "b"}}
    assert set(cache.all_cached_ids("G", context_dependent=True)) == {1, 2}


def test_all_cached_ids_skips_stale_flat_entries() -> None:
    """Stale flat entries coexisting with sub-dicts are not decoded as caches.

    Key-based decode: even a *dict-valued* stale flat entry (company-dependent
    Json written during the setup window) is excluded — its JSON keys must
    never be reported as record ids.
    """
    from odoo.orm.components.cache import FieldCache

    cache = FieldCache()
    cache._data["G"] = {
        ("en_US",): {1: "a"},
        5: "stale-scalar",
        6: None,
        7: {"json-key": "v"},  # dict-valued stale flat entry (Json)
    }
    assert set(cache.all_cached_ids("G", context_dependent=True)) == {1}


def test_invalidate_mixed_state_never_reaches_into_json_values() -> None:
    """Invalidating ids in the mixed state pops whole stale flat entries.

    The old value-based decode treated a dict-valued stale flat entry as a
    per-context sub-dict and popped *record ids inside the cached JSON value*.
    The key-based decode pops the entry by its id key and trims real
    (tuple-keyed) sub-dicts only.
    """
    from odoo.orm.components.cache import FieldCache

    cache = FieldCache()
    cache._data["G"] = {
        ("en_US",): {1: "a", 2: "b"},
        1: {2: "json-payload"},  # stale flat Json entry for record id 1
    }
    cache.invalidate("G", [2], context_dependent=True)
    # id 2 trimmed from the real sub-dict...
    assert cache._data["G"][("en_US",)] == {1: "a"}
    # ...and the stale Json value for id 1 is untouched inside (its key `2`
    # is a JSON key, not a record id)
    assert cache._data["G"][1] == {2: "json-payload"}
    # invalidating id 1 removes the stale flat entry wholesale
    cache.invalidate("G", [1], context_dependent=True)
    assert 1 not in cache._data["G"]
    assert cache._data["G"][("en_US",)] == {}  # kept (identity-preserving)
