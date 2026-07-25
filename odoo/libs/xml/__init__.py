"""XML utilities.

Pure Python XML helpers with no Odoo dependencies.
Uses standard library and lxml for XML processing.
"""

# Installs Odoo's hardened lxml defaults (XXE + decompression-bomb guards) as
# an import side effect -- see the module docstring for why it belongs here.
from .parsers import default_parser

from .utils import (
    remove_control_characters,
    create_xml_node_chain,
    create_xml_node,
)

from .template_inheritance import (
    locate_node,
    apply_inheritance_specs,
    add_stripped_items_before,
    add_text_before,
    remove_element,
    SKIPPED_ELEMENT_TYPES,
    PYTHON_ATTRIBUTES,
    XPathExpressionError,
)

__all__ = [
    "PYTHON_ATTRIBUTES",
    "SKIPPED_ELEMENT_TYPES",
    "XPathExpressionError",
    "add_stripped_items_before",
    "add_text_before",
    "apply_inheritance_specs",
    "create_xml_node",
    "create_xml_node_chain",
    "default_parser",
    # template_inheritance
    "locate_node",
    # utils
    "remove_control_characters",
    "remove_element",
]
