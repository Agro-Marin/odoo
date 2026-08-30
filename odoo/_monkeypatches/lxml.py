"""Teach ``iterlinks()`` about ``xlink:href``.

``lxml.html.defs.link_attrs`` is read as a local default inside
``HtmlMixin.iterlinks()`` (``lxml/html/__init__.py``), so widening it is the only
way to make that walk yield SVG's ``xlink:href``. The cleaner does *not* consult
it -- ``lxml_html_clean`` carries its own ``_tag_link_attrs`` -- so this changes
link rewriting and nothing about sanitisation.

It lived as a bare ``defs.link_attrs |= {"xlink:href"}`` at import time in
``odoo/libs/text/html.py``, which is a process-global mutation of a third-party
module performed by a file its only beneficiary never imports:
``ir_module._get_desc`` calls ``iterlinks()`` and reaches ``odoo.libs.rst``, not
``odoo.libs.text.html``. Whether the widening was in effect therefore depended on
whether something else had pulled the HTML stack in first. Here it is declared,
discoverable beside every other third-party patch, and applied when ``lxml.html``
is imported.
"""

from lxml.html import defs

XLINK_HREF = "xlink:href"


def patch_module() -> None:
    defs.link_attrs |= {XLINK_HREF}
