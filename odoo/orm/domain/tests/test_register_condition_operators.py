"""`register_condition_operators` is the only sanctioned way to widen the
operator vocabulary, so its refusals are the contract.

The framework's own operators are frozen in `CONDITION_OPERATORS`; an addon that
implements a predicate the framework has no notion of -- `agromarin/geoengine`'s
PostGIS operators are the only case in this codebase -- registers it here, and
`ACCEPTED_CONDITION_OPERATORS` is the union that `DomainCondition.checked()`
tests against.

**Why the named call rather than the old mutable set.** `EXTENDED_CONDITION_
OPERATORS` used to be widened as a *side effect* of `@operator_optimization`, so
a typo in a decorator argument invented an operator instead of failing. Widening
now takes a call that says what it is doing and validates its argument; the
decorator only reads. Each refusal below is one way the side-effecting version
could not fail.
"""

import pytest

from odoo.orm.domain.constants import (
    ACCEPTED_CONDITION_OPERATORS,
    CONDITION_OPERATORS,
    register_condition_operators,
)


@pytest.fixture
def restore_registry():
    """The accepted set is process-global and mutated in place; put it back."""
    before = set(ACCEPTED_CONDITION_OPERATORS)
    yield
    ACCEPTED_CONDITION_OPERATORS.clear()
    ACCEPTED_CONDITION_OPERATORS.update(before)


class TestItWidensTheVocabulary:
    def test_a_registered_operator_becomes_acceptable(self, restore_registry):
        assert "geo_probe_within" not in ACCEPTED_CONDITION_OPERATORS
        register_condition_operators(["geo_probe_within"])
        assert "geo_probe_within" in ACCEPTED_CONDITION_OPERATORS

    def test_it_returns_its_argument_as_a_frozenset(self, restore_registry):
        returned = register_condition_operators(["geo_probe_a", "geo_probe_b"])
        assert returned == frozenset({"geo_probe_a", "geo_probe_b"})
        assert isinstance(returned, frozenset)

    def test_registering_twice_is_harmless(self, restore_registry):
        register_condition_operators(["geo_probe_within"])
        register_condition_operators(["geo_probe_within"])
        assert "geo_probe_within" in ACCEPTED_CONDITION_OPERATORS

    def test_it_accepts_any_collection(self, restore_registry):
        register_condition_operators(op for op in ("geo_probe_gen",))
        assert "geo_probe_gen" in ACCEPTED_CONDITION_OPERATORS

    def test_the_framework_s_own_set_is_never_mutated(self, restore_registry):
        before = frozenset(CONDITION_OPERATORS)
        register_condition_operators(["geo_probe_within"])
        assert before == CONDITION_OPERATORS
        assert "geo_probe_within" not in CONDITION_OPERATORS


class TestItRefuses:
    def test_an_empty_registration(self, restore_registry):
        with pytest.raises(ValueError, match="Missing operator to register"):
            register_condition_operators([])

    def test_redefining_a_framework_operator(self, restore_registry):
        """The failure the side-effecting version could not have.

        Shadowing ``=`` or ``in`` would change the meaning of every domain in
        every module, from one addon's import.
        """
        with pytest.raises(ValueError, match="cannot redefine"):
            register_condition_operators(["in"])
        with pytest.raises(ValueError, match="cannot redefine"):
            register_condition_operators(["geo_probe_ok", "="])

    def test_a_collision_leaves_the_registry_untouched(self, restore_registry):
        """A refused call must not half-apply the batch it refused."""
        with pytest.raises(ValueError):
            register_condition_operators(["geo_probe_ok", "="])
        assert "geo_probe_ok" not in ACCEPTED_CONDITION_OPERATORS

    def test_a_mixed_case_operator(self, restore_registry):
        """`DomainCondition.checked()` lower-cases before lookup.

        A mixed-case name could therefore never match, so accepting it would
        register an operator that is silently unusable.
        """
        with pytest.raises(ValueError, match="lower-case"):
            register_condition_operators(["Geo_Probe_Within"])

    def test_an_empty_operator_name(self, restore_registry):
        with pytest.raises(ValueError, match="non-empty"):
            register_condition_operators([""])
