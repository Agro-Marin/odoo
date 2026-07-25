"""Find computed fields whose ``@api.depends`` is missing a field they read.

A computed field is recomputed only when something in its declared dependency
set changes. Declare nothing and a **non-stored** computed field is computed
once per transaction cache and then never invalidated: it silently serves a
stale value forever. Nothing raises, no query misbehaves, and no existing check
fires -- the ORM warns about a precompute on a non-computed field, an
unsearchable dependency, a missing ``recursive=True`` and a dependency on
``id``, but never about an *empty* dependency set. It is the one misdeclaration
in the family that fails silently.

This module finds them by reading the compute method's **code object**: every
attribute name it accesses that happens to be a field of the same model, minus
the fields it declares, minus the fields it computes (those are assignments).
Deliberately static:

* **Zero production cost.** Nothing here is imported by the ORM and no hook is
  installed. The alternative -- recording reads through ``Field.__get__`` --
  would be precise, but ``__get__`` is the hottest path in the framework and
  even a single flag check there is a tax paid by every attribute access in
  every request, forever, to serve a check that runs in CI.
* **Directionally safe.** Reading the bytecode cannot prove a read happens
  (a branch may never execute), so a finding is a *candidate*, not a verdict.
  What it does give is the useful direction: a compute that never mentions a
  sibling field cannot depend on one, so a clean result is trustworthy.

Known limits, both of which show up as *false positives* (never as a missed
bug), and both of which the caller resolves with an explicit exemption:

* an attribute name that is a field name but is read from something that is not
  a record (``get_lang(env).code`` looks like a read of a field named ``code``);
  accesses through ``env`` are filtered out, other receivers are not;
* a dependency that cannot be written as a static path at all -- an aggregate
  over another model's rows (``ir.model.count``), the live HTTP request, the
  clock, a PostgreSQL sequence.

``dynamic`` reads (``getattr(record, name)``) are invisible here; that is a
false negative, and the reason this is a lint rather than a proof.

Usage::

    from odoo.tools.depends_audit import audit_registry

    for finding in audit_registry(env.registry):
        print(finding.label, finding.reads)
"""

from __future__ import annotations

import dis
import typing
from dataclasses import dataclass
from dataclasses import field as dataclass_field

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_ATTR_ACCESS = frozenset({"LOAD_ATTR", "LOAD_METHOD", "STORE_ATTR"})

_RECEIVER_LOAD = frozenset(
    {
        "LOAD_ATTR",
        "LOAD_METHOD",
        "LOAD_FAST",
        "LOAD_FAST_BORROW",
        "LOAD_GLOBAL",
        "LOAD_DEREF",
        "LOAD_NAME",
    }
)

_NEVER_A_DEPENDENCY = frozenset({"id"})


@dataclass(frozen=True)
class DependsFinding:
    """One computed field that reads model fields it does not depend on."""

    model_name: str
    field_name: str
    reads: tuple[str, ...]
    stored: bool
    declared: tuple[str, ...] = dataclass_field(default=())

    @property
    def label(self) -> str:
        """``model.field``, the form used by exemption keys and reports."""
        return f"{self.model_name}.{self.field_name}"

    def __str__(self) -> str:
        return (
            f"{self.label} computes without depending on "
            f"{', '.join(self.reads)}"
            f"{' (stored)' if self.stored else ''}"
        )


def accessed_attribute_names(func: Callable) -> set[str]:
    """Return the attribute names *func* (and its nested code objects) accesses.

    Accesses whose receiver was just loaded from ``env`` are dropped: they are
    Environment members (``env.ref``, ``env.company``, ``env.user``...), not
    field reads, and they collide with common field names.
    """
    names: set[str] = set()
    code = getattr(func, "__code__", None)
    if code is None:
        return names
    todo = [code]
    while todo:
        current = todo.pop()
        instructions = list(dis.get_instructions(current))
        for index, instruction in enumerate(instructions):
            if instruction.opname not in _ATTR_ACCESS:
                continue
            previous = instructions[index - 1] if index else None
            if (
                previous is not None
                and previous.opname in _RECEIVER_LOAD
                and previous.argval == "env"
            ):
                continue
            if isinstance(instruction.argval, str):
                names.add(instruction.argval)
        todo.extend(c for c in current.co_consts if hasattr(c, "co_names"))
    return names


def _compute_functions(field: typing.Any, model_class: typing.Any) -> list[Callable]:
    """Return the callables implementing *field*'s compute, in override order."""
    compute = field.compute
    if not compute:
        return []
    if not isinstance(compute, str):
        return [compute]
    from odoo.orm.fields.base import resolve_mro

    return resolve_mro(model_class, compute, callable)


def audit_field(
    registry: typing.Any, model_class: typing.Any, field: typing.Any
) -> DependsFinding | None:
    """Audit one computed field; return a finding, or ``None`` when clean."""
    functions = _compute_functions(field, model_class)
    if not functions:
        return None

    accessed: set[str] = set()
    for function in functions:
        accessed |= accessed_attribute_names(function)

    declared = {path.split(".")[0] for path in registry.field_depends.get(field, ())}
    computed_together = {
        other.name for other in registry.field_computed.get(field, [field])
    }

    reads = (
        (accessed & set(model_class._fields))
        - declared
        - computed_together
        - _NEVER_A_DEPENDENCY
    )
    if not reads:
        return None
    return DependsFinding(
        model_name=field.model_name,
        field_name=field.name,
        reads=tuple(sorted(reads)),
        stored=bool(field.store),
        declared=tuple(sorted(declared)),
    )


def audit_registry(
    registry: typing.Any,
    *,
    only_without_dependencies: bool = True,
    include_stored: bool = False,
) -> Iterator[DependsFinding]:
    """Yield a :class:`DependsFinding` per suspect computed field in *registry*.

    :param only_without_dependencies: restrict to fields declaring NO
        dependencies at all (neither ``@api.depends`` nor ``depends_context``).
        This is the silent-staleness population and the only one worth gating
        on: a field that declares *some* dependencies has been thought about,
        and an incomplete set produces far more false positives (a compute
        legitimately reads fields it need not be recomputed for).
    :param include_stored: also audit stored computed fields. Off by default:
        a stored computed field with no dependencies is still computed on
        create, so it is wrong-but-not-invisible, and several are intentional.
    """
    registry._field_triggers
    for model_class in registry.models.values():
        if model_class._abstract:
            continue
        for field in model_class._fields.values():
            if not field.compute:
                continue
            if field.store and not include_stored:
                continue
            if only_without_dependencies and (
                registry.field_depends.get(field)
                or registry.field_depends_context.get(field)
            ):
                continue
            finding = audit_field(registry, model_class, field)
            if finding is not None:
                yield finding
