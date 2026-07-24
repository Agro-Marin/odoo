"""
Odoo template inheritance utilities.

This module wraps odoo.libs.xml.template_inheritance to provide Odoo-specific
error handling (ValidationError for XPath errors) for better user experience.

For agnostic usage without Odoo dependencies, use odoo.libs.xml.template_inheritance directly.
"""

from typing import TYPE_CHECKING

from lxml import etree

from odoo.exceptions import ValidationError

# Import agnostic versions for wrapping
from odoo.libs.xml.template_inheritance import (
    _compile_xpath,
)
from odoo.libs.xml.template_inheritance import (
    apply_inheritance_specs as _apply_inheritance_specs_base,
)
from odoo.libs.xml.template_inheritance import (
    locate_node as _locate_node_base,
)
from odoo.tools.translate import LazyTranslate

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["apply_inheritance_specs", "locate_node"]

_lt = LazyTranslate("base")


def locate_node(arch: etree._Element, spec: etree._Element) -> etree._Element | None:
    """Locate the node in a source (parent) architecture matching a spec node.

    :param arch: the parent architecture (e.g. a view's ``arch`` field) to search
    :param spec: a node from an inheriting view describing where a change applies
    :return: the matching node in the source, or None if it does not exist
    :raise: ValidationError if the xpath expression is invalid
    """
    if spec.tag == "xpath":
        expr = spec.get("expr")
        if expr is None:
            # A bare <xpath> without expr would reach _compile_xpath(None) and
            # raise an uncaught TypeError; fail with a clear ValidationError.
            raise ValidationError(
                _lt("Missing 'expr' attribute in xpath specification")
            )
        try:
            xPath = _compile_xpath(expr)
        except etree.XPathSyntaxError as e:
            raise ValidationError(
                _lt('Invalid Expression while parsing xpath "%s"', expr)
            ) from e
        nodes = xPath(arch)
        return nodes[0] if nodes else None
    # For non-xpath specs, delegate to base implementation
    return _locate_node_base(arch, spec)


def apply_inheritance_specs(
    source: etree._Element,
    specs_tree: etree._Element,
    inherit_branding: bool = False,
    pre_locate: Callable[[etree._Element], None] | None = None,
) -> etree._Element:
    """Apply an inheriting view's spec nodes to a source architecture.

    :param Element source: a parent architecture to modify
    :param Element specs_tree: a modifying architecture in an inheriting view
    :param bool inherit_branding:
    :param pre_locate: called before locating a node, with the arch as argument;
                        required by studio to properly handle group_ids
    :return: a modified source where the specs are applied
    :rtype: Element
    :raise: ValidationError for invalid xpath expressions
    :raise: ValueError for other invalid specs or if nodes cannot be located
    """
    # Catch ValueError from the base implementation and convert XPath-related
    # errors to ValidationError; other ValueErrors propagate unchanged (their
    # messages are dynamic, so they cannot be statically translated).
    try:
        return _apply_inheritance_specs_base(
            source, specs_tree, inherit_branding, pre_locate
        )
    except ValueError as e:
        error_msg = str(e)
        if "Invalid Expression while parsing xpath" in error_msg:
            raise ValidationError(error_msg) from e  # pylint: disable=E8502
        raise
