from typing import Any

from pypdf import PdfReader, errors, filters, generic
from pypdf import PdfWriter as _Writer
from pypdf.generic import create_string_object

__all__ = [
    "PdfReader",
    "PdfWriter",
    "create_string_object",
    "errors",
    "filters",
    "generic",
]


class PdfWriter(_Writer):
    def add_metadata(self, infos: dict[str, Any]) -> None:
        if hasattr(self, "_info") and getattr(self, "_info", None) is None:
            self._info = generic.DictionaryObject()
        super().add_metadata(infos)
