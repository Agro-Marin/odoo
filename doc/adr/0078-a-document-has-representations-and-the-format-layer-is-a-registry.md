# ADR-0078: A document has representations, and the format layer is a registry

- **Status:** Accepted
- **Date:** 2026-08-29

## Context

Reading an external document into records is one cycle, and this workspace
implements it eight times, in about 21,000 lines. The full census — which of the
nine pipeline stages each of the eight implements, and how — is written up in the
AgroMarin knowledge vault under research, dated 2026-08-29, as the document
ingestion census. The figures below are the part of it this decision rests on.

The eight differ in the stages that carry business meaning — where the human sits
relative to the write, whether one file yields many records or one document fills
one — and those differences are real. What they duplicate is the part with no
business meaning at all: deciding what a stream of bytes is, and turning it into
something a strategy can read.

**Five independent answers to "what are these bytes":**

```
base_import            MIMETYPE_TO_READER + EXTENSION_TO_READER
attachment_indexation  _MIMETYPE_TO_FTYPE + FTYPES
enterprise/ai          TABULAR_FILE_TYPES
document_extract       hand-rolled magic bytes + _IMAGE/_XML/_JSON_MIMETYPES
account                mixin.account.document.import._get_import_file_type
```

Only two called `odoo.libs.filesystem.guess_mimetype`, which is libmagic-backed
and already in `libs/`. `document_extract`'s hand-rolled sniffer answered
`application/octet-stream` for a CSV and for an XLSX, and `provides()` then
answered False for every representation — silently. `enterprise/ai`'s
`TABULAR_FILE_TYPES` is `base_import.MIMETYPE_TO_READER`'s key set, retyped.

**Five independent encoding stories, two of them broken.** `base_import` had a
chardet streaming detector with BOM handling and a measured 249x fix;
`document_extract` had `errors="replace"`, so a latin-1 CSV read as `Caf�`;
`account_bank_statement_import_qif` called bare `bytes.decode()` at three sites,
which raised `UnicodeDecodeError` on any QIF whose payee carried an accent — most
non-English exports. `l10n_se_sie4_import` hardcoded `try UTF-8 / except
ISO-8859-1`, and `agromarin`'s BBVA reader carried a fallback chain because
chardet can name a codec Python cannot load.

**Six registries, all different.** A closed dict keyed by extension; a closed dict
keyed by mimetype; a closed list; `super()` chaining (`_get_edi_decoder`, 21
implementors; `_parse_bank_statement_file`, 8); an `AbstractModel` scanned out of
`env.registry`; and one plain-Python registry with cost and prerequisites.

None of this could be shared, because there was nowhere in the tree to put it.
`base_import`'s own manifest has promised the missing thing since it was written
— *"so users and partners can build their own front-end to import from other file
formats (e.g. OpenDocument files)"* — and ODS is hard-coded into the closed dict
that makes it impossible.

## Decision

**`odoo/odoo/libs/documents/` is the one place that answers what bytes are and
turns them into representations.** It holds `guess` (mimetype and encoding),
`coerce` (the values a document prints), and — the substance of this record —
`document` and `readers`.

**A format is registered, never dispatched from a literal.** A reader declares
the mimetypes it accepts and the representation it yields, and registers itself;
`get_readers` is the only dispatch. The six registries collapse to this one,
which is the only one that already declared cost and prerequisites.

**A document has representations, derived at most once and lazily:** `rows`,
`text`, `tree`, `data`, `images`, `barcodes`. `rows` is the load-bearing
addition. Once a spreadsheet is a representation like any other, `base_import`
stops being a format layer and becomes what it always was — a mapping UI over
rows — and every strategy that can read rows gains every tabular format.

**A reader registers from the layer that owns its dependency.** `libs/documents`
holds the protocol, the registry and the readers that need nothing above `libs`.
Anything else registers from where its dependency lives:

| Reader | Registers from | Because |
|---|---|---|
| csv, xml, json, zip members | `libs/documents` | stdlib and lxml only |
| xls, xlsx, ods | `base_import` | xlrd / openpyxl / odf are optional |
| pdf text, images, page count | `document_extract` | pymupdf is that module's dep |
| pdf embedded files | `odoo/tools/documents.py` | needs `odoo.tools.pdf` |
| ocr text | `document_extract_ocr` | opt-in, costs real time |
| barcodes | `document_extract_barcode` | zxing-cpp |

That last split is not a workaround for the layer rule; it is the rule producing
the right answer. `libs-is-dependency-free` (ADR-0004) forbids `libs/` from
reaching `odoo.tools.pdf`, and an open registry is exactly what lets the reader
live where its dependency does. `document_extract` already worked this way for
OCR (`register_text_reader`, implemented in an addon); this generalises it.

**Addon code imports the area, never a submodule of it.** `from odoo.libs.documents
import to_float`, not `from odoo.libs.documents.coerce import to_float`.

## Alternatives considered

**Put it in `odoo/tools/`.** Rejected. Identifying bytes, decoding text and
parsing a printed number are Odoo-agnostic: no ORM, no environment, no record.
`doc/architecture/module.md` reserves `libs/` for exactly that, and ADR-0075
keeps `tools/` below the serving tier for a different reason that does not apply
here. Only the PDF-embedded-file reader is Odoo-coupled, and it is the one thing
that stays in `tools/`.

**Put it in `document_extract` and have `base_import` depend on it.** Rejected.
`base_import` is `auto_install` and upstream; `document_extract` declares
`pymupdf`. That direction gives every Odoo installation a PDF stack it did not
ask for, to obtain an encoding detector.

**Share only the detector and keep the dispatch literals.** Rejected. The
literals are the reason a format cannot be added from outside the module that
owns them, which is the promise `base_import`'s manifest has been making and
failing to keep. Sharing detection without opening dispatch fixes the smaller
half and leaves the stated defect.

**Merge `base_import` and `document_extract`.** Rejected on the census: they are
two cycles, not one. One creates records that did not exist from a file a person
is looking at, deciding the mapping first; the other fills a record that exists
from a document nobody has read, and asks a person to check afterwards. They
share four helpers and nothing else, and a module holding both would be defined
by a category noun rather than a mechanism.

**A new registry rather than promoting the existing one.** Rejected. Six exist.
`document_extract`'s is the only plain-Python one and the only one declaring what
a strategy costs and what it needs, which is what makes cheapest-first
escalation expressible.

## Consequences

**Core does not gain a chardet dependency.** `odoo/libs/__init__.py` is a lazy
façade whose `__getattr__` imports an area on demand, and `documents` is not in
its `_EXPORTS`. Nothing loads `odoo.libs.documents` unless an addon imports it by
path, so `chardet` stays in `requirements-addons.txt` where `base_import` and
`mail` put it.

**A module under `odoo/libs/documents/` must be declared, not added.** Accidental
submodule surface across `odoo/libs` sits at its bound of 40
(`test_area_submodule_surface`), so each module of this package is named in
`DECLARED_SUBMODULE_EXPORTS`, as `filesystem` names `mimetypes`. Publishing a
submodule is an interface decision and this makes it one.

**Two contracts point in opposite directions and both hold.** The package
declares its submodules so the surface is pinned; addons may not use them, and
must import the area. `libs_facade_check` enforces the second, and it caught two
violations in this change's own first draft.

**`base_import` loses 93 lines and gains the extensibility its manifest
promised.** `document_extract` gains rows, unwrapping, coercion and correct
identification. The other six frameworks gain the floor without changing shape.

**A behaviour difference is deliberate and documented, not accidental.**
`normalize_number` stays byte-compatible with `base_import` — a space before a
currency symbol defeats separator inference there and always has — while
`to_float`, which serves a strategy reading a document with no person at a
preview, copes. Same code, two contracts.

## Enforcement

`tooling/architecture/layer_check.py`, contract `libs-is-dependency-free`
(ADR-0004): `odoo/libs/documents` imports no `odoo.*` outside `odoo.libs`.

`tooling/architecture/libs_facade_check.py`: addon code imports the area, not its
submodules. `test_libs_facade_check::TestRealTree::test_the_addon_trees_are_clean`
is the tree-wide assertion.

`odoo/libs/tests/test_area_submodule_surface.py`: every submodule this package
publishes is pinned in `DECLARED_SUBMODULE_EXPORTS`, and the accidental surface
across `odoo/libs` stays at or under its bound.

`odoo/libs/documents/tests/`: the guessing, decoding and coercion contracts,
including the two shapes that are deliberately refused rather than guessed — an
ambiguous date (`12/03/2026`) and a single-separator number (`1,200`).

A gate counting mimetype literals and bare `.decode()` calls outside
`libs/documents` is the natural next enforcement and is not yet written; until it
is, this record is what a reviewer cites.
