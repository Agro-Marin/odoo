"""Discover in-memory search dependencies without invoking SQL callbacks."""

from collections import defaultdict

from ..domain.ast import Domain, DomainCondition, DomainCustom, DomainNary, DomainNot
from ..parsing import parse_field_expr, regex_order


def flush_search_dependencies(model, domain, order):
    """Flush searchable fields while leaving unrelated computes deferred.

    Python custom predicates are opaque: retain the historical full flush for
    those domains. Their SQL implementation belongs to the PostgreSQL adapter.
    """
    fields_by_model = defaultdict(set)
    seen = set()
    opaque = False

    def collect_field(records, expression):
        name, prop = parse_field_expr(expression)
        field = records._fields[name]
        key = (records._name, expression)
        if key in seen:
            return field
        seen.add(key)
        if field.store:
            fields_by_model[records._name].add(name)
        elif field.related:
            target = records
            for part in field.related.split("."):
                related = collect_field(target, part)
                if related.relational:
                    target = records.env[related.comodel_name]
        if field.is_one2many:
            collect_field(records.env[field.comodel_name], field.inverse_name)
        if prop and field.relational:
            collect_field(records.env[field.comodel_name], prop)
        return field

    def collect_domain(records, node):
        nonlocal opaque
        if isinstance(node, DomainCustom):
            if node._filtered is None:
                raise NotImplementedError(
                    "In-memory searches require a Python predicate for custom domains"
                )
            opaque = True
        elif isinstance(node, DomainNary):
            for child in node.children:
                collect_domain(records, child)
        elif isinstance(node, DomainNot):
            collect_domain(records, node.child)
        elif isinstance(node, DomainCondition):
            field = collect_field(records, node.field_expr)
            if isinstance(node.value, Domain):
                target = (
                    records.env[field.comodel_name] if field.relational else records
                )
                collect_domain(target, node.value)

    def collect_order(records, specification, ordered_fields=frozenset()):
        records._check_qorder(specification)
        for part in specification.split(","):
            match = regex_order.match(part)
            field = collect_field(records, match["field"])
            if (
                field.is_many2one
                and not match["property"]
                and field not in ordered_fields
            ):
                target = records.env[field.comodel_name]
                if target._order:
                    collect_order(target, target._order, ordered_fields | {field})

    collect_domain(model, domain)
    if order:
        collect_order(model, order)
    if opaque:
        model.env.flush_all()
    else:
        for name, fields in fields_by_model.items():
            model.env[name].flush_model(fields)
