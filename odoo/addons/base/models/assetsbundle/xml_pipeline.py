import re
from copy import deepcopy
from typing import TYPE_CHECKING

from lxml import etree

from odoo.tools import OrderedSet
from odoo.tools.json import scriptsafe as json

if TYPE_CHECKING:
    from .bundle import AssetsBundle
    from .common import XMLBlock
from .common import XMLAssetError


class XmlTemplatePipeline:
    """Render one bundle's OWL templates into the JS that registers them.

    Split out of :class:`AssetsBundle` (mirroring :class:`CssPipeline`): parse
    into primary/extension blocks (:meth:`xml`), render the ``registerTemplate``
    calls (:meth:`generate_xml_bundle`), and wrap for delivery — legacy IIFE
    (:meth:`legacy_template_iife`) or ESM ``<script type="module">``
    (:meth:`generate_esm_template_bundle`).
    """

    _TEMPLATE_MODULE = "@web/core/templates"
    _TEMPLATE_REGISTRARS = (
        "checkPrimaryTemplateParents, registerTemplate, registerTemplateExtension"
    )

    def __init__(self, bundle: AssetsBundle) -> None:
        self._bundle = bundle

    def xml(self) -> list[XMLBlock]:
        """Split the bundle's templates into ordered "templates"/"extensions" blocks.

        A parentless or ``t-inherit-mode="primary"`` template goes in a
        "templates" block; a ``t-inherit-mode="extension"`` one in an
        "extensions" block. Reads ``t-name``, ``t-inherit`` and
        ``t-inherit-mode``.
        """
        bundle = self._bundle
        blocks = []
        block = None
        for asset in bundle.templates:
            for template_tree in asset.template_elements:
                template_name = template_tree.get("t-name")
                inherit_from = template_tree.get("t-inherit")
                inherit_mode = None
                if inherit_from:
                    inherit_mode = template_tree.get("t-inherit-mode", "primary")
                    if inherit_mode not in {"primary", "extension"}:
                        addon = asset.url.split("/")[1] if asset.url else asset.name
                        raise asset._error(
                            bundle.env._(
                                'Invalid inherit mode. Module "%(module)s" and template name "%(template_name)s"',
                                module=addon,
                                template_name=template_name,
                            )
                        )
                if inherit_mode == "extension":
                    if block is None or block["type"] != "extensions":
                        block = {
                            "type": "extensions",
                            "extensions": {},
                        }
                        blocks.append(block)
                    block["extensions"].setdefault(inherit_from, []).append(
                        (template_tree, asset.url)
                    )
                elif template_name:
                    if block is None or block["type"] != "templates":
                        block = {"type": "templates", "templates": []}
                        blocks.append(block)
                    block["templates"].append((template_tree, asset.url, inherit_from))
                else:
                    raise asset._error(bundle.env._("Template name is missing."))
        return blocks

    def generate_xml_bundle(self) -> str:
        """Render the JS that registers this bundle's XML templates at runtime."""
        content = []
        blocks = []
        try:
            blocks = self.xml()
        except XMLAssetError as e:
            content.append(f"throw new Error({json.dumps(str(e))});")

        def get_template(element: etree._Element) -> str:
            element = deepcopy(element)
            element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            string = etree.tostring(element, encoding="unicode")
            string = (
                string.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            )
            return re.sub(r"(?i)</script", r"<\\/script", string)

        names = OrderedSet()
        primary_parents = OrderedSet()
        extension_parents = OrderedSet()
        for block in blocks:
            if block["type"] == "templates":
                for element, url, inherit_from in block["templates"]:
                    if inherit_from:
                        primary_parents.add(inherit_from)
                    name = element.get("t-name")
                    names.add(name)
                    template = get_template(element)
                    content.append(
                        f"registerTemplate({json.dumps(name)}, {json.dumps(url)}, `{template}`);"
                    )
            else:
                for inherit_from, elements in block["extensions"].items():
                    extension_parents.add(inherit_from)
                    for element, url in elements:
                        template = get_template(element)
                        content.append(
                            f"registerTemplateExtension({json.dumps(inherit_from)}, {json.dumps(url)}, `{template}`);"
                        )

        missing_names_for_primary = primary_parents - names
        if missing_names_for_primary:
            content.append(
                f"checkPrimaryTemplateParents({json.dumps(list(missing_names_for_primary))});"
            )
        missing_names_for_extension = extension_parents - names
        if missing_names_for_extension:
            missing_msg = "Missing (extension) parent templates: " + ", ".join(
                missing_names_for_extension
            )
            content.append(f"console.error({json.dumps(missing_msg)});")

        return "\n".join(content)

    def generate_esm_template_bundle(self, use_import=True) -> str:
        """Generate an ESM template bundle for ``<script type="module">``.

        *use_import* True (debug): native ``import`` from
        ``@web/core/templates`` via the import map. False (production esbuild):
        ``odoo.loader.modules.get()`` instead, since esbuild internalizes the
        module and an ``import`` would create a second copy with its own
        registry (the esbuild bundle must run first, registerNativeModules).
        """
        bundle = self._bundle
        if not bundle.templates:
            return ""
        templates = self.generate_xml_bundle()
        if not templates:
            return ""
        if use_import:
            header = (
                f"import {{ {self._TEMPLATE_REGISTRARS} }} "
                f'from "{self._TEMPLATE_MODULE}";\n'
            )
        else:
            header = (
                f"const {{ {self._TEMPLATE_REGISTRARS} }} = "
                f'odoo.loader.modules.get("{self._TEMPLATE_MODULE}");\n'
            )
        return f"{header}/* {bundle.name} */\n{templates}\n"

    def legacy_template_iife(self) -> str:
        """Wrap the registered templates in the classic-bundle IIFE.

        Non-ESM bundles ship templates inside the concatenated ``.min.js`` via
        this wrapper; ESM bundles use :meth:`generate_esm_template_bundle`.

        Written unindented rather than ``textwrap.dedent``-ed: the interpolated
        ``registerTemplate(...)`` lines start at column 0, so they used to drag
        the computed common prefix to ``""`` and turn the dedent into a no-op
        that shipped the literal's own indentation instead.
        """
        templates = self.generate_xml_bundle()
        return (
            "\n\n"
            "/*******************************************\n"
            "*  Templates                               *\n"
            "*******************************************/\n\n"
            "(function() {\n"
            '    "use strict";\n'
            f"    const {{ {self._TEMPLATE_REGISTRARS} }} = "
            f'odoo.loader.modules.get("{self._TEMPLATE_MODULE}");\n'
            f"    /* {self._bundle.name} */\n"
            f"{templates}\n"
            "})();\n"
        )
