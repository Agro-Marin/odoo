"""A refused trigger publication is memoized, and only the barrier heals it.

``Registry._field_triggers`` is a ``cached_property``.  When its
epoch-validated publication loses the race against a registry teardown, it
returns the *currently published* map and records
``_field_triggers_refused_at`` so ``_ensure_field_triggers()`` can rebuild once
the teardown ends.  Because it is a ``cached_property``, the refused (stale)
map is memoized on the registry until something pops it -- and the only thing
that pops it is ``_ensure_field_triggers()``.

That matters because ``ModelGraph.set_triggers`` publishes by **swapping** a
fresh ``_TriggerState`` (``self._state = state``), never by mutating in place.
So the dict handed back at refusal time is a different object from the one the
authoritative rebuild later publishes: a caller holding the memo does not
"catch up" -- it reads a snapshot that is permanently behind.

``test_invalidation_barrier_leak.py`` measured the *other* half of this and
concluded a refusal "does not stop recomputation", which is true **for callers
that go through the barrier**.  These tests pin the half that is not true for a
caller that reads the attribute directly.

DB-free: the mixin is exercised against a minimal fake registry, which is all
``_RegistryFieldsMixin`` actually needs (``models`` + ``model_graph``).
"""

from collections import defaultdict

from odoo.orm.components.model_graph import ModelGraph
from odoo.orm.runtime._registry_fields import _RegistryFieldsMixin


class _FakeField:
    """A field-like satisfying ``components._protocols.FieldLike``.

    The trigger build and the derived-cache precomputation in ``freeze()``
    read exactly this surface; keeping the double aligned with the protocol
    is the point of the protocol existing.
    """

    def __init__(self, name, model_name, depends=()):
        self.name = name
        self.model_name = model_name
        self.type = "integer"
        self.store = True
        self.relational = False
        self.compute = None
        self.recursive = False
        self.inverse_name = None
        self.comodel_name = None
        self.base_field = self
        self.manual = False
        self._depends = depends

    @property
    def is_stored_computed(self):
        return bool(self.store and self.compute)

    def resolve_depends(self, registry):
        """Yield one dependency chain per entry, as the real Field does."""
        yield from self._depends

    def __repr__(self):
        return f"<_FakeField {self.model_name}.{self.name}>"


class _FakeModel:
    def __init__(self, fields):
        self._abstract = False
        self._fields = {f.name: f for f in fields}


class _FakeRegistry(_RegistryFieldsMixin):
    """Enough of a Registry for the field-dependency mixin to run."""

    def __init__(self, models):
        self.models = models
        self.model_graph = ModelGraph()


def _registry_with(*, extra_trigger=False):
    """A registry whose field ``b`` depends on ``a`` (plus optionally ``c``)."""
    a = _FakeField("a", "m")
    b = _FakeField("b", "m", depends=[(a,)])
    fields = [a, b]
    if extra_trigger:
        c = _FakeField("c", "m", depends=[(a,)])
        fields.append(c)
    return _FakeRegistry({"m": _FakeModel(fields)}), a


def test_happy_path_publishes_and_memoizes():
    registry, dep = _registry_with()
    triggers = registry._ensure_field_triggers()
    assert dep in triggers, "the dependency must appear in the published map"
    # cached_property memoized the same object the graph publishes
    assert registry.__dict__["_field_triggers"] is registry.model_graph._triggers


def test_refused_publication_records_the_epoch_it_lost_at():
    registry, _dep = _registry_with()
    registry._ensure_field_triggers()

    registry.model_graph.begin_invalidation()
    registry.__dict__.pop("_field_triggers", None)

    # A reader rebuilds while the teardown window is open: refused.
    assert registry._field_triggers is registry.model_graph.published_triggers
    assert "_field_triggers_refused_at" in registry.__dict__


def test_a_refused_memo_goes_permanently_stale_but_the_barrier_heals_it():
    """The defect this file exists for: direct read vs. ``_ensure_field_triggers``."""
    registry, dep = _registry_with()
    registry._ensure_field_triggers()

    # --- the race: a teardown opens, and a reader rebuilds inside the window.
    registry.model_graph.begin_invalidation()
    registry.__dict__.pop("_field_triggers", None)
    refused_map = registry._field_triggers  # loses, memoizes the old snapshot
    assert "_field_triggers_refused_at" in registry.__dict__

    # --- the teardown ends and the authoritative rebuild publishes a NEW map,
    #     as `_discard_fields` / `_setup_models__` do.  A new field `c` now
    #     also depends on `a`.
    registry.model_graph.end_invalidation()
    new_triggers = defaultdict(lambda: defaultdict(list))
    new_field = _FakeField("c", "m")
    new_triggers[dep][()] = [new_field]
    assert registry.model_graph.set_triggers(new_triggers) is True

    # The publication swapped in a fresh _TriggerState, so the memo is now a
    # *different object* from what the graph serves.
    assert registry.__dict__["_field_triggers"] is refused_map
    assert refused_map is not registry.model_graph._triggers

    # A direct attribute read -- what a caller that skips the barrier does --
    # still sees the pre-teardown map and misses the new trigger entirely.
    assert new_field not in registry._field_triggers[dep][()]

    # Going through the barrier rebuilds and sees it.
    healed = registry._ensure_field_triggers()
    assert healed is registry.model_graph._triggers
    assert healed is not refused_map


def _direct_attribute_reads():
    """Every ``x._field_triggers`` attribute read in production ``orm/`` code.

    ``_registry_fields.py`` is exempt: it *defines* the ``cached_property`` and
    its barrier, so it is the one place that reads it deliberately.  Note the
    ``__dict__.pop("_field_triggers")`` sites in ``registry.py`` /
    ``model_test_env.py`` are string subscripts, not attribute reads, so they
    are correctly invisible to this scan.
    """
    import ast
    import pathlib

    orm_dir = pathlib.Path(__file__).resolve().parent.parent
    return [
        f"{path.relative_to(orm_dir.parent)}:{node.lineno}"
        for path in orm_dir.rglob("*.py")
        if "tests" not in path.parts and path.name != "_registry_fields.py"
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute) and node.attr == "_field_triggers"
    ]


def test_no_production_caller_reads_the_memo_directly():
    """Callers must use ``_ensure_field_triggers()``, which heals a stale memo.

    This failed on ``orm/models/mixins/recompute.py`` -- the early-exit guard
    of ``modified()``, the ORM's central invalidation entry point -- which read
    ``self.pool._field_triggers`` and so could skip recomputation entirely
    against a stale map.
    """
    leaking = _direct_attribute_reads()
    assert not leaking, (
        "read `_field_triggers` directly instead of calling "
        "`_ensure_field_triggers()`: " + ", ".join(leaking)
    )
