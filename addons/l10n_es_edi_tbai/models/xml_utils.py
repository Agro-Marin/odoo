# -*- coding: utf-8 -*-
from lxml import etree
from odoo.tools.xml_utils import cleanup_xml_node


# Utility Methods for Basque Country's TicketBAI XML-related stuff.
# The xmldsig reference processing this module used to carry now lives in
# odoo.libs.xml.dsig, shared with the other e-invoicing localizations.

NS_MAP = {'': 'http://www.w3.org/2000/09/xmldsig#'}  # default namespace matches signature's `ds:``


def cleanup_xml_signature(xml_sig):
    """
    Cleanups the content of the provided string representation of an XML signature.
    In addition, removes all line feeds for the ds:Object element.
    Turns self-closing tags into regular tags (with an empty string content)
    as the former may not be supported by some signature validation implementations.
    Returns an etree._Element
    """
    sig_elem = cleanup_xml_node(xml_sig, remove_blank_nodes=False, indent_level=-1)
    etree.indent(sig_elem, space='')  # removes indentation
    for elem in sig_elem.find('Object', namespaces=NS_MAP).iter():
        if elem.text == '\n':
            elem.text = ''  # keeps the signature in one line, prevents self-closing tags
        elem.tail = ''  # removes line feed and whitespace after the tag
    return sig_elem
