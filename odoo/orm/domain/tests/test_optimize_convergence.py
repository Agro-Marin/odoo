"""Non-convergence must not be reported as stack exhaustion.

Both failures used to funnel into ``_recursion_error_as_value_error``: the
fixpoint guard raised ``RecursionError``, the wrapper caught it and re-raised a
``ValueError`` about nesting depth, and ``from None`` hid the original. The two
have opposite remedies, so the message mattered.
"""

from unittest.mock import patch

import pytest

from odoo.orm.domain import ast as dast
from odoo.orm.domain import optimizations  # noqa: F401  registers the optimizers
from odoo.orm.domain.ast import Domain, DomainOptimizationError

_FALSY_BY_TYPE = {"char": "", "integer": 0, "boolean": False}


class _Field:
    def __init__(self, name, ftype, model_name):
        self.name = name
        self.type = ftype
        self.model_name = model_name
        self.relational = False
        self.comodel_name = None
        self.store = True
        self.required = False
        self.inherited = False
        self.company_dependent = False
        self.falsy_value = _FALSY_BY_TYPE.get(ftype)


class _Model:
    def __init__(self, name, field_types):
        self._name = name
        self._fields = {n: _Field(n, t, name) for n, t in field_types.items()}


@pytest.fixture
def model():
    return _Model("m", {"a": "integer", "b": "integer"})


@pytest.fixture
def domain():
    return Domain("a", "=", 5) & Domain("b", "in", [1, 2, 5])


class TestNonConvergence:
    def test_raises_its_own_error_not_recursion_error(self, domain, model):
        with patch.object(dast, "MAX_OPTIMIZE_ITERATIONS", 0):
            with pytest.raises(DomainOptimizationError) as caught:
                domain.optimize(model)
        assert not isinstance(caught.value, RecursionError)

    def test_the_message_names_the_real_cause(self, domain, model):
        with patch.object(dast, "MAX_OPTIMIZE_ITERATIONS", 0):
            with pytest.raises(DomainOptimizationError) as caught:
                domain.optimize(model)
        message = str(caught.value)
        assert "did not converge" in message
        assert "optimizer defect" in message
        # The regression: it must NOT claim the domain was too deeply nested.
        assert "nesting" not in message
        assert "exhausts the evaluation stack" not in message

    def test_it_survives_the_recursion_error_wrapper(self, domain, model):
        """The wrapper wraps every public entry point; it must not swallow this."""
        for entry in ("optimize", "optimize_full", "validate"):
            with patch.object(dast, "MAX_OPTIMIZE_ITERATIONS", 0):
                with pytest.raises(DomainOptimizationError):
                    getattr(domain, entry)(model)

    def test_it_stays_catchable_as_value_error(self, domain, model):
        """Existing callers catch ValueError; the new type must not break them."""
        with patch.object(dast, "MAX_OPTIMIZE_ITERATIONS", 0):
            with pytest.raises(ValueError):
                domain.optimize(model)


class TestGenuineRecursionStillReportsNesting:
    def test_a_real_recursion_error_still_reports_nesting(self, domain, model):
        # Patch the concrete node type: `_optimize_step` is overridden per
        # subclass, so patching `Domain` itself intercepts nothing.
        with patch.object(
            type(domain), "_optimize_step", side_effect=RecursionError("stack")
        ):
            with pytest.raises(ValueError) as caught:
                domain.optimize(model)
        assert "nesting too deep" in str(caught.value)
        assert not isinstance(caught.value, DomainOptimizationError)
