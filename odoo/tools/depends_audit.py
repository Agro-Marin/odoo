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


def accessed_attribute_names(func: Callable) -> set[str]:
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
