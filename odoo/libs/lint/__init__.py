"""Lint utilities — parallel file scanning via the required ``odoo_rust`` extension."""

from .scan import scan_byte_patterns, scan_regex_patterns

__all__ = ["scan_byte_patterns", "scan_regex_patterns"]
