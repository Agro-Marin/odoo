# ADR-0012: Attachment storage layers (object store, key policy, delivery)

- **Status:** Withdrawn
- **Date:** 2026-07-30

## Context

Attachment content had two independent storage axes and no layer beneath them:

- `AttachmentStorage` (`base/models/ir_attachment_storage.py`) —
  content-addressed storage under a `store_fname` key, bytes served **by** Odoo.
- `CloudProvider` (`cloud_storage/models/cloud_provider.py`) — a blob addressed
  by `url`, bytes exchanged **directly** between client and store.

Neither is an object store. `AttachmentStorage` fuses vendor I/O with a key
policy and a delivery decision; `CloudProvider` has no `get` or `put` at all —
it mints and signs URLs. A module needing plain bucket I/O had nowhere to get
it and wrote its own client. That had happened twice for one service:
`cloud_storage_s3` and `documents_cloud` each carried a boto3 stack, a
per-worker client cache keyed on the same signature, its own credential
category and its own bucket parameter.

Costs observed:

- The hybrid mirror in `cloud_storage_s3` treated content already held in
  `documents_cloud`'s bucket as local, downloaded every byte and re-uploaded it
  under a key that was the other backend's whole store URI.
- Nothing could enumerate a bucket, so nothing could compare storage against the
  database. Content the database referenced and the store had lost was answered
  with `b""` and a log line — data loss served as a successful zero-byte
  download.
- `cloud_storage` depended on `mail`, because a controller patching the chatter
  upload route lived inside it. Anything wanting a bucket dragged messaging in.

## Decision

Four layers, one responsibility each, and a rule for which to extend.

### 1. `ObjectStore` — opaque key/value blobs (`base/models/object_store.py`)

`put`/`get`/`open`/`head`/`delete`/`list`/`copy`/`presign_get`. No key policy,
no delivery policy; a store knows only opaque keys.

`capabilities()` is part of the contract: stores differ on presigning and
enumeration, and a caller must degrade rather than raise `AttributeError` from
inside a cron. `FilesystemObjectStore` puts the local filestore behind the same
interface, which makes reconciliation a general facility rather than a cloud
feature.

`list` must yield every object in range until exhausted or `limit` is reached. A
short page reads as end-of-store; truncating for any other reason turns healthy
rows into false `missing` findings.

### 2. Key policy — `KeyedObjectStorage` over a store

Content addressing, dedup on write, reference-checked delete and
redirect-on-download are generic. A keyed backend is this class plus a store
name.

**`key_scheme` must equal `store_name`.** Divergence makes content in that
backend unreconcilable. Stated as a rule because it happened: `documents_cloud`
wrote `s3://` keys into a store named `s3_documents`, and the keyed half of
Documents was invisible to the only thing that detects missing content.

**The store receives a bare key.** The scheme identifies the backend in the
database and is never handed to the store, or every object lands under a
pseudo-folder named after the scheme.

### 3. Delivery — how bytes reach the client (`odoo/http/stream.py`)

`Stream.delivery_mode()` names three cases in worker-cost terms:

| mode | meaning | worker |
|---|---|---|
| `redirect` | client fetches from the store | released |
| `offloaded` | `x_sendfile` hands the file to the frontend | released |
| `worker` | this worker carries every byte | **held until the client has them all** |

`frontend_path()` is the single place the `x_sendfile` rule is applied, so a
measurement cannot recompute it and drift.

Delivery, not throughput, is what the storage choice turns on. Measured on this
fork (MinIO over loopback, medians): reading 4 MB from the filestore costs
1.14 ms, signing a URL 0.149 ms, while a 10 Mbit/s client accepting the same
4 MB occupies a worker for **3.2 seconds**. Occupancy dominates obtaining by
four to five orders of magnitude, so:

- `x_sendfile` puts local storage in the same released class as a redirect, and
  is the highest-impact setting available. It needs the matching frontend
  location; enabling it without one breaks every download.
- Serving remote content **through** the worker is the worst option — it pays
  the store's latency *and* holds a worker. Prefer a redirect wherever the store
  can presign.

### 4. Reconciliation — `attachment_reconcile`

A windowed set difference between what a store holds and what the database
references. A page of objects spans `(after, upto]` and the database is queried
over the same range, so within the window both sides are complete and a deletion
decision is defensible; anything outside is left unclassified.

Which column carries identity is the `scope`. `store_fname` qualifies; a `url`
column qualifies provided every row in scope shares one constant prefix — with
the prefix fixed, lexicographic order on the column is order on the key. A
column mixing prefixes does not qualify.

Three safety rules, each from a failure that occurred:

- **Repair is a separate call that re-reads the database.** A scan is a
  snapshot, and a client-direct upload key is handed to the browser before any
  row exists, so an object can be correctly classified as unreferenced and then
  legitimately referenced before the sweep acts.
- **What `missing` means depends on the scope, and it decides the repair.** In
  the content scope it is lost data and the row must be flagged; in a mirror
  scope it is a lost backup while the content is still readable, and flagging
  would report healthy attachments as damaged.
- **Collection refuses when a run recognised none of what it scanned**, above a
  threshold — the signature of an index reading the wrong column, which empties
  a bucket. Below the threshold the signal says nothing, since a sweep hunting
  abandoned uploads legitimately sees nothing else.

### Measurement — `object_store_metrics` (optional)

A decorator (`MeasuredObjectStore`) rather than timing inside each backend, so
no store contains measurement code and it is removed by unregistering an
observer. `worker_bytes` is recorded separately from `total_bytes` because that
is the column the delivery decision turns on. The observer only appends to a
buffer, flushed after commit: an instrument that writes rows inside the
operation it times measures itself.

## Consequences

- A vendor adapter is written once and reused. `object_store_s3` carries the S3
  client; `cloud_storage_s3` (mirror, browser-direct upload) and
  `documents_cloud` (byte-path strategies) both consume it and keep their own
  buckets. Instances sharing an account and region share one client, so a second
  bucket costs a name and three config hooks.
- `cloud_storage` no longer depends on `mail`; the chatter integration is
  `cloud_storage_mail`.
- Storage becomes verifiable: filestore, keyed cloud content, client-fetched
  Documents content and the hybrid mirror all reconcile through one engine.
- A backend that cannot enumerate is allowed and honest: it declares no
  `CAP_LIST` and reconciliation refuses it with a clear error.

### Deliberately not done

- **`AttachmentStorage` and `CloudProvider` are not collapsed into
  `ObjectStore`.** `FileStorage` has a GC checklist and a `_file_*` override
  surface several suites patch directly; `DbStorage` has no store at all.
  `CloudProvider` cannot be collapsed while two of its three implementations
  (Azure, Google) do no object I/O — they sign URLs and delete by REST, their
  SDKs are absent here, and an adapter would be new, unexercised code. Three
  registries remain; extend `ObjectStore` for anything new.
- **Delivery is not a stored column.** It is derived per request. A column would
  let a row's delivery be chosen and migrated deliberately — the natural next
  step once identity lives in one column for every backend.
- **Eager blob cleanup on `unlink` is kept**, not replaced by reconciliation.
  Reconciliation is periodic; deleting only at the next sweep leaves deleted
  attachments' bytes in a bucket. Both are wanted: eager for the normal case,
  periodic for what it misses.

## Amendments

### 2026-08-07 — Status corrected to `Proposed`; none of this is built

Committed as `Accepted` and written in the past tense ("Storage became
verifiable"). None of the Decision was implemented. Searched every ref in
`odoo`, `enterprise`, `agromarin` and `design-themes` plus the whole filesystem:
zero occurrences of `ObjectStore`, `KeyedObjectStorage`, `attachment_reconcile`,
`object_store_s3`, `object_store_metrics`, `cloud_storage_s3`,
`documents_cloud` or `cloud_storage_mail`. The commit that added this file
(`50d1487d710`) changed three files, all documentation.

The **Context** is verifiably accurate about this tree: `AttachmentStorage` does
fuse vendor I/O (`read`/`write`/`delete`), key policy (`owns_key`,
`backend_for_key`) and delivery (`to_stream`) in one 199-line class; there is no
enumeration primitive beneath it; and `cloud_storage` depends on `mail` because
`CloudAttachmentController` subclasses `mail`'s `AttachmentController`.

Two Decision references do not describe this tree even as a "before" state:

- **`cloud_storage/models/cloud_provider.py` does not exist.** URL minting is
  `_generate_cloud_storage_url` on `ir.attachment` in
  `cloud_storage/models/ir_attachment.py`. The `CloudProvider` registry is a
  design for what that logic would become.
- **`Stream.delivery_mode()` and `frontend_path()` do not exist.**
  `odoo/http/stream.py` resolves, which is why the path check passed for a year;
  the methods are proposed. `x_sendfile` is applied inline at
  `odoo/http/stream.py:171-179`.

### 2026-08-14 — Withdrawn: the work is not intended

Confirmed 2026-08-14 that the layering will not be built. Withdrawn rather than
deleted, because a later reader proposing the same four layers should find the
case already made, including its costs and its exclusions.

Two things outlive the proposal.

The **Context is a diagnosis of this tree and stayed accurate**: attachment
storage fuses vendor I/O, key policy and a delivery decision in one class; no
enumeration primitive sits beneath it, so nothing can compare a store against
the database; `cloud_storage` depends on `mail` because a controller patching
the chatter upload route lives inside it. Withdrawing the remedy withdraws none
of that.

The **delivery measurement carries forward**: worker occupancy dominates
obtaining by four to five orders of magnitude, so `x_sendfile` and a redirect
belong in the same class, and serving remote content through a worker is the
worst of the three. That conclusion does not depend on the layering above it.

`doc/architecture/data.md` states the dual-storage seam directly now instead of
pointing here, and `doc/architecture/risks.md` R5 is closed by this withdrawal.
