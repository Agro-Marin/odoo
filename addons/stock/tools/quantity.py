from __future__ import annotations

import logging
from collections.abc import Collection
from typing import NamedTuple

from odoo.fields import Domain

_logger = logging.getLogger(__name__)


def filter_quantity_in_python(records, field_name, operator, value):
    matches = records.with_context(prefetch_fields=False).search_fetch(
        [], [field_name], order="id"
    )
    positive_operator = Domain.NEGATIVE_OPERATORS.get(operator, operator)
    predicate = records._fields[field_name].filter_function(
        matches, field_name, positive_operator, value
    )
    if positive_operator != operator:
        matched = matches.filtered(lambda record: not predicate(record))
    else:
        matched = matches.filtered(predicate)
    return [("id", "in", matched.ids)]


def resolve_context_record_ids(env, model, values) -> set[int]:
    Model = env[model]
    given_ids = set()
    domains = []
    for item in values:
        if isinstance(item, bool):
            raise ValueError(
                f"Invalid {model!r} value {item!r} in the context: "
                f"expected a database id or a name to search for.",
            )
        if isinstance(item, int):
            given_ids.add(item)
        else:
            domains.append(Domain(Model._rec_name, "ilike", item))
    existing = set(Model.browse(given_ids).exists().ids) if given_ids else set()
    if missing := given_ids - existing:
        _logger.warning(
            "Ignoring %s id(s) %s from the context: no such record.",
            model,
            sorted(missing),
        )
    if domains:
        existing |= set(Model.search(Domain.OR(domains)).ids)
    return existing


class QuantityFilters(NamedTuple):
    lot_id: int | bool | None = None
    owner_id: int | bool | None = None
    package_id: int | bool | None = None
    owners: Collection | bool | None = None
    from_date: object = False
    to_date: object = False

    @classmethod
    def from_context(cls, env) -> QuantityFilters:
        context = env.context
        return cls(
            lot_id=context.get("lot_id"),
            owner_id=context.get("owner_id"),
            package_id=context.get("package_id"),
            owners=context.get("owners"),
            from_date=context.get("from_date", False),
            to_date=context.get("to_date", False),
        )
