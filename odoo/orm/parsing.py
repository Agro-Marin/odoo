"""Expression and specification parsing for the ORM.

Parsing for field expressions, read_group specifications, and import/export
field paths. Widely shared (6+ consumers for parse_field_expr alone).
"""

import functools
import re

# Parsing patterns

# For import/export field path ID fixing. The lookahead makes the match
# token-based: ".id"/":id" convert only as a complete trailing designator
# (end of name or before a "/"), so "partner_id.identifier" or
# "partner_id:idx" are left alone instead of being mangled by a bare prefix
# match. \Z, not $ — $ would also match before a trailing newline.
_FIX_DB_ID_RE = re.compile(r"([^/])\.id(?=/|\Z)")
_FIX_EXTERNAL_ID_RE = re.compile(r"([^/]):id(?=/|\Z)")

# For _read_group (new API)
regex_read_group_spec = re.compile(r"(\w+)(\.([\w\.]+))?(?::(\w+))?$")

# For read_group (old API)
regex_field_agg = re.compile(r"(\w+)(?::(\w+)(?:\((\w+)\))?)?")

# For ORDER BY in read_group context (single order part, no anchors)
regex_order_part_read_group = re.compile(
    r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""",
    re.IGNORECASE | re.VERBOSE,
)

# For ORDER BY clause parsing (used by search and sort operations)
regex_order = re.compile(
    r"""
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
""",
    re.IGNORECASE | re.VERBOSE,
)


# Parsing functions


# Bounded cache: these parsers are reachable from authenticated RPC with
# user-controlled, effectively unbounded distinct inputs (e.g.
# ``props.<arbitrary>``). An unbounded ``functools.cache`` would be a slow
# memory-exhaustion vector; LRU caps memory while keeping the hot set.
_PARSE_CACHE_MAXSIZE = 2048


@functools.lru_cache(maxsize=_PARSE_CACHE_MAXSIZE)
def parse_field_expr(field_expr: str) -> tuple[str, str | None]:
    """Parse ``"field"`` or ``"field.property"`` into ``(field, property)``.

    ``property`` is ``None`` when absent.

    :raises ValueError: empty or malformed expression (leading/trailing dot,
        or an empty segment between dots).
    """
    raw = field_expr
    if (property_index := field_expr.find(".")) >= 0:
        property_name = field_expr[property_index + 1 :]
        field_expr = field_expr[:property_index]
    else:
        property_name = None
    if not field_expr or (property_name is not None and not property_name):
        raise ValueError(f"Invalid field expression {raw!r}")
    if property_name is not None and (
        property_name.startswith(".")
        or property_name.endswith(".")
        or ".." in property_name
    ):
        raise ValueError(f"Invalid field expression {raw!r}")
    return field_expr, property_name


@functools.lru_cache(maxsize=_PARSE_CACHE_MAXSIZE)
def parse_read_group_spec(spec: str) -> tuple[str, str | None, str | None]:
    """Parse a read_group spec into ``(field, property, aggregate/granularity)``.

    E.g. ``"amount:sum"`` → ``('amount', None, 'sum')``;
    ``"properties.color:count"`` → ``('properties', 'color', 'count')``.

    :raises ValueError: if the spec format is invalid.
    """
    res_match = regex_read_group_spec.match(spec)
    if not res_match:
        raise ValueError(
            f"Invalid aggregate/groupby specification {spec!r}.\n"
            '- Valid aggregate specification looks like "<field_name>:<agg>" example: "quantity:sum".\n'
            '- Valid groupby specification looks like "<no_datish_field_name>" or "<datish_field_name>:<granularity>" example: "date:month" or "<properties_field_name>.<property>:<granularity>".'
        )

    groups = res_match.groups()
    return groups[0], groups[2], groups[3]


@functools.lru_cache(maxsize=_PARSE_CACHE_MAXSIZE)
def fix_import_export_id_paths(fieldname: str) -> tuple[str, ...]:
    """Normalize import/export id syntax and split the field path on '/'.

    Converts ``.id`` (database id) to ``/.id`` and ``:id`` (external id) to
    ``/id``, then splits into a tuple. E.g. ``"partner_id.id"`` →
    ``('partner_id', '.id')``; ``"partner_id:id"`` → ``('partner_id', 'id')``.
    """
    fixed_db_id = _FIX_DB_ID_RE.sub(r"\1/.id", fieldname)
    fixed_external_id = _FIX_EXTERNAL_ID_RE.sub(r"\1/id", fixed_db_id)
    return tuple(fixed_external_id.split("/"))
