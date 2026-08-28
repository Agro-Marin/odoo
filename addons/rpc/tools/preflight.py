import difflib
from typing import Any, NamedTuple

from odoo.exceptions import UserError
from odoo.fields import Domain

FIELDS = "fields"
FIELD = "field"
PATHS = "paths"
SPEC = "spec"
DOMAIN = "domain"
ORDER = "order"
GROUP = "group"
HAVING = "having"
VALS = "vals"


class Argument(NamedTuple):
    kind: str
    index: int | None
    name: str
    key: str | None = None


CALL_SHAPES: dict[str, tuple[Argument, ...]] = {
    "read": (Argument(FIELDS, 1, "fields"),),
    "search": (Argument(DOMAIN, 0, "domain"), Argument(ORDER, 3, "order")),
    "search_count": (Argument(DOMAIN, 0, "domain"),),
    "search_read": (
        Argument(DOMAIN, 0, "domain"),
        Argument(FIELDS, 1, "fields"),
        Argument(ORDER, 4, "order"),
    ),
    "name_search": (Argument(DOMAIN, 1, "domain"),),
    "default_get": (Argument(FIELDS, 0, "fields"),),
    "load": (Argument(PATHS, 0, "fields"),),
    "export_data": (Argument(PATHS, 1, "fields_to_export"),),
    "get_field_translations": (Argument(FIELD, 1, "field_name"),),
    "update_field_translations": (Argument(FIELD, 1, "field_name"),),
    "search_panel_select_range": (Argument(FIELD, 0, "field_name"),),
    "search_panel_select_multi_range": (Argument(FIELD, 0, "field_name"),),
    "web_resequence": (
        Argument(SPEC, 1, "specification"),
        Argument(FIELD, 2, "field_name"),
    ),
    "create": (Argument(VALS, 0, "vals_list"),),
    "write": (Argument(VALS, 1, "vals"),),
    "copy": (Argument(VALS, 1, "default"),),
    "copy_data": (Argument(VALS, 1, "default"),),
    "onchange": (
        Argument(VALS, 1, "values"),
        Argument(FIELDS, 2, "field_names"),
        Argument(SPEC, 3, "fields_spec"),
    ),
    "read_group": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "fields"),
        Argument(GROUP, 2, "groupby"),
        Argument(ORDER, 5, "orderby"),
    ),
    "formatted_read_group": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "groupby"),
        Argument(GROUP, 2, "aggregates"),
        Argument(HAVING, 3, "having"),
        Argument(ORDER, 6, "order"),
    ),
    "formatted_read_grouping_sets": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "grouping_sets"),
        Argument(GROUP, 2, "aggregates"),
        Argument(ORDER, None, "order"),
    ),
    "read_progress_bar": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "group_by"),
        Argument(FIELD, 2, "progress_bar", "field"),
    ),
    "web_read": (Argument(SPEC, 1, "specification"),),
    "web_search_read": (
        Argument(DOMAIN, 0, "domain"),
        Argument(SPEC, 1, "specification"),
        Argument(ORDER, 4, "order"),
    ),
    "web_name_search": (
        Argument(SPEC, 1, "specification"),
        Argument(DOMAIN, 2, "domain"),
    ),
    "web_read_group": (
        Argument(DOMAIN, 0, "domain"),
        Argument(GROUP, 1, "groupby"),
        Argument(GROUP, 2, "aggregates"),
        Argument(ORDER, 5, "order"),
        Argument(SPEC, None, "unfold_read_specification"),
        Argument(SPEC, None, "groupby_read_specification"),
    ),
    "web_save": (
        Argument(VALS, 1, "vals"),
        Argument(SPEC, 2, "specification"),
    ),
    "web_save_multi": (
        Argument(VALS, 1, "vals_list"),
        Argument(SPEC, 2, "specification"),
    ),
}


def call_args(params: list) -> tuple[list, dict]:
    args = params[5] if len(params) > 5 and isinstance(params[5], list) else []
    kwargs = params[6] if len(params) > 6 and isinstance(params[6], dict) else {}
    return args, kwargs


def arguments(model_method: str, kind: str, args, kwargs) -> list:
    found = []
    for argument in CALL_SHAPES.get(model_method, ()):
        if argument.kind != kind:
            continue
        value = kwargs.get(argument.name)
        if value is None and argument.index is not None and len(args) > argument.index:
            value = args[argument.index]
        if argument.key is not None:
            value = value.get(argument.key) if isinstance(value, dict) else None
        if value is not None:
            found.append(value)
    return found


def _first(model_method: str, kind: str, args, kwargs):
    values = arguments(model_method, kind, args, kwargs)
    return values[0] if values else None


def _leading_name(spec: Any) -> str:
    if not isinstance(spec, str):
        return ""
    head = spec
    for separator in (":", ".", "/"):
        head = head.split(separator, 1)[0]
    return head.strip()


def _iter_field_names(kind: str, container) -> list[str]:
    if kind is FIELD:
        return [_leading_name(container)] if isinstance(container, str) else []
    if not isinstance(container, dict | list | tuple):
        return []
    names = list(container)
    if kind is PATHS:
        return [_leading_name(name) for name in names]
    return names


def _iter_grouping_specs(container):
    if isinstance(container, str):
        yield container
    elif isinstance(container, list | tuple):
        for item in container:
            yield from _iter_grouping_specs(item)


def _iter_vals_dicts(model_method: str, args, kwargs):
    for vals in arguments(model_method, VALS, args, kwargs):
        if isinstance(vals, dict):
            yield vals
        elif isinstance(vals, list | tuple):
            for item in vals:
                if isinstance(item, dict):
                    yield item


def _parse_domain(domain):
    if isinstance(domain, Domain):
        return domain
    if not isinstance(domain, list | tuple):
        return None
    try:
        return Domain(list(domain))
    except ValueError, TypeError:
        return None


def _domain_names(domain) -> list[str]:
    parsed = _parse_domain(domain)
    if parsed is None:
        return []
    return [_leading_name(str(c.field_expr)) for c in parsed.iter_conditions()]


def _order_names(order) -> list[str]:
    if not order or not isinstance(order, str):
        return []
    return [_leading_name(term.split()[0]) for term in order.split(",") if term.strip()]


def _requested_fields(model_method: str, args: list, kwargs: dict) -> list | None:
    names = []
    for kind in (FIELDS, PATHS, FIELD, SPEC):
        for container in arguments(model_method, kind, args, kwargs):
            names.extend(_iter_field_names(kind, container))
    return names or None


def domain_argument(model_method: str, args, kwargs):
    return _first(model_method, DOMAIN, args, kwargs)


def mentioned_field_names(model_method: str, args, kwargs) -> list[str]:
    names: list[str] = []
    for kind in (FIELDS, PATHS, FIELD, SPEC):
        for container in arguments(model_method, kind, args, kwargs):
            names.extend(_leading_name(n) for n in _iter_field_names(kind, container))
    for domain in arguments(model_method, DOMAIN, args, kwargs):
        names.extend(_domain_names(domain))
    for having in arguments(model_method, HAVING, args, kwargs):
        names.extend(_domain_names(having))
    for order in arguments(model_method, ORDER, args, kwargs):
        names.extend(_order_names(order))
    for container in arguments(model_method, GROUP, args, kwargs):
        names.extend(_leading_name(spec) for spec in _iter_grouping_specs(container))
    for vals in _iter_vals_dicts(model_method, args, kwargs):
        names.extend(_leading_name(key) for key in vals)
    return [name for name in names if name and not name.startswith("__")]


def _close_field_names(name: str, known: list) -> list:
    tokens = frozenset(name.split("_"))
    reordered = [k for k in known if frozenset(k.split("_")) == tokens and k != name]
    if reordered:
        return reordered[:2]
    return difflib.get_close_matches(name, known, n=2, cutoff=0.5)


def _describe_unknown(name, known: list) -> str:
    if not isinstance(name, str):
        return f"{name!r} (not a string)"
    close = _close_field_names(name, known)
    if close:
        return f"{name!r} (did you mean {' or '.join(repr(c) for c in close)}?)"
    return repr(name)


def _unknown_field_names(env, model_name: str, names) -> str:
    model_fields = env[model_name]._fields
    unknown = []
    for name in names:
        if isinstance(name, str) and (not name or name.startswith("__")):
            continue
        if (isinstance(name, str) and name in model_fields) or name in unknown:
            continue
        unknown.append(name)
    if not unknown:
        return ""
    known = sorted(model_fields)
    return ", ".join(_describe_unknown(name, known) for name in unknown)


def check_requested_fields(env, model_name: str, model_method: str, args, kwargs):
    requested = _requested_fields(model_method, args, kwargs)
    if requested is None:
        return
    if unknown := _unknown_field_names(env, model_name, requested):
        raise UserError(
            env._(
                "Unknown field(s) on '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_domain(env, model_name: str, model_method: str, args, kwargs):
    domain = domain_argument(model_method, args, kwargs)
    if domain is None or isinstance(domain, Domain):
        return
    if not isinstance(domain, list | tuple):
        raise UserError(
            env._(
                "The domain for '%(model)s' must be a list, got %(kind)s.",
                model=model_name,
                kind=type(domain).__name__,
            )
        )

    model = env[model_name]
    try:
        parsed = Domain(list(domain))
    except (ValueError, TypeError) as e:
        raise UserError(
            env._(
                "Malformed domain for '%(model)s': %(error)s",
                model=model_name,
                error=e,
            )
        ) from e

    if unknown := _unknown_field_names(env, model_name, _domain_names(parsed)):
        raise UserError(
            env._(
                "Unknown field(s) in the domain for '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=unknown,
            )
        )

    try:
        parsed.validate(model)
    except (ValueError, TypeError) as e:
        raise UserError(
            env._(
                "Invalid domain for '%(model)s': %(error)s",
                model=model_name,
                error=e,
            )
        ) from e


def check_order(env, model_name: str, model_method: str, args, kwargs):
    model_fields = env[model_name]._fields
    unknown = []
    for order in arguments(model_method, ORDER, args, kwargs):
        if not order or not isinstance(order, str):
            continue
        for term in order.split(","):
            parts = term.split()
            if not parts:
                continue
            head, _, rest = parts[0].partition(".")
            head = head.split(":", 1)[0]
            if not head:
                continue
            field = model_fields.get(head)
            if field is None:
                if head not in unknown:
                    unknown.append(head)
                continue
            if rest and not getattr(field, "is_properties", False):
                raise UserError(
                    env._(
                        "Cannot sort '%(model)s' by '%(term)s': '%(head)s' is a "
                        "relation, and sorting across a relation is not "
                        "supported. Sort by a field of '%(model)s' itself.",
                        model=model_name,
                        term=parts[0],
                        head=head,
                    )
                )
    if unknown := _unknown_field_names(env, model_name, unknown):
        raise UserError(
            env._(
                "Unknown field(s) in the sort order for '%(model)s': "
                "%(fields)s. Call fields_get('%(model)s') for the fields this "
                "model actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_grouping(env, model_name: str, model_method: str, args, kwargs):
    names = []
    for container in arguments(model_method, GROUP, args, kwargs):
        names.extend(_leading_name(spec) for spec in _iter_grouping_specs(container))
    for having in arguments(model_method, HAVING, args, kwargs):
        names.extend(_domain_names(having))
    if unknown := _unknown_field_names(env, model_name, [n for n in names if n]):
        raise UserError(
            env._(
                "Unknown field(s) in the group specification for '%(model)s': "
                "%(fields)s. Call fields_get('%(model)s') for the fields this "
                "model actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_write_values(env, model_name: str, model_method: str, args, kwargs):
    keys = [
        key for vals in _iter_vals_dicts(model_method, args, kwargs) for key in vals
    ]
    if unknown := _unknown_field_names(env, model_name, keys):
        raise UserError(
            env._(
                "Unknown field(s) on '%(model)s': %(fields)s. "
                "Call fields_get('%(model)s') for the fields this model "
                "actually has.",
                model=model_name,
                fields=unknown,
            )
        )


def check_call(env, model_name: str, model_method: str, args, kwargs):
    check_requested_fields(env, model_name, model_method, args, kwargs)
    check_domain(env, model_name, model_method, args, kwargs)
    check_order(env, model_name, model_method, args, kwargs)
    check_grouping(env, model_name, model_method, args, kwargs)
    check_write_values(env, model_name, model_method, args, kwargs)
