__all__ = [
    "ANY_UNIQUE",
    "ASSET_EXTENSIONS",
    "DOTTED_ASSET_EXTENSIONS",
    "EXTENSION_TO_WEB_MIMETYPES",
    "EXTERNAL_ASSET",
    "SCRIPT_EXTENSIONS",
    "STYLE_EXTENSIONS",
    "TEMPLATE_EXTENSIONS",
    "ExternalAsset",
]

SCRIPT_EXTENSIONS = ("js",)
STYLE_EXTENSIONS = ("css", "scss", "sass")
TEMPLATE_EXTENSIONS = ("xml",)
ASSET_EXTENSIONS = SCRIPT_EXTENSIONS + STYLE_EXTENSIONS + TEMPLATE_EXTENSIONS


class ExternalAsset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "EXTERNAL_ASSET"


EXTERNAL_ASSET = ExternalAsset()
"""Marks a resolved asset as an external URL, served as-is instead of bundled."""

ANY_UNIQUE = "_" * 7
"""Sentinel placeholder for unique asset hashes in URLs."""

DOTTED_ASSET_EXTENSIONS = tuple(f".{ext}" for ext in ASSET_EXTENSIONS)
"""Asset extensions with leading dots (for URL/path matching)."""

EXTENSION_TO_WEB_MIMETYPES = {
    ".css": "text/css",
    ".scss": "text/scss",
    ".js": "text/javascript",
    ".xml": "text/xml",
    ".csv": "text/csv",
    ".html": "text/html",
}
"""Mapping of web file extensions to MIME types."""
