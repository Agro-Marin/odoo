from collections.abc import Collection
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

EXTENDED_CONDITION_OPERATORS: Final[frozenset[str]] = frozenset(
    ("=?", "<>", "==", "=", "!=", "parent_of", "child_of")
)
"""Operators accepted on input and reduced to standard ones by the optimizer.

Declared here rather than accumulated by ``@operator_optimization``'s side
effect. Until 2026-08-08 :data:`CONDITION_OPERATORS` was a **mutable set** that
each decorator ``update()``d at import time, and ``DomainCondition.checked()``
used it as the validation oracle -- so the set of operators the framework
accepted was whatever had been imported, and a typo in a decorator argument
silently widened the domain language instead of failing.

That had already caused one bug, recorded on
:data:`LIKE_CONDITION_OPERATORS` below: a comprehension over the mutable set,
evaluated at import time, whose result depended on how many decorators had run
above it. The fix then was to derive that one name from the frozen standard set;
this is the same fix applied to the cause. ``operator_optimization`` now asserts
membership instead of mutating.
"""

CONDITION_OPERATORS: Final[frozenset[str]] = (
    STANDARD_CONDITION_OPERATORS | EXTENDED_CONDITION_OPERATORS
)
"""All condition operators the framework itself declares.

Non-standard operators are reduced to standard ones by the optimization
functions (see each for details).

This is the *framework's* language and is frozen. An addon that adds a
predicate the framework has no notion of -- ``geoengine``'s PostGIS operators
are the only case in this codebase -- contributes it through
:func:`register_condition_operators`, and the union of the two is
:data:`ACCEPTED_CONDITION_OPERATORS`.
"""

ACCEPTED_CONDITION_OPERATORS: set[str] = set(CONDITION_OPERATORS)
"""Operators a condition may actually carry: the frozen set above, plus what
addons have registered.

Mutable, and deliberately so, but **not** a return to what
:data:`EXTENDED_CONDITION_OPERATORS` describes. What made the old mutable set a
defect was that ``@operator_optimization`` widened it as a *side effect*, so a
typo in a decorator argument invented an operator instead of failing. Widening
now takes a named call that says what it is doing and validates its argument;
the decorator only ever *reads* this set. Membership is the hot path in
``DomainCondition.checked()``, so consumers import this object and test against
it directly rather than recomputing a union per call -- which is why it is
mutated in place and never rebound.
"""


def register_condition_operators(operators: Collection[str]) -> frozenset[str]:
    """Declare addon-provided condition operators and return them as a set.

    Call at import time of the module that implements the operators, before the
    ``@operator_optimization`` that gives them meaning -- the decorator
    validates against the registry, so registration has to come first.

    Registering an operator only makes it *sayable*: a condition carrying it
    survives ``checked()``. Something still has to give it meaning, or the
    domain will reach a consumer that cannot translate it.
    """
    operators = frozenset(operators)
    if not operators:
        raise ValueError("Missing operator to register")
    if collisions := operators & CONDITION_OPERATORS:
        raise ValueError(
            f"cannot redefine the framework's own operator(s) "
            f"{sorted(collisions)!r}; addon operators must be new names."
        )
    if malformed := {op for op in operators if not op or op != op.lower()}:
        raise ValueError(
            f"domain operator(s) {sorted(malformed)!r} must be non-empty and "
            f"lower-case; DomainCondition.checked() lower-cases the operator "
            f"before looking it up, so a mixed-case name could never match."
        )
    ACCEPTED_CONDITION_OPERATORS.update(operators)
    return operators

LIKE_CONDITION_OPERATORS: Final[frozenset[str]] = frozenset(
    op for op in STANDARD_CONDITION_OPERATORS if op.endswith("like")
)
"""The ``like`` family, derived from the frozen standard set.

Declared here rather than recomputed from :data:`CONDITION_OPERATORS` at the
point of use. ``optimizations.py`` used to register ``_optimize_like_str`` with
``[op for op in CONDITION_OPERATORS if op.endswith("like")]`` -- a comprehension
over the mutable set that ``operator_optimization()`` itself updates, evaluated
at import time, so its result depended on how many decorators had already run
above it in the file. It happened to be correct only because none of them
registers a ``like`` operator today.
"""

INTERNAL_CONDITION_OPERATORS: Final[frozenset[str]] = frozenset(("any!", "not any!"))

SUBDOMAIN_OPERATORS: Final[frozenset[str]] = frozenset(
    ("any", "any!", "not any", "not any!")
)
"""Operators whose value must be parsed as a Domain when ``internal=True``.

Named so ``Domain.__new__``'s fast path and stack parser cannot diverge.
"""

SUBDOMAIN_OR_IN_OPERATORS: Final[frozenset[str]] = SUBDOMAIN_OPERATORS | frozenset(
    ("in", "not in")
)
"""Operators whose value may legitimately be a ``Domain``, ``Query`` or ``SQL``.

Named for the same reason as :data:`SUBDOMAIN_OPERATORS` -- so the set has one
spelling. ``DomainCondition.checked()`` wrote this union out as an inline tuple
literal thirty lines below a correct use of ``SUBDOMAIN_OPERATORS``, which is a
third copy of the set the constant exists to keep single.
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
    "EXTENDED_CONDITION_OPERATORS",
    "FALSE_LEAF",
    "INTERNAL_CONDITION_OPERATORS",
    "INVERSE_INEQUALITY",
    "INVERSE_OPERATOR",
    "LIKE_CONDITION_OPERATORS",
    "NEGATIVE_CONDITION_OPERATORS",
    "STANDARD_CONDITION_OPERATORS",
    "SUBDOMAIN_OPERATORS",
    "SUBDOMAIN_OR_IN_OPERATORS",
    "TRUE_LEAF",
]
