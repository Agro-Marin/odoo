"""Domain operator constants and mappings."""

from typing import Final

STANDARD_CONDITION_OPERATORS: Final[frozenset[str]] = frozenset(
    [
        "any",
        "not any",
        "any!",
        "not any!",
        "in",
        "not in",
        "<",
        ">",
        "<=",
        ">=",
        "like",
        "not like",
        "ilike",
        "not ilike",
        "=like",
        "not =like",
        "=ilike",
        "not =ilike",
    ]
)
"""Standard operators for conditions, supported at all framework levels.

- `any` works for relational fields and `id` to check if a record matches
  the condition
  - if value is SQL or Query, see `any!`
  - if bypass_search_access is set on the field, see `any!`
  - if value is a Domain for a many2one (or `id`),
    _search with active_test=False
  - if value is a Domain for a x2many,
    _search on the comodel of the field (with its context)
- `any!` works like `any` but bypass adding record rules on the comodel
- `in` for equality checks where the given value is a collection of values
  - the collection is transformed into OrderedSet
  - False value indicates that the value is *not set*
  - for relational fields
    - if int, bypass record rules
    - if str, search using display_name of the model
  - the value should have the type of the field
  - SQL type is always accepted
- `<`, `>`, ... inequality checks, similar behaviour to `in` with a single value
- string pattern comparison
  - `=like` case-sensitive compare to a string using SQL like semantics
  - `=ilike` case-insensitive with `unaccent` comparison to a string
  - `like`, `ilike` behave like the preceding methods, but add wildcards
    around the value
  - an empty pattern is rewritten before either consumer sees it
    (``_optimize_like_str``): ``like ''`` becomes TRUE — *including* NULL rows,
    unlike SQL ``LIKE '%%'`` which excludes them — and ``not like ''`` becomes
    FALSE — *excluding* NULL rows, an exception to negative operators otherwise
    matching unset values; SQL and predicate consumers agree because both see
    the rewritten form
"""

CONDITION_OPERATORS: set[str] = set(
    STANDARD_CONDITION_OPERATORS
)  # modifiable (for optimizations only)
"""All available condition operators.

Non-standard operators are reduced to standard ones by the optimization
functions (see each for details).
"""

INTERNAL_CONDITION_OPERATORS: Final[frozenset[str]] = frozenset(("any!", "not any!"))

SUBDOMAIN_OPERATORS: Final[frozenset[str]] = frozenset(
    ("any", "any!", "not any", "not any!")
)
"""Operators whose value must be parsed as a Domain when ``internal=True``.

Named so ``Domain.__new__``'s fast path and stack parser cannot diverge.
"""

NEGATIVE_CONDITION_OPERATORS: Final[dict[str, str]] = {
    "not any": "any",
    "not any!": "any!",
    "not in": "in",
    "not like": "like",
    "not ilike": "ilike",
    "not =like": "=like",
    "not =ilike": "=ilike",
    "!=": "=",
    "<>": "=",
}
"""Negative-semantic operators mapped to their positive operator."""

# negations for operators (used in DomainNot), derived from
# NEGATIVE_CONDITION_OPERATORS so the two cannot drift: every negative→positive
# pair plus its reverse. The legacy "<>" alias is skipped when building the
# reverse so "=" canonicalises to "!=" (not "<>"); "<>"→"=" is kept from the
# forward map. See test_domain_constants for the locked-in expected mapping.
INVERSE_OPERATOR: Final[dict[str, str]] = {
    **NEGATIVE_CONDITION_OPERATORS,
    **{
        positive: negative
        for negative, positive in NEGATIVE_CONDITION_OPERATORS.items()
        if negative != "<>"
    },
}

INVERSE_INEQUALITY: Final[dict[str, str]] = {
    "<": ">=",
    ">": "<=",
    ">=": "<",
    "<=": ">",
}
"""Inverse of inequality operators; separate because of null-value handling."""

TRUE_LEAF: Final[tuple[int, str, int]] = (1, "=", 1)
FALSE_LEAF: Final[tuple[int, str, int]] = (0, "=", 1)

__all__ = [
    "CONDITION_OPERATORS",
    "FALSE_LEAF",
    "INTERNAL_CONDITION_OPERATORS",
    "INVERSE_INEQUALITY",
    "INVERSE_OPERATOR",
    "NEGATIVE_CONDITION_OPERATORS",
    "STANDARD_CONDITION_OPERATORS",
    "SUBDOMAIN_OPERATORS",
    "TRUE_LEAF",
]
