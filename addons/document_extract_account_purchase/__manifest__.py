{
    "name": "Vendor Bill Purchase Order Matching from Extraction",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "summary": "Match a read purchase order reference to its order",
    "description": """
Vendor Bill Purchase Order Matching from Extraction
===================================================

Teaches the ``invoice`` schema that a vendor bill may print the purchase order
it answers, and hands whatever is read to the matching core already performs on
``invoice_origin``.

Replaces ``account_invoice_extract_purchase``, which did the same against the
IAP extraction service. What does not come across is that module's
``_get_user_infos``: it derived a regex from the purchase order sequence and
sent it to the remote reader as a hint about what a reference looks like. A
cascade of local extractors has nobody to hint to -- a structured source states
the reference or it does not, and a generative extractor is told the field
exists by the schema. The regex is not lost so much as it has no addressee.

Matching is core's, not this module's
-------------------------------------
``_find_and_set_purchase_orders`` decides between a total match, a reference
match and a subset, and it is the same routine that runs when a person types a
reference into ``invoice_origin``. A bill matched from a read reference and a
bill matched from a typed one therefore take the same path and go wrong in the
same way, which is the point: one matching behaviour to understand.

Only an empty bill is touched. A bill that already carries lines has been
worked on by somebody, and pulling an order's lines underneath that is how an
extraction turns into a correction nobody asked for.
    """,
    "author": "AgroMarin",
    "website": "https://agromarin.com",
    "license": "LGPL-3",
    "depends": [
        "document_extract_account",
        "purchase",
    ],
}
