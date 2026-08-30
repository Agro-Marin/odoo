import contextlib

from odoo.addons.document_extract.tools import extractors as registry


@contextlib.contextmanager
def only(extractor):
    saved = dict(registry._EXTRACTORS)
    registry._EXTRACTORS.clear()
    try:
        registry.register_extractor(extractor)
        yield
    finally:
        registry._EXTRACTORS.clear()
        registry._EXTRACTORS.update(saved)
