"""Asset bundle pipeline — package split of the former single module.

The public import path (``odoo.addons.base.models.assetsbundle``) is unchanged:
every consumed name is re-exported here, so external imports and
``mute_logger``/``patch`` targets keep resolving. Submodules by responsibility:

* ``common``       — logging, error taxonomy, TypedDicts, CLI-pipe + CSS-scan helpers
* ``assets``       — WebAsset and its JS/CSS/XML/SCSS leaf subclasses
* ``store``        — AssetAttachmentStore (raw-SQL attachment persistence)
* ``css_pipeline`` — CssPipeline + the rtlcss subprocess helpers
* ``xml_pipeline`` — XmlTemplatePipeline (OWL template rendering)
* ``js_pipeline``  — JsPipeline (legacy JS concatenation / sourcemap body)
* ``bundle``       — AssetsBundle, the orchestrator

Gotcha: functions patched by string path in tests must be patched at their real
home (``...css_pipeline._check_rtlcss``, ``...assets.minify_js``) — patch where
the name is looked up. The ``ODOO_EXTERNAL_LIBS`` / esbuild cross-check now runs
lazily on first bundle construction (``bundle._check_external_libs_once``), not
at import time.
"""

# Re-exported through this module so tests importing the historical surface
# keep resolving.
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
