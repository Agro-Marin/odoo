"""Helpers shared by this module's tests.

Only what is genuinely identical lives here. Each test file keeps its own
``_Stub``: the stub's ``name`` is asserted on, and the two differ in what they
return for empty values, so merging them would need a flag per difference and
lose exactly the information the tests rely on.
"""

import contextlib

from odoo.addons.document_extract.tools import extractors as registry


@contextlib.contextmanager
def only(extractor):
    """Run the block with `extractor` as the only registered strategy."""
    saved = dict(registry._EXTRACTORS)
    registry._EXTRACTORS.clear()
    try:
        registry.register_extractor(extractor)
        yield
    finally:
        registry._EXTRACTORS.clear()
        registry._EXTRACTORS.update(saved)
