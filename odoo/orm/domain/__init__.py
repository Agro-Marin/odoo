"""Domain expression processing package.

A domain is a first-order logical predicate filtering records, represented as an
AST of boolean operators:

- n-ary operators: AND, OR
- unary operator: NOT
- boolean constants: TRUE, FALSE
- conditions: ``(expression, operator, value)``

In a condition, *expression* is usually a field name, optionally using
dot-notation to traverse relationships (equivalent to the ``any`` operator) or
access field properties; *operator* is one of ``CONDITION_OPERATORS`` (described
there); *value* is a Python value the operator supports.

Layout: ``constants.py`` (operators/mappings), ``ast.py`` (Domain classes),
``optimizations.py`` (optimization functions).
"""

from .constants import (
    STANDARD_CONDITION_OPERATORS,
    CONDITION_OPERATORS,
    INTERNAL_CONDITION_OPERATORS,
    NEGATIVE_CONDITION_OPERATORS,
    INVERSE_OPERATOR,
    INVERSE_INEQUALITY,
    TRUE_LEAF,
    FALSE_LEAF,
)

from .ast import (
    OptimizationLevel,
    MAX_OPTIMIZE_ITERATIONS,
    ANY_TYPES,
    Domain,
    DomainBool,
    DomainNot,
    DomainNary,
    DomainAnd,
    DomainOr,
    DomainCustom,
    DomainCondition,
)

from . import optimizations

from .optimizations import (
    operator_optimization,
    field_type_optimization,
    nary_optimization,
    nary_condition_optimization,
)

__all__ = [
    "ANY_TYPES",
    "CONDITION_OPERATORS",
    "FALSE_LEAF",
    "INTERNAL_CONDITION_OPERATORS",
    "INVERSE_INEQUALITY",
    "INVERSE_OPERATOR",
    "MAX_OPTIMIZE_ITERATIONS",
    "NEGATIVE_CONDITION_OPERATORS",
    "STANDARD_CONDITION_OPERATORS",
    "TRUE_LEAF",
    "Domain",
    "DomainAnd",
    "DomainBool",
    "DomainCondition",
    "DomainCustom",
    "DomainNary",
    "DomainNot",
    "DomainOr",
    "OptimizationLevel",
    "field_type_optimization",
    "nary_condition_optimization",
    "nary_optimization",
    "operator_optimization",
]
