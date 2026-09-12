import pytest

from odoo.orm.domain import Domain
from odoo.orm.domain.ast import DomainCondition


@pytest.mark.parametrize(
    "domain",
    [
        [("foo_id", "any", [("bar_id", "any", [("name", "=", "bar_a")])])],
        [
            "|",
            ("foo_id", "not any", []),
            ("foo_id", "any", ["|", ("bar_id", "not any", []), ("bar_id", "=", 1)]),
        ],
        [("foo_id", "any", [("bar_id", "in", [1, 2])])],
        [("foo_id", "not any", [("tag_ids", "not in", [3])])],
        [("tag_ids", "in", [1, 2])],
        [("name", "=", False)],
    ],
)
def test_list_of_a_domain_round_trips_to_the_lists_it_was_built_from(domain):
    assert list(Domain(domain)) == domain


def test_the_condition_still_holds_a_frozen_value():
    condition = DomainCondition("foo_id", "any", [("bar_id", "in", [1, 2])])
    assert condition.value == (("bar_id", "in", (1, 2)),)
    assert list(condition) == [("foo_id", "any", [("bar_id", "in", [1, 2])])]


def test_a_domain_object_as_value_serialises_as_its_list():
    condition = DomainCondition("foo_id", "any", Domain("bar_id", "in", [1, 2]))
    assert list(condition) == [("foo_id", "any", [("bar_id", "in", [1, 2])])]
