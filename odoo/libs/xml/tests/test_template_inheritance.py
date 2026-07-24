"""Regression tests for ``odoo.libs.xml.template_inheritance``.

Covers the ``<attribute remove=…>`` literal-vs-regex contract, which decides
what ``invisible`` / ``readonly`` expressions survive view inheritance.
"""

import pytest
from lxml import etree

from odoo.libs.xml.template_inheritance import apply_inheritance_specs, locate_node


def _apply(original: str, *, remove: str, separator: str = "and", add: str = "") -> str:
    """Apply ``<attribute name="invisible" remove=… >`` and return the new value."""
    arch = etree.fromstring(f'<form><field name="a" invisible="{original}"/></form>')
    add_attr = f' add="{add}"' if add else ""
    spec = etree.fromstring(
        f'<field name="a" position="attributes">'
        f'<attribute name="invisible" remove="{remove}"{add_attr}'
        f' separator="{separator}"/></field>'
    )
    return apply_inheritance_specs(arch, spec)[0].get("invisible", "")


class TestAttributeRemoveIsLiteral:
    """``remove`` is a literal expression, never a regex pattern."""

    def test_exact_match_clears_the_attribute(self):
        assert _apply("state == 'draft'", remove="state == 'draft'") == ""

    def test_alternation_is_not_a_regex_alternative(self):
        # "a|b" is not a term of "a or b"; interpolated raw, `^\(*a|b\)*$`
        # matched the bare "a" and wiped the whole attribute.
        assert _apply("a or b", remove="a|b", separator="or") == "a or b"

    def test_dot_is_not_a_wildcard(self):
        assert _apply("axb", remove="a.b") == "axb"

    def test_unbalanced_paren_does_not_raise(self):
        # `^\(*(\)*$` is not a valid pattern: this used to be a re.PatternError
        # escaping as a 500.
        assert _apply("foo", remove="(") == "foo"

    def test_term_removal_still_works(self):
        # the surviving term keeps whatever parentheses it was written with
        assert _apply("(a) and (b)", remove="b") == "(a)"
        assert _apply("a and b", remove="b") == "a"

    def test_add_after_remove(self):
        assert _apply("a", remove="a", add="b") == "b"


class TestLocateNode:
    def test_xpath_without_expr_raises_value_error(self):
        # ETXPath(None) raises TypeError, which bypasses the
        # ValueError -> ValidationError wrapper in ir.ui.view.
        arch = etree.fromstring("<form><field name='a'/></form>")
        spec = etree.fromstring('<xpath position="replace"><p/></xpath>')
        with pytest.raises(ValueError, match="missing 'expr'"):
            locate_node(arch, spec)


class TestSpecQueue:
    def test_caller_list_is_not_consumed(self):
        arch = etree.fromstring("<form><field name='a'/></form>")
        specs = list(
            etree.fromstring(
                '<data><field name="a" position="attributes">'
                '<attribute name="x">1</attribute></field></data>'
            )
        )
        apply_inheritance_specs(arch, specs)
        assert len(specs) == 1
        # and the spec still applies on a second run against a fresh source
        arch2 = etree.fromstring("<form><field name='a'/></form>")
        assert apply_inheritance_specs(arch2, specs)[0].get("x") == "1"
