from .ai_extractors import LlmTextExtractor, LlmVisionExtractor
from odoo.addons.document_extract.tools import register_extractor

register_extractor(LlmTextExtractor())
register_extractor(LlmVisionExtractor())
