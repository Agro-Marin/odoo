{
    "name": "Document Extraction",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "sequence": 10,
    "summary": "Format-agnostic, strategy-agnostic field extraction from documents",
    "description": """
Document Extraction
===================

One framework for reading fields out of a document, whatever the document is
and however the reading is done.

Five places in this codebase extract fields today, and each one fuses three
choices that are independent: the *format* it can read, the *strategy* it uses,
and the *schema* it produces. Fusing them is why none of them can be reused --
a new format means a new parser, a new document type means a new integration.

Separating them is the whole module.

``DocumentSource``
------------------
Where formats collapse. Holds the bytes and derives ``text``, ``images``,
``tree``, ``data`` and ``barcodes`` on first access, each at most once. PDF,
PNG, JPEG, WebP, GIF, BMP, XML and JSON today; a format is added by teaching
one class to read it, and every strategy gains it.

Deriving once is not an optimization. A utility bill in this codebase was
measured being opened and text-extracted twice in one dispatch, and PDFs were
sent to a vision model labelled ``image/jpeg`` because the code that chose the
label had no idea what it was holding.

Schemas
-------
What a document type is supposed to yield: its fields, which are required, and
the rules that must hold between them (``subtotal + tax == total``,
``period_start <= period_end``). Localizations extend rather than fork, so a
fiscal UUID lives with the localization that knows it.

Extractors
----------
A strategy declares the document types it reads, the representations it needs,
and what it costs. The framework checks all three, so a strategy is never
handed a document it cannot read.

The cascade
-----------
Cheapest first, stopping when the schema is **satisfied** -- required fields
present *and* consistency rules holding. Not "a strategy returned something":
measured on a real bill, a one-word layout change dropped the subtotal, tax,
surcharge and total together while twenty-eight other fields came back and the
parser reported success. Escalation is per field, so what a free strategy read
is kept and only the gaps cost money.

``document.extract.mixin``
--------------------------
What a record gets by inheriting it: a state, the result with its provenance,
the fields nobody could read, a synchronous and a queued way to run, and a
record of every correction a person makes afterwards. A consumer declares its
schema and a field mapping, and overrides one hook when filling is more than a
mapping.

``partial`` is a state rather than an error, because a document that yields
nine required fields of eleven is worth more than an exception, and the two are
named so a person can be pointed at them.

Queued extraction runs on ``ir.job``: its own transaction, its own retries,
``identity_key`` so a sweep cannot queue a document twice, and ``_defer()``
available to a strategy that has to wait on a service rather than fail.

``ir.attachment`` inherits the mixin here, as the framework's own consumer and
its honest first test: a record whose whole content is the document, with no
business fields to fill. Anything the mixin needs that an attachment cannot
give would mean the mixin is wrong.

The strategies -- structured parsers, templates, Odoo's own extraction service,
and generative models -- arrive as separate modules, each registering itself.
    """,
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": ["data/ir_job_channel.xml"],
    "external_dependencies": {"python": ["pymupdf"]},
    "installable": True,
}
