from __future__ import annotations

import dis
import typing
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from opcode import opmap

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _opnames(*names: str) -> frozenset[str]:
    """Refuse an opcode this interpreter does not have.

    A name that no longer exists narrows the analysis silently -- `LOAD_METHOD`
    sat in both sets below and was folded into `LOAD_ATTR` in Python 3.12, so
    for three releases these sets have been describing an interpreter we do not
    run.  safe_eval.to_required_opcodes refuses the same way, for the same
    reason.
    """
    if missing := sorted(n for n in names if n not in opmap):
        raise RuntimeError(
            f"depends_audit names opcode(s) {', '.join(missing)}, which do not "
            f"exist on this interpreter. Re-derive the sets against it: "
            f"silently dropping one narrows the analysis."
        )
    return frozenset(names)


_ATTR_ACCESS = _opnames("LOAD_ATTR", "STORE_ATTR")

# Loads that can put the receiver of an attribute access on the stack.  The
# fused forms matter: 3.13+ emits LOAD_FAST_LOAD_FAST and friends, whose argval
# is a *tuple* of two names, so the `env` guard below has to read the last of
# them rather than compare the whole argval.
_RECEIVER_LOAD = _opnames(
    "LOAD_ATTR",
    "LOAD_FAST",
    "LOAD_FAST_BORROW",
    "LOAD_FAST_CHECK",
    "LOAD_FAST_LOAD_FAST",
    "LOAD_FAST_BORROW_LOAD_FAST_BORROW",
    "LOAD_GLOBAL",
    "LOAD_DEREF",
    "LOAD_NAME",
)

# Attributes whose own attributes belong to another record, not to `self`.
# `self.env.user.name` reads `name` off res.users; reporting it as a missing
# dependency of the compute's own model is a false positive.
_FOREIGN_ROOTS = frozenset({"env"})

_NEVER_A_DEPENDENCY = frozenset({"id"})


@dataclass(frozen=True)
class DependsFinding:
    model_name: str
    field_name: str
    reads: tuple[str, ...]
    stored: bool
    declared: tuple[str, ...] = dataclass_field(default=())

    @property
    def label(self) -> str:
        return f"{self.model_name}.{self.field_name}"

    def __str__(self) -> str:
        return (
            f"{self.label} computes without depending on "
            f"{', '.join(self.reads)}"
            f"{' (stored)' if self.stored else ''}"
        )


def _loaded_name(instruction: dis.Instruction) -> str | None:
    """The name a receiver-load pushes, or None.

    A fused load (LOAD_FAST_LOAD_FAST and its borrowing variants) carries a
    tuple of two names and leaves the *second* on top of the stack.
    """
    argval = instruction.argval
    if isinstance(argval, tuple):
        return argval[-1] if argval else None
    return argval if isinstance(argval, str) else None


def accessed_attribute_names(func: Callable) -> set[str]:
    """Attribute names this function reads off `self`.

    Anything reached through `self.env` belongs to another record and is
    excluded -- and so is the rest of that chain: for `self.env.user.name` the
    guard has to survive past `user` to drop `name` too, which a one-instruction
    lookback did not do.
    """
    names: set[str] = set()
    code = getattr(func, "__code__", None)
    if code is None:
        return names
    todo = [code]
    while todo:
        current = todo.pop()
        instructions = list(dis.get_instructions(current))
        # Index of every instruction whose result is a value on some foreign
        # record, so an attribute read off it is not a dependency of ours.
        foreign: set[int] = set()
        for index, instruction in enumerate(instructions):
            if instruction.opname not in _ATTR_ACCESS:
                continue
            previous = instructions[index - 1] if index else None
            if previous is None:
                if isinstance(instruction.argval, str):
                    names.add(instruction.argval)
                continue
            previous_name = _loaded_name(previous)
            if previous.opname in _RECEIVER_LOAD and previous_name in _FOREIGN_ROOTS:
                # self.env.<x> -- and everything further along the chain
                foreign.add(index)
                continue
            if index - 1 in foreign:
                foreign.add(index)
                continue
            if instruction.argval in _FOREIGN_ROOTS:
                # `self.env` itself: a doorway to other records, never a field.
                foreign.add(index)
                continue
            if isinstance(instruction.argval, str):
                names.add(instruction.argval)
        todo.extend(c for c in current.co_consts if hasattr(c, "co_names"))
    return names


def _compute_functions(field: typing.Any, model_class: typing.Any) -> list[Callable]:
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
    registry._ensure_field_triggers()
    for model_class in registry.models.values():
        if model_class._abstract:
            continue
        for field in model_class._fields.values():
            if not field.compute:
                continue
            if field.related or field.is_properties:
                # Their `compute` is the framework's own -- `Field._compute_related`
                # and the properties equivalent -- so scanning its bytecode
                # attributes the ORM's attribute reads to the model. 92 of the
                # 133 findings at the widest scope were exactly that, which is
                # what made the widest scope unusable.
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
