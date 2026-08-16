# ADR-0012: Attachment storage layers (object store, key policy, delivery)

- **Status:** Withdrawn
- **Date:** 2026-07-30

## Context

Attachment content had two independent storage axes and no layer beneath them:

- `AttachmentStorage` (`base/models/ir_attachment_storage.py`) — content-addressed
  storage under a `store_fname` key, bytes served **by** Odoo.
- `CloudProvider` (`cloud_storage/models/cloud_provider.py`) — a blob addressed by
  `url`, bytes exchanged **directly** between client and store.

Neither is an object store. `AttachmentStorage` fuses vendor I/O with a key policy
and a delivery decision; `CloudProvider` has no `get` or `put` **at all** — it mints
URLs and signs them. So a module needing plain bucket I/O had nowhere to get it, and
wrote its own client. At the time of this ADR that had happened twice for one
service: `cloud_storage_s3` and `documents_cloud` each carried a boto3 stack, a
per-worker client cache keyed on the same signature, its own credential category and
its own bucket parameter.

The costs were not theoretical:

- With two stacks unaware of each other, the hybrid mirror in `cloud_storage_s3`
  treated content already held in `documents_cloud`'s bucket as local, downloaded
  every byte of it and re-uploaded it into its own bucket, under a key that was not
  an object key but the other backend's whole store URI.
- Nothing could enumerate any bucket, so nothing could compare storage against the
  database. Content the database referenced and the store no longer had was answered
  with `b""` and a log line: data loss served as a successful zero-byte download.
- `cloud_storage` depended on `mail`, because a controller patching the chatter
  upload route lived inside it. Anything wanting a bucket had to drag messaging in
  to get one.

## Decision

Four layers, each with one responsibility, and a rule for which to extend.

### 1. `ObjectStore` — opaque key/value blobs (`base/models/object_store.py`)

`put`/`get`/`open`/`head`/`delete`/`list`/`copy`/`presign_get`. No key policy, no
delivery policy; a store knows only opaque keys.

`capabilities()` is part of the contract, not an assumption: stores differ on
presigning and enumeration, and a caller must degrade rather than raise
`AttributeError` from inside a cron. `FilesystemObjectStore` puts the local
filestore behind the same interface, which is what makes reconciliation a general
facility rather than a cloud feature.

`list` must yield every object in range until exhausted or `limit` is reached. A
short page is read as "end of store"; truncating for any other reason turns healthy
rows into false `missing` findings.

### 2. Key policy — `KeyedObjectStorage` over a store

Content addressing, dedup on write, reference-checked delete and redirect-on-download
are generic. A keyed backend is now this class plus a store name.

**`key_scheme` must equal `store_name`.** When they diverge, nothing can map a store
back to the keys it holds and content in that backend becomes unreconcilable. This
is stated as a rule because it happened: `documents_cloud` wrote `s3://` keys into a
store named `s3_documents`, and the keyed half of Documents was invisible to the only
thing that detects missing content.

**The store receives a bare key.** The scheme identifies the backend in the database
and is never handed to the store, or every object lands under a pseudo-folder named
after the scheme.

### 3. Delivery — how bytes reach the client (`odoo/http/stream.py`)

`Stream.delivery_mode()` names three cases in worker-cost terms:

| mode | meaning | worker |
|---|---|---|
| `redirect` | client fetches from the store | released |
| `offloaded` | `x_sendfile` hands the file to the frontend | released |
| `worker` | this worker carries every byte | **held until the client has them all** |

`frontend_path()` is the single place the `x_sendfile` rule is applied, so a
measurement cannot recompute it and drift from the rule actually in force.

This layer, not throughput, is what the storage choice turns on. Measured on this
fork (MinIO over loopback, medians): reading 4 MB from the filestore costs 1.14 ms
and signing a URL costs 0.149 ms — while a 10 Mbit/s client accepting the same 4 MB
occupies a worker for **3.2 seconds** if the worker streams it. Occupancy dominates
obtaining by four to five orders of magnitude, so:

- `x_sendfile` puts local storage in the same released class as a redirect, and is
  the highest-impact setting available. It requires the matching frontend location;
  enabling it without one breaks every download.
- Serving remote content **through** the worker is the worst option: it pays the
  store's latency *and* holds a worker. Prefer a redirect whenever the store can
  presign.

### 4. Reconciliation — `attachment_reconcile`

A windowed set difference between what a store holds and what the database
references. A page of objects spans `(after, upto]` and the database is queried over
that **same** range, so within the window both sides are complete and a deletion
decision is defensible; anything outside is left unclassified rather than assumed
absent.

Which column carries identity is the `scope`. `store_fname` qualifies; so does a
`url` column, provided every row in scope shares one constant prefix — with the
prefix fixed, lexicographic order on the column *is* order on the key. A column
mixing prefixes does not qualify at all.

Three safety rules, each from a failure that occurred:

- **Repair is a separate call that re-reads the database.** A scan is a snapshot, and
  a client-direct upload key is handed to the browser *before* any row exists, so an
  object can be correctly classified as unreferenced and then legitimately referenced
  before the sweep acts.
- **What `missing` means depends on the scope, and it decides the repair.** In the
  content scope it is lost data and the row must be flagged; in a mirror scope it is
  a lost *backup* while the content is still readable, and flagging would report
  healthy attachments as damaged.
- **Collection refuses when a run recognised none of what it scanned**, above a
  threshold, because that is the signature of an index reading the wrong column —
  which empties a bucket. Below the threshold the signal says nothing, since a sweep
  hunting abandoned uploads legitimately sees nothing else.

### Measurement — `object_store_metrics` (optional)

A decorator (`MeasuredObjectStore`) rather than timing inside each backend, so no
store contains measurement code and it is removed by unregistering an observer.
`worker_bytes` is recorded separately from `total_bytes` because that is the column
the delivery decision turns on. The observer only appends to a buffer, flushed after
commit: an instrument that writes rows inside the operation it times measures itself.

## Consequences

- A vendor adapter is written once and reused. `object_store_s3` carries the S3
  client; `cloud_storage_s3` (policy: mirror, browser-direct upload) and
  `documents_cloud` (policy: byte-path strategies) both consume it and keep their
  own buckets. Instances sharing an account and region share one client, so a second
  bucket costs a name and three config hooks, not a stack.
- `cloud_storage` no longer depends on `mail`; the chatter integration is
  `cloud_storage_mail`. A module wanting a bucket does not acquire messaging.
- Storage became verifiable. The filestore, keyed cloud content, client-fetched
  Documents content and the hybrid mirror are all reconcilable through one engine.
- Adding a backend that cannot enumerate is allowed and honest: it declares no
  `CAP_LIST` and reconciliation refuses it with a clear error rather than
  misbehaving.

### Deliberately not done

- **`AttachmentStorage` and `CloudProvider` are not collapsed into `ObjectStore`.**
  The layering makes it possible, but `FileStorage` has a GC checklist and a `_file_*`
  override surface several suites patch directly, and `DbStorage` has no store at
  all. `CloudProvider` cannot be collapsed while two of its three implementations
  (Azure, Google) do no object I/O whatsoever — they sign URLs and delete by REST,
  their SDKs are absent from this environment, and an adapter for them would be new,
  unexercised code. Three registries remain; extend `ObjectStore` for anything new.
- **Delivery is not yet a stored column.** It is derived per request. Making it a
  column would let a row's delivery be chosen and migrated deliberately, and is the
  natural next step once identity lives in one column for every backend.
- **Eager blob cleanup on `unlink` is kept** and is *not* replaced by reconciliation.
  Reconciliation is periodic; deleting content only at the next sweep leaves deleted
  attachments' bytes in a bucket, which is a storage-cost and retention problem.
  Both mechanisms are wanted: eager for the normal case, periodic for what it misses.

## Amendments

Append-only. An amendment corrects what this record says *about the repo*; it
never edits the decision above.

### 2026-08-07 — Status corrected to `Proposed`; none of this is built

This ADR was committed as `Accepted` and written in the past tense ("Storage
became verifiable", "`cloud_storage` no longer depends on `mail`"). None of the
Decision has been implemented in this repository. Searched at the time of this
amendment: every ref in `odoo`, `enterprise`, `agromarin` and `design-themes`
(`git ls-tree` per ref), plus the whole filesystem. Zero occurrences of
`ObjectStore`, `KeyedObjectStorage`, `attachment_reconcile`, `object_store_s3`,
`object_store_metrics`, `cloud_storage_s3`, `documents_cloud` or
`cloud_storage_mail`. The commit that added this file (`50d1487d710`) changed
three files, all of them documentation.

What is verifiably still true is the **Context**, which diagnoses this tree
accurately: `AttachmentStorage` does fuse vendor I/O (`read`/`write`/`delete`),
key policy (`owns_key`, `backend_for_key`) and delivery (`to_stream`) in one
199-line class; there is no enumeration primitive anywhere beneath it; and
`cloud_storage` does depend on `mail` because `CloudAttachmentController`
subclasses `mail`'s `AttachmentController` to patch `mail_attachment_upload`.

Two references in the Decision do not correspond to this tree even as a
description of the "before" state, and are recorded here rather than edited
above:

- **`cloud_storage/models/cloud_provider.py` does not exist.** URL minting lives
  on `ir.attachment` as `_generate_cloud_storage_url` in
  `cloud_storage/models/ir_attachment.py`. The `CloudProvider` registry the
  Context describes is a design for what that logic would become.
- **`Stream.delivery_mode()` and `frontend_path()` do not exist.**
  `odoo/http/stream.py` resolves, which is why the path check passed for a year;
  the methods are proposed, not present. `x_sendfile` is applied inline at
  `odoo/http/stream.py:171-179`.

The layering this ADR proposes is not withdrawn — it is a sound response to a
real, still-present diagnosis. It is reclassified so that a reader can tell
which half is the tree and which half is the plan. Promote to `Accepted` when
the Decision lands, at which point `test_adr_coherence.py` will begin requiring
every name above to exist.

### 2026-08-14 — Withdrawn: the work is not intended

Confirmed on 2026-08-14 that the object-store layering this record proposes will
not be built. The status is `Withdrawn` rather than the file deleted, because the
argument is the reason to keep it: a later reader who proposes the same four
layers should find the case that was already made — including what it would cost
and what it deliberately does not do — instead of re-deriving it.

Two things outlive the proposal and are recorded so they are not lost with it.

The **Context is a diagnosis of this tree, and it stayed accurate**: attachment
storage does fuse vendor I/O, key policy and a delivery decision in one class;
there is no enumeration primitive beneath it, so nothing can compare a store
against the database; and `cloud_storage` does depend on `mail` because a
controller patching the chatter upload route lives inside it. None of that is
withdrawn by withdrawing the remedy.

The **delivery measurement is the part worth carrying forward**: worker occupancy
dominates obtaining by four to five orders of magnitude, which is why `x_sendfile`
and a redirect belong in the same class and why serving remote content through a
worker is the worst of the three options. That conclusion does not depend on any
of the layering above it.

`doc/architecture/data.md` states the dual-storage seam directly now, rather than
pointing at this record for it, and `doc/architecture/risks.md` R5 is closed by
this withdrawal.
