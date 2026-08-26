from .._pg import assert_dependencies_present
from .conftest import REQUIREMENTS


def test_dependencies_are_present():
    assert_dependencies_present(REQUIREMENTS)
