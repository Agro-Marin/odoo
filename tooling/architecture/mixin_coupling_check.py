#!/usr/bin/env python3
"""mixin_coupling_check.py — drift-zero gate on the ORM's mixin compositions.

``layer_check.py`` reasons about **import** edges, which is the right model for
every boundary in ``doc/architecture/ARCHITECTURE.md`` except one. ``BaseModel`` is composed
from 26 ``__slots__ = ()`` mixins by multiple inheritance; they collaborate
through ``self``, and a ``self._fields`` or ``self._search(...)`` produces **no
import edge at all**. So the most intricate coupling surface in the framework is
invisible to the checker that guards everything around it: a mixin can grow a
dependency on any other mixin, and no gate moves.

This reconstructs that graph from the AST and ratchets it.

TWO COMPOSITIONS
----------------

``BaseModel`` is not the only class built this way. ``Field`` is
``Field(_FieldDescriptionMixin, _FieldConvertMixin, _FieldSqlMixin)`` over a
``_FieldStubs`` typing declaration — the same construction, the same invisibility
to ``layer_check``, and until 2026-08-08 measured by nothing at all, while being
1401 lines against 628 in its three mixins (the inverse of the ratio ``models/``
reached). :class:`Composition` describes one; :data:`COMPOSITIONS` lists both,
each with its own floors, and a drift in either fails.

The first run of the ``Field`` graph found a 2-cycle, ``_field_convert`` <->
``base.py`` — see :data:`FIELD_BASELINE`. That is what generalising the gate was
worth: the tangle was there, and nothing could see it.

For ``Field`` the units are the mixin composition only. Concrete field types
(``BaseString(Field[...])``, ``Many2many(_RelationalMulti)``) are *subclasses*;
they override base methods freely — ``BaseString`` overrides six of ``Field``'s
twelve cache methods — but that is the override surface, a different graph, and
folding it in here would conflate the two.

HOW THE GRAPH IS BUILT
----------------------

For each unit (one mixin module, the ``read_group`` subpackage, or ``base.py``):

* **defines** — names bound in the body of a class that participates in the
  composition (``BaseModel`` itself, or a class inheriting ``_ModelStubs`` /
  ``*Mixin``). Restricting to those classes matters: ``traversal.py`` defines a
  local ``ReversibleComparator`` and ``cache.py`` a ``RecordCache``, both with
  ``__eq__`` / ``__getitem__`` / ``__len__``. Counting those would report
  phantom MRO collisions against ``IterationMixin``.
* **uses** — every ``self.X`` / ``cls.X`` read inside such a class.
* **recordset_uses** — ``uses`` plus every name reached through another
  recordset *of the same model*: ``records = self.browse(ids)`` followed by
  ``records._validate_fields(...)``. A mixin is a fragment of one class, so that
  is the same coupling as ``self._validate_fields(...)`` — but spelled in a way
  the ``self``-only collector cannot see. Measuring only ``self.`` reported the
  composition as a DAG while it was not one (see ``BASELINE``'s 2026-08c note).
* An edge ``A -> B`` exists when A uses a name that B defines. Both views are
  built, and both are ratcheted.

``_model_stubs`` is excluded: it is the typing-only *declaration* of the shared
surface, not an implementation, so counting it would collapse every edge onto it
and hide the real graph.

WHAT IS RATCHETED
-----------------

Six numbers, each a one-way contract against ``BASELINE``: the three below,
measured twice — once on the ``self``-only graph and once on the
recordset-aware one (``recordset_`` prefix). The second set is the one that
describes the composition; the first is kept because its movements are the
recorded history of this decomposition.

* ``max_scc`` — the largest strongly-connected component. Cycles are what make a
  decomposition cosmetic; this must never grow.
* ``cyclic_edges`` — edges whose endpoints share a cycle. The volume of
  tangling, as opposed to ``max_scc``'s worst single knot: breaking one back-edge
  of a 9-cycle leaves ``max_scc`` at 9 but shows up here immediately.
* ``scc_without_base`` — the largest SCC once ``base.py`` is removed. It used to
  be the interesting number: ``base.py`` was the *articulation point* of a
  nine-unit cycle, holding model metadata that every mixin read, and this
  metric reported the 2 that would remain if that were fixed. That split
  happened — the metadata lives on ``_metadata`` / ``_properties`` /
  ``_magic_fields`` leaves — and ``max_scc`` and this metric have converged, at
  **1**. It is kept as the regression guard for that split: if they diverge
  again, behaviour has moved back into the root.

  Two claims here had drifted from the graph they describe, in the checker whose
  job is to stop exactly that. They said the pair had converged at *2* (the
  value before ``_query.py`` broke ``read`` ⇄ ``search``; see ``BASELINE``'s
  2026-08b note) and that ``base.py`` was "now purely the composition root",
  which at the time it was not: it had out-edges to ``create``, ``_metadata``,
  ``traversal`` and ``_magic_fields``, and in-edges from ``lifecycle`` and
  ``unlink`` for the ``_onchange_methods`` / ``_ondelete_methods`` registries.
  A composition root two units depend on is a participant. It **is** one now --
  ``_HooksMixin``, ``_DisplayNameMixin`` and ``_FieldComputeMixin`` took the last
  six members off it, and ``base.py`` measures in-degree 0 and out-degree 0 in
  both views. So ``scc_without_base`` is now structurally pinned to ``max_scc``
  rather than merely equal to it, and its job has narrowed to catching the
  regression: if behaviour moves back into the root, the two diverge.

``units`` and ``edges`` are **reported but deliberately not ratcheted**. An
earlier version ratcheted the raw edge count as a god-object guard, and the very
first refactor done with this tool disproved it: extracting
``_read_group_empty_value`` onto a leaf deleted a 3-cycle outright, and the edge
count went *up* 85 -> 87, because a new unit brings its own edges. A metric that
fires on a decomposition it should reward is worse than no metric. Tangling is
what matters, so tangling is what is ratcheted.

Like ``layer_check``, the gate is drift-zero: any increase fails. A *decrease*
is reported and the baseline should be lowered in the same commit, so a cleanup
is locked in and cannot silently regress (the ``exact`` posture of
``tooling/ratchet/``).

USAGE
-----

  python tooling/architecture/mixin_coupling_check.py            # report
  python tooling/architecture/mixin_coupling_check.py --check    # CI: exit 1 on drift
  python tooling/architecture/mixin_coupling_check.py --json
  python tooling/architecture/mixin_coupling_check.py --explain read search
  python tooling/architecture/mixin_coupling_check.py --composition Field \\
      --explain _field_convert base.py

exit 0 — within baseline
exit 1 — coupling grew (or shrank without updating BASELINE)
exit 2 — usage error
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# Located by marker, not by counting parents — same reasoning as layer_check.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="mixin_coupling_check")
MODELS = ROOT / "odoo" / "orm" / "models"
MIXINS = MODELS / "mixins"

BASE_UNIT = "base.py"

#: Typing-only declaration of the shared surface, not an implementation.
EXCLUDED_UNITS = frozenset({"_model_stubs", "_crud_common", "__init__"})

#: Names that legitimately appear in more than one composed class, so a
#: duplicate is not MRO shadowing.
#:
#: ``__slots__`` — every mixin declares its own empty tuple; that is the point.
#: ``_register`` — ``MetaModel.__new__`` reads it out of the raw class-body
#:   ``attrs`` dict rather than off the class, so inheriting it does not work:
#:   any class using ``metaclass=MetaModel`` that must NOT self-register has to
#:   spell it out. ``BaseModel`` and ``_magic_fields`` both do, both as
#:   ``False``, so there is nothing for the MRO to decide between.
DUPLICATE_BY_DESIGN = frozenset({"__slots__", "_register"})

#: Committed floors. Lower these in the same commit as any cleanup.
#:
#: History, because both movements were corrections rather than drift:
#:  * first recorded as ``edges`` 75 / ``scc_without_base`` 2, against a version
#:    that collapsed the ``read_group`` subpackage into one unit. The runtime
#:    ``BaseModel.__mro__`` has four classes there; splitting them revealed 10
#:    edges and a whole 3-cycle the collapse had hidden -> 85 / 3.
#:  * ``edges`` then replaced by ``cyclic_edges`` (see the module docstring):
#:    extracting ``_read_group_empty_value`` deleted that 3-cycle and *raised*
#:    the raw edge count 85 -> 87, while tangling fell 35 -> 31.
#:  * 2026-08a: ``BaseModel`` split into composition root + ``_metadata`` /
#:    ``_properties`` / ``_magic_fields`` leaves. ``base.py`` was the
#:    articulation point of the nine-unit cycle (``base.py -> {create|env|
#:    traversal} -> iteration -> base.py``, that last edge being ``self.id``),
#:    so removing its participation took ``max_scc`` 9 -> 2 and
#:    ``cyclic_edges`` 31 -> 2, leaving only ``read <-> search``.
#:  * 2026-08b: that last cycle was broken by giving query construction its own
#:    leaf (``mixins/_query.py``), which removed the back-edge ``read ->
#:    search`` (``search -> read`` stays, and is acyclic). **The mixin graph is
#:    now a DAG**: ``cyclic_edges`` is 0, so the gate's meaning has hardened
#:    from "the tangle must not grow" to "there must be no tangle at all", and
#:    any new cycle at all fails CI.
#:
#:  * 2026-08c: the ``self``-only numbers above are true and unchanged, but they
#:    answer a narrower question than the docstring claimed. A mixin is a
#:    *fragment of one class*, so calling a sibling's method on another
#:    recordset of the same model -- ``records._validate_fields(...)`` where
#:    ``records = self.browse(ids)`` -- couples exactly as much as ``self.``
#:    would, and the collector could not see it. Following those locals
#:    (:data:`RECORDSET_PRODUCERS`) adds 8 edges and reveals **one 2-cycle**,
#:    ``base.py <-> create``: ``base.py:302`` calls ``self.create(...)`` in
#:    ``name_create`` while ``create.py:339,595`` call ``_validate_fields`` on
#:    recordsets ``self`` never names. So the composition was a DAG through
#:    ``self`` and *not* a DAG through the model -- which is the claim that
#:    matters. Both are now ratcheted; the ``recordset_*`` floors are the
#:    honest ones.
#:  * 2026-08d: that cycle was then broken the same way its predecessors were,
#:    by moving behaviour off the composition root: ``_constraint_methods`` and
#:    ``_validate_fields`` went to a ``_ConstraintsMixin`` leaf
#:    (``mixins/_constraints.py``). ``create`` and ``write`` now reach the
#:    constraint machinery without touching ``base.py``, and a leaf nothing
#:    depends *on* cannot close a cycle. ``recordset_cyclic_edges`` 2 -> 0 and
#:    ``recordset_max_scc`` 2 -> 1: **the composition is now a DAG in both
#:    views**, and both gates forbid a cycle rather than bounding one.
#:
#: Keep this list chronological: the two 2026-08 entries were written in the
#: opposite order, so the closing line read "only read <-> search remains" two
#: bullets after the one declaring the graph a DAG.
BASELINE = {
    "max_scc": 1,
    "cyclic_edges": 0,
    "scc_without_base": 1,
    # The same three measured on the recordset-aware graph.
    "recordset_max_scc": 1,
    "recordset_cyclic_edges": 0,
    "recordset_scc_without_base": 1,
}


#: Committed floors for the ``Field`` composition. Its own set, because the two
#: graphs answer the same question about different classes and must not mask
#: each other.
#:
#: These are NOT zero, and that is the honest state on the day the gate was
#: written: ``Field``'s composition has a 2-cycle, ``_field_convert`` <->
#: ``base``. ``base`` reaches conversion (``convert_to_cache`` /
#: ``convert_to_record`` / ``convert_to_write``, from the descriptor protocol)
#: and conversion reaches back for declared metadata (``column_type``,
#: ``company_dependent``, ``translate``, ``_is_context_dependent``,
#: ``_company_dependent_fallback_raw``).
#:
#: It is the same shape ``BaseModel`` had before 2026-08a, and the same fix
#: applies: the metadata belongs on a leaf, as ``_metadata`` / ``_properties`` /
#: ``_magic_fields`` are for models. That is a real refactor of ``Field``'s
#: ~40 declared attributes, so it is not bundled here -- the floor records the
#: tangle rather than pretending it away, and stops it growing meanwhile.
FIELD_BASELINE = {
    "max_scc": 2,
    "cyclic_edges": 2,
    "scc_without_base": 1,
}


@dataclass(frozen=True)
class Composition:
    """One ``__slots__``-mixin composition to measure.

    The gate was written for ``BaseModel`` and hard-coded to it. ``Field`` is
    built the same way -- a root class over ``*Mixin`` bases with a
    typing-only stub declaring the shared surface -- and was measured by
    nothing, while being 1401 lines against 628 in its three mixins (the
    inverse of the ratio ``models/`` reached). The first run found the cycle
    recorded in :data:`FIELD_BASELINE`.
    """

    label: str
    root_dir: Path
    root_file: str
    unit_dir: Path
    stub_base: str
    root_class: str
    excluded: frozenset[str]
    baseline: dict[str, int]
    #: Whether to also measure the recordset-mediated graph. Model-only: the
    #: producers in :data:`RECORDSET_PRODUCERS` are ``BaseModel`` methods, and a
    #: ``Field`` holds no recordset of itself, so for fields the wide view is
    #: the narrow one and ratcheting it twice would just double the noise.
    recordset_aware: bool


#: Methods on ``self`` that hand back another recordset **of the same model**.
#:
#: Calling a mixin's method on one of these is the same coupling as calling it
#: on ``self`` -- ``records._validate_fields(...)`` binds ``create`` to
#: ``base.py`` exactly as ``self._validate_fields(...)`` would -- but it is
#: invisible to a collector that only matches the literal name ``self``.
RECORDSET_PRODUCERS = frozenset(
    {
        "browse",
        "concat",
        "create",
        "exists",
        "filtered",
        "filtered_domain",
        "new",
        "search",
        "sorted",
        "sudo",
        "union",
        "with_company",
        "with_context",
        "with_env",
        "with_prefetch",
        "with_user",
        "_origin",
        "_spawn",
    }
)

#: Names that appear on ordinary containers/objects and would otherwise create
#: spurious edges when a local happens to be a list, dict or plain value rather
#: than the recordset we inferred.  Deliberately conservative: a false edge
#: makes the widened graph *look* more tangled than it is, which is the one
#: direction this analysis must not err in.
NON_RECORDSET_ATTRS = frozenset(
    {
        "append",
        "clear",
        "copy",
        "count",
        "extend",
        "get",
        "index",
        "insert",
        "items",
        "keys",
        "pop",
        "remove",
        "setdefault",
        "sort",
        "update",
        "values",
    }
)


MODEL_COMPOSITION = Composition(
    label="BaseModel",
    root_dir=MODELS,
    root_file=BASE_UNIT,
    unit_dir=MIXINS,
    stub_base="_ModelStubs",
    root_class="BaseModel",
    excluded=EXCLUDED_UNITS,
    baseline=BASELINE,
    recordset_aware=True,
)

FIELD_COMPOSITION = Composition(
    label="Field",
    root_dir=ROOT / "odoo" / "orm" / "fields",
    root_file=BASE_UNIT,
    # Flat, and deliberately not ``relational/``: those are Field *subclasses*
    # (``_Relational(Field[...])``, ``Many2many(_RelationalMulti)``), which is
    # the override surface, a different question from mixin composition. They
    # contribute no composed class and would be filtered anyway.
    unit_dir=ROOT / "odoo" / "orm" / "fields",
    stub_base="_FieldStubs",
    root_class="Field",
    excluded=frozenset({"_field_stubs", "__init__"}),
    baseline=FIELD_BASELINE,
    recordset_aware=False,
)

COMPOSITIONS = (MODEL_COMPOSITION, FIELD_COMPOSITION)


@dataclass
class Unit:
    """One participant in the composition: a mixin module or ``base.py``."""

    name: str
    files: list[str] = field(default_factory=list)
    defines: set[str] = field(default_factory=set)
    uses: set[str] = field(default_factory=set)
    #: ``uses`` plus names reached through another recordset of the same model.
    #: Kept separate so the original metric keeps its recorded history while
    #: the wider one records what the composition actually couples.
    recordset_uses: set[str] = field(default_factory=set)


def _is_composed_class(node: ast.ClassDef, comp: Composition) -> bool:
    """Whether *node* participates in *comp*'s composition.

    Local helper classes (``ReversibleComparator``, ``RecordCache``) must not
    count — see the module docstring. For ``Field`` the same filter excludes
    every concrete field type: ``BaseString(Field[...])`` has an
    ``ast.Subscript`` base and ``Many2many(_RelationalMulti)`` a name that is
    not a ``*Mixin``, so the graph stays the mixin composition rather than the
    subclass tree.
    """
    if node.name == comp.root_class:
        return True
    return any(
        isinstance(b, ast.Name) and (b.id == comp.stub_base or b.id.endswith("Mixin"))
        for b in node.bases
    )


def _bound_names(body: list[ast.stmt]):
    """Names bound directly in a class body, descending into ``if`` blocks.

    The ``if TYPE_CHECKING:`` descent is required: ``_ModelStubs`` and several
    mixins declare their surface there, and skipping it would drop real names.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield stmt.name
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    yield target.id
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            yield stmt.target.id
        elif isinstance(stmt, ast.If):
            yield from _bound_names(stmt.body)
            yield from _bound_names(stmt.orelse)


def _is_same_model_recordset(node: ast.expr) -> bool:
    """Does *node* evaluate to another recordset of the class being defined?

    Recognises the three shapes that produce one from ``self``: a call to a
    recordset-producing method (``self.browse(...)``, ``self.filtered(...)``),
    a slice (``self[:1]``), and ``self`` itself.
    """
    if isinstance(node, ast.Name) and node.id == "self":
        return True
    if isinstance(node, ast.Subscript):
        return _is_same_model_recordset(node.value)
    if isinstance(node, ast.Call):
        func = node.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr in RECORDSET_PRODUCERS
            and _is_same_model_recordset(func.value)
        )
    return False


class _SelfUseCollector(ast.NodeVisitor):
    """Collect ``defines`` / ``uses`` / ``recordset_uses`` for one file.

    ``uses`` is the original metric: attribute reads spelled ``self.X`` /
    ``cls.X``.  ``recordset_uses`` additionally follows locals bound to another
    recordset of the same model, because a mixin is a *fragment of one class*
    and calling into a sibling through ``records`` couples exactly as much as
    calling it through ``self`` -- the import graph and the ``self``-only graph
    both miss it.
    """

    def __init__(self, unit: Unit, comp: Composition | None = None) -> None:
        self.unit = unit
        # Defaulted for the self-test, which builds collectors directly.
        self.comp = comp if comp is not None else MODEL_COMPOSITION
        self._nesting = 0
        #: locals currently known to hold a recordset of this model
        self._recordset_locals: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        composed = _is_composed_class(node, self.comp)
        if composed:
            self.unit.defines.update(_bound_names(node.body))
            self._nesting += 1
        self.generic_visit(node)
        if composed:
            self._nesting -= 1

    def _track(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name) and _is_same_model_recordset(value):
            self._recordset_locals.add(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._track(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._track(node.target, node.value)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        # `for record in self:` / `for rec in records:` -- iterating a recordset
        # yields singletons of the same model.
        if isinstance(node.target, ast.Name) and (
            _is_same_model_recordset(node.iter)
            or (
                isinstance(node.iter, ast.Name)
                and node.iter.id in self._recordset_locals
            )
        ):
            self._recordset_locals.add(node.target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._nesting and isinstance(node.value, ast.Name):
            base = node.value.id
            if base in ("self", "cls"):
                self.unit.uses.add(node.attr)
                self.unit.recordset_uses.add(node.attr)
            elif (
                base in self._recordset_locals and node.attr not in NON_RECORDSET_ATTRS
            ):
                self.unit.recordset_uses.add(node.attr)
        self.generic_visit(node)


def _unit_name(path: Path, comp: Composition) -> str:
    """One unit per *composed class*, which means one per module.

    An earlier version collapsed the ``read_group`` subpackage into a single
    unit on the theory that a package is a unit. Checking the AST result against
    the runtime ``BaseModel.__mro__`` disproved it: ``mixin``, ``sql``,
    ``format`` and ``fill`` are four separate classes in the MRO
    (``ReadGroupMixin``, ``_ReadGroupSQLMixin``, ``_ReadGroupFormatMixin``,
    ``_ReadGroupFillMixin``), so collapsing them misattributed 14 names and hid
    every edge *between* them. A subpackage is a directory; the MRO is the
    architecture.
    """
    if path.name == comp.root_file and path.parent == comp.root_dir:
        return comp.root_file
    if path.parent != comp.unit_dir:
        return f"{path.parent.name}/{path.stem}"
    return path.stem


def collect_units(comp: Composition = None) -> dict[str, Unit]:
    """Parse *comp*'s package into units keyed by name."""
    comp = comp if comp is not None else MODEL_COMPOSITION
    units: dict[str, Unit] = {}
    paths = [p for p in comp.unit_dir.rglob("*.py") if "__pycache__" not in p.parts]
    root = comp.root_dir / comp.root_file
    if root not in paths:
        paths.append(root)
    for path in sorted(paths):
        name = _unit_name(path, comp)
        if name in comp.excluded:
            continue
        unit = units.setdefault(name, Unit(name))
        unit.files.append(path.name)
        _SelfUseCollector(unit, comp).visit(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
    # A module that contributes no composed class is not a participant --
    # ``_cache_scan.py`` is free functions, not a mixin. Keeping it would report
    # an isolated node and inflate the unit count without affecting any edge.
    return {n: u for n, u in units.items() if u.defines or u.uses}


def build_edges(
    units: dict[str, Unit], *, through_recordsets: bool = False
) -> tuple[dict[str, dict[str, set[str]]], dict]:
    """Return ``(edges, collisions)``.

    ``edges[a][b]`` is the set of B-owned names that A reaches through ``self``.
    With *through_recordsets*, names reached through another recordset of the
    same model count too — see :data:`RECORDSET_PRODUCERS`.

    ``collisions`` maps a name defined by more than one unit to those units — a
    real MRO shadowing risk, since which definition wins depends only on the
    order of the bases in ``class BaseModel(...)``.
    """
    owner: dict[str, str] = {}
    collisions: dict[str, set[str]] = defaultdict(set)
    for name in sorted(units):
        for member in sorted(units[name].defines):
            if member in owner and member not in DUPLICATE_BY_DESIGN:
                collisions[member].update({owner[member], name})
            else:
                owner.setdefault(member, name)

    edges: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for name, unit in units.items():
        members = unit.recordset_uses if through_recordsets else unit.uses
        for member in members:
            target = owner.get(member)
            if target is not None and target != name:
                edges[name][target].add(member)
    return edges, dict(collisions)


def strongly_connected(
    nodes: set[str], edges: dict[str, dict[str, set[str]]]
) -> list[list[str]]:
    """Tarjan's SCC, iterative so a deep graph cannot blow the stack."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in sorted(nodes):
        if root in index:
            continue
        work: list[tuple[str, list[str]]] = [(root, sorted(edges.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, pending = work[-1]
            progressed = False
            while pending:
                nxt = pending.pop(0)
                if nxt not in nodes:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, sorted(edges.get(nxt, ()))))
                    progressed = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if progressed:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    top = stack.pop()
                    on_stack.discard(top)
                    component.append(top)
                    if top == node:
                        break
                result.append(sorted(component))
    return result


def measure(
    *, through_recordsets: bool = False, comp: Composition | None = None
) -> dict:
    comp = comp if comp is not None else MODEL_COMPOSITION
    units = collect_units(comp)
    edges, collisions = build_edges(units, through_recordsets=through_recordsets)
    names = set(units)

    sccs = [c for c in strongly_connected(names, edges) if len(c) > 1]
    without_base = [
        c for c in strongly_connected(names - {comp.root_file}, edges) if len(c) > 1
    ]

    # Edges whose endpoints share a cycle. This -- not the raw edge count -- is
    # the tangling measure, because only these edges are the ones that cannot be
    # read in dependency order.
    component_of: dict[str, int] = {}
    for i, component in enumerate(sccs):
        for unit in component:
            component_of[unit] = i
    cyclic = sum(
        1
        for src, targets in edges.items()
        for dst in targets
        if component_of.get(src, -1) == component_of.get(dst, -2)
    )

    return {
        "units": sorted(names),
        "edges_total": sum(len(t) for t in edges.values()),
        "cyclic_edges": cyclic,
        "max_scc": max((len(c) for c in sccs), default=1),
        "sccs": sorted(sccs, key=len, reverse=True),
        "scc_without_base": max((len(c) for c in without_base), default=1),
        "sccs_without_base": sorted(without_base, key=len, reverse=True),
        "collisions": {k: sorted(v) for k, v in collisions.items()},
        "_edges": edges,
        "_units": units,
    }


def _verdicts(
    m: dict, wide: dict | None = None, baseline: dict | None = None
) -> list[tuple[str, int, int, str]]:
    """Return ``(metric, actual, floor, status)`` for each ratcheted number.

    *wide* is the same measurement taken through recordsets; its three numbers
    are ratcheted alongside the ``self``-only ones so neither view can drift.
    """
    pairs = [
        ("max_scc", m["max_scc"]),
        ("cyclic_edges", m["cyclic_edges"]),
        ("scc_without_base", m["scc_without_base"]),
    ]
    if wide is not None:
        pairs += [
            ("recordset_max_scc", wide["max_scc"]),
            ("recordset_cyclic_edges", wide["cyclic_edges"]),
            ("recordset_scc_without_base", wide["scc_without_base"]),
        ]
    floors = baseline if baseline is not None else BASELINE
    out = []
    for key, actual in pairs:
        floor = floors[key]
        if actual > floor:
            status = "GREW"
        elif actual < floor:
            status = "IMPROVED"
        else:
            status = "ok"
        out.append((key, actual, floor, status))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any drift"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--explain",
        nargs=2,
        metavar=("FROM", "TO"),
        help="list the members that create one edge",
    )
    parser.add_argument(
        "--composition",
        choices=[c.label for c in COMPOSITIONS],
        default=MODEL_COMPOSITION.label,
        help="which composition --explain refers to (default: BaseModel)",
    )
    args = parser.parse_args(argv)

    chosen = next(c for c in COMPOSITIONS if c.label == args.composition)
    m = measure(comp=chosen)

    if args.explain:
        src, dst = args.explain
        direct = m["_edges"].get(src, {}).get(dst) or set()
        # Also consult the recordset-aware graph: the report names cycles from
        # it (base.py <-> create), and an --explain that could not describe
        # them would send the reader looking for a `self.` spelling that is not
        # there.
        wide_edges = (
            measure(through_recordsets=True, comp=chosen)["_edges"]
            if chosen.recordset_aware
            else m["_edges"]
        )
        wide = wide_edges.get(src, {}).get(dst) or set()
        if not direct and not wide:
            print(f"no edge {src} -> {dst}", file=sys.stderr)
            return 2
        if direct:
            print(f"{src} -> {dst} via {len(direct)} member(s) on self:")
            for member in sorted(direct):
                print(f"  {member}")
        if indirect := wide - direct:
            print(
                f"{src} -> {dst} via {len(indirect)} member(s) reached through "
                f"another recordset of the same model:"
            )
            for member in sorted(indirect):
                print(f"  {member}")
        return 0

    reports = []
    for comp in COMPOSITIONS:
        cm = m if comp is chosen else measure(comp=comp)
        cwide = (
            measure(through_recordsets=True, comp=comp)
            if comp.recordset_aware
            else None
        )
        reports.append((comp, cm, cwide, _verdicts(cm, cwide, comp.baseline)))

    if args.json:
        print(
            json.dumps(
                {
                    comp.label: {
                        "metrics": {k: a for k, a, _, _ in vs},
                        "baseline": comp.baseline,
                        "status": {k: st for k, _, _, st in vs},
                        "sccs": cm["sccs"],
                        "recordset_sccs": cwide["sccs"] if cwide else None,
                        "collisions": cm["collisions"],
                    }
                    for comp, cm, cwide, vs in reports
                },
                indent=2,
            )
        )
    else:
        for comp, cm, cwide, vs in reports:
            print(f"{comp.label} mixin coupling check")
            print("=" * 64)
            for key, actual, floor, status in vs:
                flag = "ok" if status == "ok" else status
                print(f"[{flag:>8}] {key}: {actual} (baseline {floor})")
            print("-" * 64)
            print(f"units: {len(cm['units'])}   inter-unit edges: {cm['edges_total']}")
            for component in cm["sccs"]:
                print(f"  cycle of {len(component)}: {', '.join(component)}")
            if cwide is not None:
                print(
                    f"through recordsets: {cwide['edges_total']} edges, "
                    f"{cwide['cyclic_edges']} cyclic"
                )
                for component in cwide["sccs"]:
                    print(
                        f"  cycle of {len(component)} via recordsets: "
                        f"{', '.join(component)}"
                    )
            if cm["scc_without_base"] < cm["max_scc"]:
                print(
                    f"  without {comp.root_file}: largest cycle is "
                    f"{cm['scc_without_base']} — the rest of the cycle is "
                    f"{comp.root_file} being both composition root and "
                    f"metadata holder"
                )
            for component in cm["sccs_without_base"]:
                print(f"    residual cycle: {', '.join(component)}")
            if cm["collisions"]:
                print("\nname defined by more than one unit (MRO order decides):")
                for name, owners in sorted(cm["collisions"].items()):
                    print(f"  {name}: {', '.join(owners)}")
            else:
                print("\nNo cross-unit name collisions. ✓")
            print()

    verdicts = [(comp.label, *v) for comp, _, _, vs in reports for v in vs]

    grew = [v for v in verdicts if v[4] == "GREW"]
    improved = [v for v in verdicts if v[4] == "IMPROVED"]

    if args.check:
        if grew:
            print("\nFAILED: mixin coupling grew:", file=sys.stderr)
            for label, key, actual, floor, _ in grew:
                print(f"  {label}.{key}: {floor} -> {actual}", file=sys.stderr)
            return 1
        if improved:
            print(
                "\nFAILED: coupling improved but the baseline was not lowered "
                "(exact-mode ratchet — commit the new floor):",
                file=sys.stderr,
            )
            for label, key, actual, floor, _ in improved:
                print(f"  {label}.{key}: {floor} -> {actual}", file=sys.stderr)
            return 1
        print("Mixin coupling within baseline, both compositions. ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
