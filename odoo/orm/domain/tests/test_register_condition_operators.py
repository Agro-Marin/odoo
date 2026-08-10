import pytest

from odoo.orm.domain.constants import (
    ACCEPTED_CONDITION_OPERATORS,
    CONDITION_OPERATORS,
    register_condition_operators,
)


@pytest.fixture
def restore_registry():
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
        with pytest.raises(ValueError, match="cannot redefine"):
            register_condition_operators(["in"])
        with pytest.raises(ValueError, match="cannot redefine"):
            register_condition_operators(["geo_probe_ok", "="])

    def test_a_collision_leaves_the_registry_untouched(self, restore_registry):
        with pytest.raises(ValueError):
            register_condition_operators(["geo_probe_ok", "="])
        assert "geo_probe_ok" not in ACCEPTED_CONDITION_OPERATORS

    def test_a_mixed_case_operator(self, restore_registry):
        with pytest.raises(ValueError, match="lower-case"):
            register_condition_operators(["Geo_Probe_Within"])

    def test_an_empty_operator_name(self, restore_registry):
        with pytest.raises(ValueError, match="non-empty"):
            register_condition_operators([""])
