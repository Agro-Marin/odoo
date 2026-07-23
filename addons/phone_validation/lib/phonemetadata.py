# Part of Odoo. See LICENSE file for full copyright and licensing details.

import contextlib

# Re-exported for usage in phonenumbers_patch/region_*.py files.
__all__ = ["NumberFormat", "PhoneMetadata", "PhoneNumberDesc"]

with contextlib.suppress(ImportError):
    from phonenumbers.phonemetadata import NumberFormat, PhoneMetadata, PhoneNumberDesc
