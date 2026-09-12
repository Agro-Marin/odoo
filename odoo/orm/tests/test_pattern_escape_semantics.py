import re

import pytest

from odoo.orm.fields._field_sql import _get_like_regex


@pytest.mark.parametrize("pattern", ["\\", "a\\", "a\\\\\\"])
def test_exact_pattern_rejects_an_unpaired_final_escape(pattern):
    with pytest.raises(ValueError, match="must not end with an escape"):
        _get_like_regex(pattern, exact=True)


@pytest.mark.parametrize("exact", [False, True])
def test_a_pair_of_final_escapes_matches_a_literal_backslash(exact):
    expression = re.compile(_get_like_regex("a\\\\", exact))
    assert expression.match("a\\")
    assert not expression.match("a")


def test_implicit_percent_is_part_of_the_escaped_pattern():
    expression = re.compile(_get_like_regex("a\\", exact=False))
    assert expression.match("a%")
    assert expression.match("xa%")
    assert not expression.match("a")
    assert not expression.match("a%x")
    assert not expression.match("a%\n")


@pytest.mark.parametrize(
    "value", ["*", "?", "[", "]", "[a]", "[!a]", "a*b", "a?b", "a[b]"]
)
@pytest.mark.parametrize("exact", [False, True])
def test_glob_metacharacters_remain_sql_literals(value, exact):
    expression = re.compile(_get_like_regex(value, exact))
    assert expression.match(value)
    assert not expression.match("x")


def test_many_wildcards_preserve_match_results():
    expression = re.compile(_get_like_regex("%a" * 12 + "b", exact=False))
    assert expression.match("a" * 24 + "b")
    assert not expression.match("a" * 24)
