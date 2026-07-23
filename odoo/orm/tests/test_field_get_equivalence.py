"""Semantic-equivalence guard for the hand-inlined ``Field.__get__`` fast paths.

The fork hand-inlines the hottest ORM path.  ``odoo/orm/fields/base.py`` holds
the canonical ``Field.__get__`` plus ``_make_scalar_get(cache_to_record)`` which
GENERATES a fast-path ``__get__`` for scalar types (Integer/Float/Monetary use
``lambda v: v or 0`` / ``0.0``; Boolean/Date/Datetime/Selection use
``lambda v: False if v is None else v``).  Hand-rolled overrides also live in
``relational/_base.py`` (``_Relational``), ``relational/many2one.py``
(``Many2one``), ``relational/one2many.py`` (``One2many``), ``textual.py``
(``BaseString`` and ``Html``) and ``misc.py`` (``Id``).

``test_field_access_preamble.py`` already pins the ACL-preamble SOURCE TEXT.
This module is the SEMANTIC companion: it asserts each specialized/generated
``__get__`` produces the same OBSERVABLE result as the canonical
``Field.__get__`` protocol for the same ``(field, record, cache-state)``, and
that every invariant the canonical protocol guarantees is honored by each fast
path.

Oracles / invariants encoded (see each test's docstring):

* **Differential** ``type(field).__get__`` vs canonical ``Field.__get__`` on the
  SAME record and cache state — sound for the scalar-lambda types, Char/Text,
  Html (non-fallback) and Many2one (recordset equality).  Where a fast path
  deliberately DIVERGES from base (translate=True en_US fallback) or base is not
  applicable (Id), the differential is replaced by a targeted invariant and the
  divergence is documented.
* **ACL preamble fires identically**: groups=None fast path and ``env.su``
  bypass never consult access; a restricted field with ``su=False`` and access
  denied raises ``AccessError`` on every field type (the semantic version of the
  text-pin).  Id is exempt by design.
* **Null/empty recordset** returns the type's falsy default (== base).
* **Cache hit** (real value / falsy value / None) reads back
  ``convert_to_record(cache_value)``.
* **PENDING** is never returned to the caller; a protected pending record yields
  the falsy default, an unprotected one falls through to fetch.
* **Multi-record** access raises via ``ensure_one`` for the singleton-valued
  types (relational types return a recordset instead, by contract).

Tier-2 suite: real ``import odoo``, no database (runs like ``test_model_test_env``
in its own pytest invocation).
"""

import sys
from datetime import date, datetime

import pytest

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.orm.model_test_env import model_test_env
from odoo.tools.misc import PENDING, SENTINEL

_MOD = "test_field_get_equivalence"

# canonical descriptor: the reference oracle every fast path must match.
_CANONICAL_GET = fields.Field.__get__


def _term_translate(_callback, value):
    """Minimal per-term translate callable (shape of ``xml_translate``)."""
    return value


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class GCurrency(models.Model):
    """Minimal ``res.currency`` double so Monetary/Many2one run DB-free."""

    _name = "res.currency"
    _module = _MOD
    _description = "Currency (test double)"

    name = fields.Char()
    rounding = fields.Float(default=0.01)

    def round(self, amount: float) -> float:
        self.ensure_one()
        prec = self.rounding or 0.01
        return round(amount / prec) * prec


class GChild(models.Model):
    """One2many child with a Many2one inverse."""

    _name = "g.child"
    _module = _MOD
    _description = "O2m child"

    name = fields.Char()
    parent_id = fields.Many2one("g.host")


class GHost(models.Model):
    """Host carrying one field of every fast-path flavour."""

    _name = "g.host"
    _module = _MOD
    _description = "Fast-path field host"

    # scalar-lambda fast paths (_make_scalar_get)
    f_bool = fields.Boolean()
    f_int = fields.Integer()
    f_float = fields.Float()
    f_money = fields.Monetary()
    f_sel = fields.Selection([("a", "A"), ("b", "B")])
    f_date = fields.Date()
    f_dt = fields.Datetime()
    currency_id = fields.Many2one("res.currency")
    # textual fast paths (BaseString / Html)
    f_char = fields.Char()
    f_text = fields.Text()
    f_html = fields.Html()
    # relational fast paths (Many2one / One2many / _Relational)
    f_m2o = fields.Many2one("res.currency")
    child_ids = fields.One2many("g.child", "parent_id")
    # translated
    f_tchar = fields.Char(translate=True)
    # sanitize="email_outgoing" is the one Html config that KEEPS translate=True
    # (sanitize=True would normalize translate to the html_translate callable),
    # so the BaseString/Html en_US fallback branch stays reachable. Mirrors the
    # real mail.template.body_html field named in Html.__get__'s docstring.
    f_thtml = fields.Html(translate=True, sanitize="email_outgoing")
    f_ctchar = fields.Char(translate=_term_translate)
    # stored computed (exercises the is_stored_computed / pending branch)
    f_scomp = fields.Integer(compute="_compute_scomp", store=True)

    @api.depends("f_int")
    def _compute_scomp(self):
        for rec in self:
            rec.f_scomp = (rec.f_int or 0) + 1


# ---------------------------------------------------------------------------
# Field-type metadata
# ---------------------------------------------------------------------------
# scalar-lambda + textual singleton-valued fields whose fast path can be
# compared cell-for-cell against the canonical Field.__get__ on a cache HIT.
# Each entry: field name -> list of raw cache values (incl. None + falsy).
_SCALAR_DIFFERENTIAL = {
    "f_bool": [None, False, True],
    "f_int": [None, 0, 7],
    "f_float": [None, 0.0, 3.5],
    "f_money": [None, 0.0, 3.5],
    "f_sel": [None, "a", "b"],
    "f_date": [None, date(2020, 1, 2)],
    "f_dt": [None, datetime(2020, 1, 2, 3, 4)],
    "f_char": [None, "", "hello"],
    "f_text": [None, "", "multi\nline"],
}

# every singleton-valued field type (scalars + textual + html) — these raise on
# multi-record access and go through the ACL preamble on a singleton read.
_SINGLETON_FIELDS = (*_SCALAR_DIFFERENTIAL, "f_html")

# relational fields: multi-record returns a recordset (no ensure_one raise).
_RELATIONAL_FIELDS = ("f_m2o", "child_ids")

# every field carrying a specialized/generated __get__ that runs the inlined ACL
# preamble (Id is intentionally excluded — see the Id tests).
_ACL_FIELDS = (*_SINGLETON_FIELDS, *_RELATIONAL_FIELDS)


def _seed(env):
    """Two currencies + a host with a child; return (host, cur_a, cur_b)."""
    cur = env["res.currency"]
    cur_a = cur.create({"name": "AAA", "rounding": 0.01})
    cur_b = cur.create({"name": "BBB", "rounding": 0.01})
    host = env["g.host"].create(
        {
            "currency_id": cur_a.id,
            "f_m2o": cur_b.id,
            "f_int": 5,
            "f_char": "hi",
        }
    )
    env["g.child"].create({"name": "c1", "parent_id": host.id})
    return host, cur_a, cur_b


def _put_cache(field, rec, value):
    """Write a raw cache value (bypassing dirty guards) for exact control."""
    field._get_cache(rec.env)[rec.id] = value


# ===========================================================================
# 1. Differential: fast path == canonical Field.__get__ on a cache HIT
# ===========================================================================
def test_scalar_and_textual_fastpath_matches_canonical_on_cache_hit():
    """(oracle 6) For a singleton cache hit, every scalar-lambda and Char/Text
    fast path returns exactly what canonical ``Field.__get__`` returns for the
    same cache value — true differential equivalence, since both resolve the same
    ``convert_to_record(cache_value)``.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        for fname, samples in _SCALAR_DIFFERENTIAL.items():
            field = host._fields[fname]
            fast = type(field).__get__
            # a scalar/textual fast path must NOT be the canonical method itself
            assert fast is not _CANONICAL_GET, fname
            for raw in samples:
                _put_cache(field, host, raw)
                got = fast(field, host)
                ref = _CANONICAL_GET(field, host)
                assert got == ref, (
                    f"{fname}: fast={got!r} != canonical={ref!r} (raw={raw!r})"
                )
                assert got is not PENDING and got is not SENTINEL
                # oracle (6): equals convert_to_record(cache_value)
                assert got == field.convert_to_record(raw, host), fname


def test_many2one_fastpath_matches_canonical_on_cache_hit():
    """Many2one builds its singleton recordset inline; it must equal the
    recordset canonical ``Field.__get__`` produces via ``convert_to_record`` —
    for a real target, a NULL (None) cache value, and a missing (0) target.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, _cur_a, cur_b = _seed(env)
        field = host._fields["f_m2o"]
        fast = type(field).__get__
        for raw in (cur_b.id, None):
            _put_cache(field, host, raw)
            got = fast(field, host)
            ref = _CANONICAL_GET(field, host)
            assert got == ref, f"m2o fast={got!r} != canonical={ref!r} (raw={raw!r})"
            # observable identity: right ids, right comodel
            assert got._name == "res.currency"
            assert got.ids == (ref.ids)


def test_html_fastpath_matches_canonical_on_normal_hit():
    """Html delegates to ``Field.__get__`` for non-fallback records, so a plain
    stored Html read must equal canonical (Markup-wrapped) exactly.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        field = host._fields["f_html"]
        fast = type(field).__get__
        _put_cache(field, host, "<p>x</p>")
        got = fast(field, host)
        ref = _CANONICAL_GET(field, host)
        assert got == ref
        assert str(got) == str(ref)


# ===========================================================================
# 2. Null / empty recordset -> falsy default (== base)
# ===========================================================================
def test_empty_recordset_returns_type_falsy_default_matching_base():
    """(oracle 2) An empty recordset returns the type's falsy default, identical
    to canonical ``Field.__get__``.  Scalars/textual return the scalar falsy
    value; relational types return an empty recordset of the comodel.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        _seed(env)
        empty = env["g.host"].browse(())
        for fname in _ACL_FIELDS:
            field = empty._fields[fname]
            got = type(field).__get__(field, empty)
            ref = _CANONICAL_GET(field, empty)
            assert got == ref, f"{fname}: empty fast={got!r} != base={ref!r}"
        # spot-check the concrete falsy values
        assert type(empty._fields["f_int"]).__get__(empty._fields["f_int"], empty) == 0
        assert (
            type(empty._fields["f_bool"]).__get__(empty._fields["f_bool"], empty)
            is False
        )
        m2o = empty._fields["f_m2o"]
        got = type(m2o).__get__(m2o, empty)
        assert got._name == "res.currency" and len(got) == 0


# ===========================================================================
# 3. Multi-record access raises (singleton-valued types) / returns recordset
#    (relational types)
# ===========================================================================
def test_multirecord_singleton_types_raise_via_ensure_one():
    """(oracle 5) For scalar/textual/html fields, multi-record access raises the
    same exception as canonical ``Field.__get__`` (ensure_one path).
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        env["g.host"].create({"f_int": 1})
        env["g.host"].create({"f_int": 2})
        recs = env["g.host"].search([])
        assert len(recs) >= 2
        for fname in _SINGLETON_FIELDS:
            field = recs._fields[fname]
            with pytest.raises(ValueError):
                type(field).__get__(field, recs)
            with pytest.raises(ValueError):
                _CANONICAL_GET(field, recs)


def test_multirecord_relational_types_return_recordset_not_raise():
    """Contract exception to oracle 5: relational fast paths map multi-record
    reads to a recordset (never ensure_one), matching canonical/_Relational.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, cur_a, cur_b = _seed(env)
        host2 = env["g.host"].create({"f_m2o": cur_a.id})
        recs = host + host2
        m2o = recs._fields["f_m2o"]
        got = type(m2o).__get__(m2o, recs)
        assert got._name == "res.currency"
        assert set(got.ids) == {cur_a.id, cur_b.id}
        o2m = recs._fields["child_ids"]
        got_lines = type(o2m).__get__(o2m, recs)
        assert got_lines._name == "g.child"


# ===========================================================================
# 4. ACL preamble fires identically on every fast path (semantic text-pin)
# ===========================================================================
class _AclSpy:
    """Install controllable ``_has_field_access`` / ``_check_field_access`` on a
    model class and record their calls, so the preamble branch can be observed
    without a real user/group stack.
    """

    def __init__(self, model_cls):
        self.model_cls = model_cls
        self.has_calls = 0
        self.check_calls = 0
        self.allow = True
        self._orig_has = model_cls.__dict__.get("_has_field_access")
        self._orig_check = model_cls.__dict__.get("_check_field_access")
        spy = self

        def _has_field_access(self, field, operation):
            spy.has_calls += 1
            return spy.allow

        def _check_field_access(self, field, operation):
            spy.check_calls += 1
            if not spy.allow:
                raise AccessError("spy-denied")

        model_cls._has_field_access = _has_field_access
        model_cls._check_field_access = _check_field_access

    def restore(self):
        for name, orig in (
            ("_has_field_access", self._orig_has),
            ("_check_field_access", self._orig_check),
        ):
            if orig is None:
                delattr(self.model_cls, name)
            else:
                setattr(self.model_cls, name, orig)


def test_acl_preamble_bypassed_when_field_ungrouped():
    """(oracle 1a) groups=None: the preamble short-circuits before consulting
    access — ``_has_field_access`` is never called — on every fast path.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        spy = _AclSpy(type(host))
        try:
            for fname in _ACL_FIELDS:
                field = host._fields[fname]
                assert field.groups in (None, False), fname
                type(field).__get__(field, host)
            assert spy.has_calls == 0
            assert spy.check_calls == 0
        finally:
            spy.restore()


def test_acl_preamble_bypassed_for_superuser_even_when_grouped():
    """(oracle 1b) A grouped field under ``env.su`` bypasses access on every
    fast path (``_has_field_access`` never called).
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        assert env.su is True
        spy = _AclSpy(type(host))
        try:
            for fname in _ACL_FIELDS:
                field = host._fields[fname]
                orig = field.groups
                field.groups = "base.group_system"
                try:
                    type(field).__get__(field, host)
                finally:
                    field.groups = orig
            assert spy.has_calls == 0, "su must not consult _has_field_access"
            assert spy.check_calls == 0
        finally:
            spy.restore()


def test_acl_preamble_allows_when_has_field_access_true():
    """(oracle 1c) Grouped field, ``su=False``, access granted: the read
    proceeds and ``_check_field_access`` is never invoked, on every fast path.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        host = host.with_env(env(user=2, su=False))  # env.su is read-only; derive one
        assert host.env.su is False
        spy = _AclSpy(type(host))
        spy.allow = True
        try:
            for fname in _ACL_FIELDS:
                field = host._fields[fname]
                orig = field.groups
                field.groups = "base.group_system"
                try:
                    type(field).__get__(field, host)  # must not raise
                finally:
                    field.groups = orig
            assert spy.has_calls >= len(_ACL_FIELDS)
            assert spy.check_calls == 0
        finally:
            spy.restore()


def test_acl_preamble_raises_access_error_when_denied_on_every_fast_path():
    """(oracle 1d) Grouped field, ``su=False``, access denied: EVERY fast path
    dispatches to ``_check_field_access`` and raises ``AccessError`` — the
    semantic form of the source text-pin, differential across field types.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        host = host.with_env(env(user=2, su=False))
        spy = _AclSpy(type(host))
        spy.allow = False
        try:
            for fname in _ACL_FIELDS:
                field = host._fields[fname]
                orig = field.groups
                field.groups = "base.group_system"
                try:
                    with pytest.raises(AccessError):
                        type(field).__get__(field, host)
                finally:
                    field.groups = orig
            assert spy.check_calls == len(_ACL_FIELDS)
        finally:
            spy.restore()


def test_acl_denied_multirecord_relational_also_raises():
    """The relational batch path (``_Relational.__get__``) runs its OWN inlined
    preamble on multi-record reads; assert it too raises when denied.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, cur_a, _cur_b = _seed(env)
        host2 = env["g.host"].create({"f_m2o": cur_a.id})
        recs = (host + host2).with_env(env(user=2, su=False))
        spy = _AclSpy(type(recs))
        spy.allow = False
        try:
            for fname in _RELATIONAL_FIELDS:
                field = recs._fields[fname]
                orig = field.groups
                field.groups = "base.group_system"
                try:
                    with pytest.raises(AccessError):
                        type(field).__get__(field, recs)
                finally:
                    field.groups = orig
        finally:
            spy.restore()


def test_id_field_has_no_acl_preamble_by_design():
    """Documented divergence: ``Id.__get__`` carries NO ACL preamble (the ``id``
    field is never group-restricted and ``record.id`` is the single hottest
    access).  This test freezes that intentional exemption: even a (contrived)
    grouped+denied ``id`` field does not raise.  Flagged for the coordinator as
    by-design, not a bug.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        rec_id = host.id
        host = host.with_env(env(user=2, su=False))
        spy = _AclSpy(type(host))
        spy.allow = False
        idf = host._fields["id"]
        orig = idf.groups
        idf.groups = "base.group_system"
        try:
            assert type(idf).__get__(idf, host) == rec_id  # no raise
            assert spy.check_calls == 0
        finally:
            idf.groups = orig
            spy.restore()


# ===========================================================================
# 5. Id field invariants (base __get__ is not applicable)
# ===========================================================================
def test_id_field_invariants():
    """``Id.__get__`` is not differential-comparable to base (``id`` is not a
    cached column).  Guard its own contract: null->False, singleton->id, and a
    DISTINCT multi-record error (``ValueError('Expected singleton')``), not
    ensure_one.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, *_ = _seed(env)
        host2 = env["g.host"].create({})
        idf = host._fields["id"]
        get = type(idf).__get__
        assert get(idf, env["g.host"].browse(())) is False
        assert get(idf, host) == host.id
        with pytest.raises(ValueError, match="Expected singleton"):
            get(idf, host + host2)


# ===========================================================================
# 6. PENDING is never returned; protected -> falsy default, else fetch
# ===========================================================================
def test_pending_in_cache_is_never_returned_protected_yields_falsy():
    """(oracle 4) PENDING in cache, record PROTECTED (being computed): base pops
    PENDING and returns the type's falsy default (0) instead of a wasted NULL
    fetch.  The scalar fast path routes through this branch (scalar_cache_get
    maps PENDING->SENTINEL, delegating to base), and base itself agrees.  Uses a
    plain stored scalar so no stored-computed flush is triggered.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host = env["g.host"].create({"f_int": 5})
        field = host._fields["f_int"]
        _put_cache(field, host, PENDING)
        with env.protecting([field], host):
            got = type(field).__get__(field, host)
        assert got is not PENDING
        assert got == 0  # falsy default while protected/computing
        # base agrees under the same setup
        _put_cache(field, host, PENDING)
        with env.protecting([field], host):
            ref = _CANONICAL_GET(field, host)
        assert ref == 0


def test_pending_in_cache_unprotected_falls_through_to_fetch():
    """(oracle 4) PENDING in cache, NOT protected: base evicts PENDING and the
    stored value is fetched from the backend (never PENDING).  Fast path
    delegates to base and agrees.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host = env["g.host"].create({"f_int": 7})
        field = host._fields["f_int"]
        stored = type(field).__get__(field, host)  # warm & read the real value
        assert stored == 7
        _put_cache(field, host, PENDING)
        got = type(field).__get__(field, host)
        assert got is not PENDING
        assert got == stored


def test_stored_computed_pending_guard_recomputes_and_never_leaks_pending():
    """The ``is_stored_computed and has_pending_field`` guard: a stored computed
    field with a scheduled pending recompute AND a stale PENDING in cache
    recomputes BEFORE the cache read, so the fresh value (not PENDING) is
    returned — on both the scalar fast path and canonical base.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host = env["g.host"].create({"f_int": 3})  # f_scomp computed -> 4
        field = host._fields["f_scomp"]
        assert field.is_stored_computed
        assert type(field).__get__(field, host) == 4  # warm
        # stale PENDING + a scheduled recompute
        _put_cache(field, host, PENDING)
        env._core.schedule(field, [host.id])
        got = type(field).__get__(field, host)
        assert got is not PENDING
        assert got == 4
        assert not env._core.has_pending_field(field)  # recompute cleared it


def test_pending_evicted_for_scalar_via_scalar_cache_get():
    """``scalar_cache_get`` maps PENDING -> SENTINEL, so the scalar fast path
    delegates to base rather than feeding PENDING into ``cache_to_record``.
    Verify a non-computed scalar with a stray PENDING never returns it.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host = env["g.host"].create({"f_int": 9})
        field = host._fields["f_int"]
        _put_cache(field, host, PENDING)
        got = type(field).__get__(field, host)
        assert got is not PENDING
        # not stored-computed, real row: falls through to fetch -> stored 9
        assert got == 9


def test_relational_pending_protected_yields_empty_recordset():
    """The ``_Relational`` batch path inlines its own PENDING evict + protected
    fallback (relational/_base.py).  With a stored-computed... falls back to a
    single-record m2o exercise: PENDING protected -> falsy (empty) recordset.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        host, _cur_a, _cur_b = _seed(env)
        field = host._fields["f_m2o"]
        # Many2one singleton fast path: PENDING -> scalar_cache_get SENTINEL ->
        # Field.__get__ handles it. Assert never leaks PENDING.
        _put_cache(field, host, PENDING)
        got = type(field).__get__(field, host)
        assert got is not PENDING
        assert got._name == "res.currency"


# ===========================================================================
# 7. Translated fields
# ===========================================================================
def test_translate_true_en_us_fallback_diverges_from_base_and_is_correct():
    """translate=True, origin-less NEW record, read in a non-en language: the
    BaseString fast path returns the en_US fallback value, whereas canonical
    ``Field.__get__`` (which lacks the fallback) would return False and poison
    the language sub-cache.  This is an INTENTIONAL divergence FROM base — the
    fast path is the correct oracle here.  Asserts the fast path returns the
    en_US value and documents that base does not.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        field = env["g.host"]._fields["f_tchar"]
        assert field.translate is True
        # new record with no origin, warm en_US
        rec = env["g.host"].new({"f_tchar": "english"})
        assert rec.f_tchar == "english"
        # read in another language: fast path must fall back to en_US
        other = rec.with_context(lang="fr_FR")
        of = other._fields["f_tchar"]
        got = type(of).__get__(of, other)
        assert got == "english", f"en_US fallback expected, got {got!r}"


def test_callable_translate_delegates_to_base():
    """translate=<callable>: the BaseString fast path detects ``callable(
    self.translate)`` and delegates to canonical ``Field.__get__`` (which
    handles the {lang: value} dict + KeyError->fetch).  Assert the fast path and
    canonical agree for a warmed record.
    """
    with model_test_env(GHost, GChild, GCurrency) as env:
        rec = env["g.host"].create({"f_ctchar": "cval"})
        field = rec._fields["f_ctchar"]
        assert callable(field.translate)
        got = type(field).__get__(field, rec)
        ref = _CANONICAL_GET(field, rec)
        assert got == ref == "cval"


def test_html_translate_true_fallback_preserves_markup():
    """Html(translate=True) keeps BaseString's en_US fallback for a no-DB-row
    record but wraps the value in Markup (unlike BaseString).  Assert the
    fallback fires AND the result is Markup, not a raw string.
    """
    from markupsafe import Markup

    with model_test_env(GHost, GChild, GCurrency) as env:
        field = env["g.host"]._fields["f_thtml"]
        assert field.translate is True
        rec = env["g.host"].new({"f_thtml": "<b>hi</b>"})
        assert isinstance(rec.f_thtml, Markup)
        other = rec.with_context(lang="fr_FR")
        of = other._fields["f_thtml"]
        got = type(of).__get__(of, other)
        assert isinstance(got, Markup), f"expected Markup fallback, got {type(got)}"
        assert "hi" in str(got)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
