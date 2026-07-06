from __future__ import annotations

import re
import textwrap
from typing import TYPE_CHECKING

from lxml import etree

from odoo.tools import OrderedSet
from odoo.tools.json import scriptsafe as json

if TYPE_CHECKING:
    # Typing-only sibling imports: ``bundle`` imports this module at runtime,
    # so the reverse edge stays under TYPE_CHECKING to avoid an import cycle.
    from .bundle import AssetsBundle
    from .common import XMLBlock
from .common import XMLAssetError


class XmlTemplatePipeline:
    """Render one bundle's OWL templates into the JS that registers them.

    Split out of :class:`AssetsBundle` so all template handling lives behind one
    boundary, mirroring :class:`CssPipeline` for stylesheets: parsing into
    primary/extension blocks (:meth:`xml`), rendering the ``registerTemplate``
    calls (:meth:`generate_xml_bundle`), and the two delivery wrappers — the
    legacy classic-bundle IIFE (:meth:`legacy_template_iife`) and the ESM
    ``<script type="module">`` form (:meth:`generate_esm_template_bundle`).
    ``AssetsBundle`` keeps thin façades for its public/test surface and the
    ``ir_qweb`` call sites.
    """

    # OWL template-registration API destructured from ``@web/core/templates`` by
    # the generated template bundles. Three call sites consume this exact set —
    # the legacy IIFE wrapper and both header forms of
    # ``generate_esm_template_bundle`` — so a single source keeps them from
    # drifting when a registrar is added or renamed.
    _TEMPLATE_MODULE = "@web/core/templates"
    _TEMPLATE_REGISTRARS = (
        "checkPrimaryTemplateParents, registerTemplate, registerTemplateExtension"
    )

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose templates it renders."""
        self._bundle = bundle

    def xml(self) -> list[XMLBlock]:
        """
        Create a list of blocks. A block can have one of the two types "templates" or "extensions".
        A template with no parent or template with t-inherit-mode="primary" goes in a block of type "templates".
        A template with t-inherit-mode="extension" goes in a block of type "extensions".

        Used parsed attributes:
        * `t-name`: template name
        * `t-inherit`: inherited template name.
        * 't-inherit-mode':  'primary' or 'extension'.

        :return: a list of blocks
        """
        bundle = self._bundle
        blocks = []
        block = None
        for asset in bundle.templates:
            # ``template_elements`` parses each asset's XML once and caches it
            # (see XMLAsset); a parse error surfaces as XMLAssetError at access
            # time and is handled by generate_xml_bundle's try/except.
            for template_tree in asset.template_elements:
                template_name = template_tree.get("t-name")
                inherit_from = template_tree.get("t-inherit")
                inherit_mode = None
                if inherit_from:
                    inherit_mode = template_tree.get("t-inherit-mode", "primary")
                    if inherit_mode not in {"primary", "extension"}:
                        # ``asset.name`` covers inline assets (url is None),
                        # where ``url.split`` would crash the error path.
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
                    block["extensions"].setdefault(inherit_from, [])
                    block["extensions"][inherit_from].append((template_tree, asset.url))
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
            element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            string = etree.tostring(element, encoding="unicode")
            string = (
                string.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            )
            # The rendered JS may be emitted as an INLINE
            # ``<script type="module">`` (``?debug=assets``, read-only
            # renders, satellite template nodes).  The HTML parser ends a
            # script element at the first ``</script`` (case-insensitive)
            # REGARDLESS of JS string/template-literal context, so a
            # template carrying a ``<script>`` child would truncate the
            # surrounding tag and break the page.  ``<\/script`` is an
            # identity escape inside a JS template literal, so the emitted
            # string is unchanged.
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
                    # The URL is a JS string argument, not template-literal
                    # text: json.dumps quotes/escapes it so a url containing a
                    # backtick or ``${`` cannot break out of (or interpolate
                    # into) the surrounding literal. The template body stays a
                    # backtick literal — get_template already escapes it.
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

        When *use_import* is True (debug mode), uses native ``import``
        from ``@web/core/templates`` (resolved via import map).

        When False (production esbuild), accesses the templates module
        via ``odoo.loader.modules.get()`` — this avoids a second module
        instance (esbuild internalizes @web/core/templates, so an
        ``import`` would create a separate copy with its own registry).
        The esbuild bundle must execute first (registerNativeModules).
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

        Non-ESM bundles ship their templates *inside* the concatenated
        ``.min.js`` via this wrapper; ESM bundles use
        :meth:`generate_esm_template_bundle` instead.
        """
        templates = self.generate_xml_bundle()
        return textwrap.dedent(f"""

            /*******************************************
            *  Templates                               *
            *******************************************/

            (function() {{
                "use strict";
                const {{ {self._TEMPLATE_REGISTRARS} }} = odoo.loader.modules.get("{self._TEMPLATE_MODULE}");
                /* {self._bundle.name} */
                {templates}
            }})();
        """)
