{
    "name": "Document Extraction - Barcodes",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Read barcodes and QR codes off a document's pages",
    "description": """
Document Extraction - Barcodes
==============================

Registers a barcode reader with the document layer, so a document's
``barcodes`` stops being empty and a strategy can declare ``needs=("barcodes",)``.

It registers at ``CHEAP``, under the default reader ceiling, on the argument
that decoding is the cheap half: rendering the page is what costs, and a caller
that asked for ``barcodes`` has already agreed to pay it. Registered any dearer,
a printed CFDI's QR would go unread on every document nobody thought to ask
about in advance.

The case this exists for is a printed CFDI. A Mexican invoice's QR encodes the
SAT verification URL, which carries the fiscal UUID, both RFCs and the total --
signed data, printed. On a scan, where no XML survives, those four values can
therefore be had exactly rather than read by an OCR engine or guessed by a
model. Verified at 150 and 200 dpi: a QR stamped in a page corner survives
rendering and decodes whole.

``zxing-cpp``, declared: one wheel with the decoder compiled into it and no
transitive dependencies. Nothing in a shared environment moves to satisfy it, so
there is no reason to leave it optional and every reason to fail loudly rather
than read no barcodes and say nothing.

This used to read zbar via ``pyzbar``, and the claim that justified declaring
that one -- "against a ``libzbar`` that is already present" -- was not true here:
no ``libzbar`` is installed on the workspace, so ``pyzbar`` was never importable,
the reader logged "No barcode reading" and returned nothing on every page, and
the module could not install at all once its declaration was checked. A binding
is only as declarable as the system library underneath it, which is the argument
for a decoder that has no system library underneath it. Verified on this
module's own fixtures: the SAT QR decodes byte-identically raw, and still decodes
after being stamped into a PDF and rendered at both 150 and 200 dpi. It also
reads Code128, EAN-13 and Code39, and adds DataMatrix and PDF417, which libzbar
does not do.

The decoder is imported at module level and nothing is guarded. A reader that
answers "no barcodes found" because its decoder is absent is indistinguishable
from a page that carries none, and the caller has no way to tell the two apart:
the install has to be what fails. ``document_extract_ocr`` makes the same call
about a far heavier engine.
    """,
    "author": "AgroMarin",
    "website": "https://agromarin.com",
    "license": "LGPL-3",
    "depends": ["document_extract"],
    "external_dependencies": {"python": ["zxing-cpp"]},
}
