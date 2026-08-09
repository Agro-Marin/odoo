from odoo.tools.assets.constants import ANY_UNIQUE
from odoo.tools.assets.esm_graph import (
    _cached_module_classification,
    _parse_odoo_module_header,
    is_odoo_module,
)

from .assets import (
    JavascriptAsset,
    PreprocessedCSS,
    SassStylesheetAsset,
    ScssStylesheetAsset,
    StylesheetAsset,
    WebAsset,
    XMLAsset,
)
from .bundle import AssetsBundle
from .common import (
    _SCSS_STATEMENT_SPANS,
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
