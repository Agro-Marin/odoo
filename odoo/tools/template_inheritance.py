from typing import TYPE_CHECKING

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.libs.xml import XPathExpressionError
from odoo.libs.xml import (
    apply_inheritance_specs as _apply_inheritance_specs_base,
)
from odoo.libs.xml import (
    locate_node as _locate_node_base,
)
from odoo.libs.xml.template_inheritance import _compile_xpath
from odoo.tools.translate import LazyTranslate

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["apply_inheritance_specs", "locate_node"]

_lt = LazyTranslate("base")


def locate_node(arch: etree._Element, spec: etree._Element) -> etree._Element | None:
    if spec.tag == "xpath":
        expr = spec.get("expr")
        if expr is None:
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
    return _locate_node_base(arch, spec)


def apply_inheritance_specs(
    source: etree._Element,
    specs_tree: etree._Element,
    inherit_branding: bool = False,
    pre_locate: Callable[[etree._Element], None] | None = None,
) -> etree._Element:
    try:
        return _apply_inheritance_specs_base(
            source, specs_tree, inherit_branding, pre_locate
        )
    except XPathExpressionError as e:
        raise ValidationError(str(e)) from e
