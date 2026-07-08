"""Asset bundle pipeline — package split of the former single module.

Public API and import path (``odoo.addons.base.models.assetsbundle``) are
unchanged: every name external code imports is re-exported here, so existing
imports and ``mute_logger``/``patch`` targets that reference the package keep
working. The single 2.8k-line module was split by responsibility:

* ``common``       — logging, error taxonomy, TypedDicts, CLI-pipe + CSS-scan helpers
* ``assets``       — WebAsset and its JS/CSS/XML/SCSS leaf subclasses
* ``store``        — AssetAttachmentStore (raw-SQL attachment persistence)
* ``css_pipeline`` — CssPipeline + the rtlcss subprocess helpers
* ``xml_pipeline`` — XmlTemplatePipeline (OWL template rendering)
* ``js_pipeline``  — JsPipeline (legacy JS concatenation / sourcemap body)
* ``bundle``       — AssetsBundle, the orchestrator

Only the CONSUMED surface is re-exported (names with importers outside the
package); pipeline internals are imported from their defining module.

Note: module-level functions patched by string path in tests are patched at
their real home (``...assetsbundle.css_pipeline._check_rtlcss``,
``...assetsbundle.assets.minify_js``) — patch where the name is looked up.

The ``ODOO_EXTERNAL_LIBS`` / esbuild cross-check that used to run here at
import time now runs lazily on first bundle construction — see
``bundle._check_external_libs_once``.
"""

# Re-exported from their origin so tests importing them THROUGH this module
# (the historical surface) keep resolving.
from odoo.libs.constants import ANY_UNIQUE
from odoo.tools.assets.esm_graph import (
    _cached_module_classification,
    _parse_odoo_module_header,
    is_odoo_module,
)

from .assets import (
    JavascriptAsset,
    PreprocessedCSS,
    ScssStylesheetAsset,
    StylesheetAsset,
    WebAsset,
    XMLAsset,
)
from .bundle import AssetsBundle
from .common import (
    _rewrite_css_outside_strings,
    AssetError,
    AssetNotFoundError,
    BundleFileSpec,
    CompileError,
    XMLAssetError,
)
from .css_pipeline import CssPipeline, _check_rtlcss
from .store import AssetAttachmentStore
from .xml_pipeline import XmlTemplatePipeline
