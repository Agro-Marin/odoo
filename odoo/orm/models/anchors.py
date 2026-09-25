from __future__ import annotations

import typing
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    from collections.abc import Mapping

    from .base import BaseModel

# what each kind of anchor points at: the rung that reads it compares the
# anchor with the principal's own records of that model
ANCHOR_KINDS: Mapping[str, str] = {
    "company": "res.company",
    "owner": "res.users",
    "creator": "res.users",
    "employee": "hr.employee",
    "team": "team.team",
    "unit": "hr.department",
    "partner": "res.partner",
}
HIERARCHIES = frozenset({"parent_of", "child_of"})


@dataclass(frozen=True, slots=True)
class Anchor:
    """Where a model's records meet a principal, for the reach an access row names.

    `path` leads from the record to a record of the kind's model (a user, a
    company, a team...); `kind` is the key's own name unless the key is a
    second anchor of a known kind (`"approver": Anchor("approver_ids.user_id",
    kind="owner")`). `shared` lets the rung admit the records where the anchor
    is unset; `hierarchy` reads a company anchor up (`parent_of`) or down
    (`child_of`) the company tree; `usage` limits a team anchor to the teams
    of one usage (`sale`, `purchase`...).
    """

    path: str
    kind: str | None = None
    shared: bool = False
    hierarchy: str | None = None
    usage: str | None = None


def collect_anchors(model_cls: type[BaseModel]) -> dict[str, Anchor]:
    declared: dict[str, str | Anchor] = {}
    for cls in reversed(model_cls.mro()):
        declared.update(vars(cls).get("_access_anchors") or {})
    anchors: dict[str, Anchor] = {}
    for key, value in declared.items():
        anchor = Anchor(value) if isinstance(value, str) else value
        kind = anchor.kind or key
        if kind not in ANCHOR_KINDS:
            raise TypeError(
                f"{model_cls._name}: anchor {key!r} has no kind; name one of "
                f"{sorted(ANCHOR_KINDS)} with kind=..."
            )
        if anchor.hierarchy is not None and (
            anchor.hierarchy not in HIERARCHIES or kind != "company"
        ):
            raise TypeError(
                f"{model_cls._name}: anchor {key!r} reads a hierarchy "
                f"{anchor.hierarchy!r}; only a company anchor reads parent_of or "
                f"child_of"
            )
        if anchor.usage is not None and kind != "team":
            raise TypeError(
                f"{model_cls._name}: anchor {key!r} names a usage; only a team "
                f"anchor has one"
            )
        if anchor.path:
            anchors[key] = Anchor(
                anchor.path, kind, anchor.shared, anchor.hierarchy, anchor.usage
            )
    creator = model_cls._fields.get("create_uid")
    if (
        "creator" not in declared
        and creator is not None
        and creator.comodel_name == "res.users"
    ):
        anchors["creator"] = Anchor("create_uid", "creator")
    if "company" not in declared:
        if model_cls._name == "res.company":
            anchors["company"] = Anchor("id", "company")
        else:
            for name in ("company_id", "company_ids"):
                field = model_cls._fields.get(name)
                if (
                    field is not None
                    and field.comodel_name == "res.company"
                    and (field.store or field.related or field.search)
                ):
                    anchors["company"] = Anchor(name, "company")
                    break
    return anchors


def anchor_path_error(
    model_cls: type[BaseModel], key: str, anchor: Anchor, models: Mapping[str, type]
) -> str | None:
    # every hop exists and can be searched, and the last one reaches the model
    # the anchor's kind names
    target = ANCHOR_KINDS[anchor.kind or key]
    if anchor.path == "id":
        if model_cls._name != target:
            return f"its path 'id' is a {model_cls._name}, not a {target}"
        return None
    current: type = model_cls
    for name in anchor.path.split("."):
        field = current._fields.get(name)  # type: ignore[attr-defined]
        if field is None:
            return f"{current._name}.{name} does not exist"  # type: ignore[attr-defined]
        if not (field.store or field.related or field.search):
            return f"{field} is neither stored nor searchable"
        if not field.relational:
            return f"{field} is not relational"
        if field.comodel_name not in models:
            return f"{field} leads to {field.comodel_name}, which is not loaded"
        current = models[field.comodel_name]
    reached = current._name  # type: ignore[attr-defined]
    if reached != target:
        return f"its path leads to {reached}, not to {target}"
    return None
