from __future__ import annotations

from odoo.libs.documents import Document

from . import readers  # noqa: F401


def document_of(attachment, **options) -> Document:
    attachment.ensure_one()
    return Document(
        attachment.raw, attachment.mimetype or "", attachment.name or "", **options
    )
