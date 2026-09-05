{
    "name": "Document Extraction - Local OCR",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Read a scan locally, with no key and no per-page charge",
    "description": """
Document Extraction - Local OCR
===============================

Registers a local OCR engine as a reader of the document layer, so a document
that has pages but no characters gets text anyway.

It is not a strategy and extracts no fields. OCR turns pixels into characters,
which is what a reader is for, and putting it there means every
strategy that needs text gains scanned documents without knowing OCR happened.

It registers at ``EXPENSIVE`` and carries no gate of its own. Two conditions
decide whether it runs, both enforced by the document layer: the caller raised
that document's reader ceiling, and every cheaper reader answered nothing. So a
PDF with a text layer never renders a page, and a scan does.

RapidOCR: PaddleOCR's PP-OCR models exported to ONNX. Apache-2.0, ~32 MB of
weights inside the wheel, CPU-only, no download at first use and no network at
inference. Measured at 2.4 s for a rendered page, reading a CFE bill's service
number, tariff, meter number, period and total exactly.

The engine, and what installing it costs
----------------------------------------
``rapidocr`` plus ``onnxruntime``, both declared and both imported at module
level. Installing this module without them fails, by name, on the install path;
it does not install and then read nothing. A scan that silently yields no text
looks exactly like a blank page to every strategy downstream, which is a worse
outcome than a refused install and a harder one to attribute. The package this used to name,
``rapidocr-onnxruntime``, is the same project under its old name and is frozen:
every release after the pinned 1.2.3 -- 1.3.24 and 1.4.4 -- caps at
``python_requires <3.13``, so on 3.14 the old name cannot move at all. ``rapidocr``
3.x is its continuation, ships PP-OCRv6 rather than v4, and declares
``<4``.

It no longer bundles an inference backend, which is why ``onnxruntime`` is now
named here rather than arriving underneath: ``rapidocr`` exposes no extras, so a
declaration that does not name it installs a package that raises
``ImportError: onnxruntime is not installed`` on first use instead of at install
time.

Nine packages and about 120 MB, against five and 105 MB before -- the four added
are ``omegaconf``, its ``antlr4-python3-runtime``, ``tqdm`` and ``colorlog``, all
small. Measured rather than assumed, it still upgrades nothing: the ``numpy``,
``scipy``, ``shapely``, ``pyproj``, ``Pillow``, ``PyYAML``, ``six`` and
``requests`` a workspace already has all satisfy it unchanged. Nothing another
module depends on moves to make room for it, which is what makes declaring it
honest rather than imposing.

What it does not make work
--------------------------
OCR text is not a PDF's text layer with the pixels in between. Measured on one
page: a bill printing ``TARIFA: 01   NO. MEDIDOR: 599CMC`` side by side yields
one line from the text layer and two from OCR. Every value is present; the line
structure is not the same.

So a regex template anchored to a line -- ``cfe_pdf`` is one -- may miss on a
scan what it matches on a digital PDF, and must not be assumed to work merely
because text now exists. A language model reading that text does not care where
the lines fall, which is why ``llm_text`` is what this mainly unlocks: a scan
that previously needed a vision model can now be read by any model at all.
    """,
    "author": "AgroMarin",
    "website": "https://agromarin.com",
    "license": "LGPL-3",
    "depends": ["document_extract"],
    "external_dependencies": {"python": ["rapidocr", "onnxruntime"]},
}
