import logging
from typing import TYPE_CHECKING

from odoo.libs.asset_log import log_event
from odoo.libs.profiling.sourcemap_generator import SourceMapGenerator
from odoo.tools.assets.esm_graph import (
    has_module_syntax,
)
from odoo.tools.json import scriptsafe as json

if TYPE_CHECKING:
    # ``bundle`` imports this module at runtime; keep the reverse edge under
    # TYPE_CHECKING to avoid an import cycle.
    from .bundle import AssetsBundle
from .assets import JavascriptAsset
from .common import _bundle_log


class JsPipeline:
    """Assemble one bundle's JavaScript content for the legacy concatenated bundle.

    Split out of :class:`AssetsBundle` so JS content generation (module-syntax
    guard, production concatenation, debug sourcemap body) lives behind one
    boundary, mirroring :class:`CssPipeline`. Attachment persistence (the ``js``
    / ``js.map`` records) stays on :class:`AssetsBundle`.
    """

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose JavaScript it assembles."""
        self._bundle = bundle

    def _module_syntax_error_stub(self, asset: JavascriptAsset) -> str | None:
        """Return a ``console.error`` stub when module syntax can't be concatenated.

        :param asset: legacy-routed JS asset about to be concatenated
        :return: replacement JS for the asset, or ``None`` when it is safe
        :rtype: str | None
        """
        # The legacy transpiler is gone, so ES-module syntax in the concatenated
        # classic bundle is a browser SyntaxError that takes the WHOLE bundle
        # down. Excluding the file keeps the rest working and the
        # misconfiguration loud. Detection is syntax-based on purpose: the
        # ``is_odoo_module`` routing heuristic also claims plain non-module
        # files under /static/src, valid classic scripts that must not be stubbed.
        bundle = self._bundle
        if bundle._is_esm_bundle:
            return None
        header = asset.parsed_header
        if header and header["ignore"]:
            # ``@odoo-module ignore`` is an explicit opt-out: the author
            # asserts the file is classic-script safe.
            return None
        if not header and not has_module_syntax(asset.raw_content):
            return None
        msg = (
            f"Module-syntax file {asset.url or asset.name!r} cannot be "
            f"concatenated into non-ESM bundle {bundle.name!r}; declare the "
            "bundle under the 'esm' key of its module's manifest to serve "
            "it. File skipped."
        )
        log_event(
            _bundle_log,
            logging.ERROR,
            "module_syntax_in_legacy_bundle",
            bundle=bundle.name,
            url=asset.url or "<inline>",
        )
        return f"console.error({json.dumps(msg)});"

    def minified_bundle(self, template_bundle: str) -> str:
        """Concatenated, minified JS for the production (``min.js``) bundle.

        ``template_bundle`` is the legacy template IIFE (empty for ESM bundles,
        which deliver templates separately).
        """
        content_bundle = ";\n".join(
            self._module_syntax_error_stub(asset) or asset.minify()
            for asset in self._bundle.javascripts
        )
        if template_bundle:
            # The ";" defuses ASI, like the ";\n" join above: a last file ending
            # in an unterminated expression would otherwise CALL the template
            # IIFE as its argument.
            content_bundle += ";" + template_bundle
        return content_bundle

    def sourcemap_bundle(
        self, generator: SourceMapGenerator, sourcemap_url: str, template_bundle: str
    ) -> str:
        """Build the un-minified debug JS body, populating *generator*.

        Adds a per-file source mapping to *generator* and appends the
        ``sourceMappingURL`` link. The caller owns the ``js`` / ``js.map``
        attachment I/O (and sets ``generator.file`` once the js URL is known).
        """
        content_bundle_list = []
        content_line_count = 0
        # Lines ``with_header(minimal=False)`` emits before the file body; kept
        # in sync with this offset via ``JavascriptAsset._HEADER_LINE_COUNT``.
        line_header = JavascriptAsset._HEADER_LINE_COUNT
        for asset in self._bundle.javascripts:
            stub = self._module_syntax_error_stub(asset)
            if stub:
                # Excluded from the sourcemap too — the stub replaces the
                # file body, so mapped positions would be meaningless.
                content_bundle_list.append(stub)
                content_line_count += stub.count("\n") + 1
                continue
            generator.add_source(
                asset.url,
                asset.content,
                content_line_count,
                start_offset=line_header,
            )

            content_bundle_list.append(asset.with_header(asset.content, minimal=False))
            content_line_count += asset.content.count("\n") + 1 + line_header

        content_bundle = ";\n".join(content_bundle_list)
        if template_bundle:
            # ";" defuses ASI — see ``minified_bundle``.
            content_bundle += ";" + template_bundle

        content_bundle += "\n\n//# sourceMappingURL=" + sourcemap_url
        return content_bundle
