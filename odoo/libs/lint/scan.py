"""Parallel file scanning for lint tests.

Backed by the Rust ``odoo_rust`` extension: ``scan_byte_patterns`` and
``scan_regex_patterns``.
"""

from odoo_rust import scan_byte_patterns, scan_regex_patterns

__all__ = ["scan_byte_patterns", "scan_regex_patterns"]
