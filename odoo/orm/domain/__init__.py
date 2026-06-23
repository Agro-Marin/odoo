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
    # Optimization infrastructure
    OptimizationLevel,
    MAX_OPTIMIZE_ITERATIONS,
    ANY_TYPES,
    # Domain classes
    Domain,
    DomainBool,
    DomainNot,
    DomainNary,
    DomainAnd,
    DomainOr,
    DomainCustom,
    DomainCondition,
)

# Importing registers all optimization functions; must follow the AST imports.
from . import optimizations

# Re-export optimization decorators for extending
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
    # Constants
    "STANDARD_CONDITION_OPERATORS",
    "TRUE_LEAF",
    # Domain classes
    "Domain",
    "DomainAnd",
    "DomainBool",
    "DomainCondition",
    "DomainCustom",
    "DomainNary",
    "DomainNot",
    "DomainOr",
    # Optimization infrastructure
    "OptimizationLevel",
    "field_type_optimization",
    "nary_condition_optimization",
    "nary_optimization",
    "operator_optimization",
]
