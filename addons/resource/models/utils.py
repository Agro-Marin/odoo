from collections.abc import Callable

from odoo.fields import Domain

HOURS_PER_DAY = 8


def filter_domain_leaf(
    domain: Domain | list,
    field_check: Callable[[str], bool],
    field_name_mapping: dict[str, str] | None = None,
) -> Domain:
    field_name_mapping = field_name_mapping or {}

    def adapt_condition(condition, ignored):
        field_name = condition.field_expr
        if not field_check(field_name):
            return ignored
        field_name = field_name_mapping.get(field_name)
        if field_name is None:
            return condition
        return Domain(field_name, condition.operator, condition.value)

    def adapt_domain(domain: Domain, ignored) -> Domain:
        if hasattr(domain, "OPERATOR"):
            if domain.OPERATOR in ("&", "|"):
                domain = domain.apply(
                    adapt_domain(d, domain.ZERO) for d in domain.children
                )
            elif domain.OPERATOR == "!":
                domain = ~adapt_domain(~domain, ~ignored)
            else:
                msg = f"domain.OPERATOR = {domain.OPERATOR!r} unhandled"
                raise AssertionError(msg)
        else:
            domain = domain.map_conditions(
                lambda condition: adapt_condition(condition, ignored)
            )
        return ignored if domain.is_true() or domain.is_false() else domain

    domain = Domain(domain)
    if domain.is_false():
        return domain
    return adapt_domain(domain, ignored=Domain.TRUE)
