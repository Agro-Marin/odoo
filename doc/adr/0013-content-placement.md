# ADR-0013: Content placement — where an attachment's bytes are, as data

- **Status:** Withdrawn
- **Date:** 2026-07-30
- **Extends:** ADR-0012 (attachment storage layers)

## Context

ADR-0012 closed by noting that delivery could not become a stored column until
identity lived in one column for every backend. The blocker is not which column
identity lives in but that there is only one of it.

`store_fname` answers "where is the content" with a single string, fusing two
independent facts: **which store** holds the bytes, as a `scheme://` prefix, and
**which key** they are under. Both costs were paid in production.

- The prefix is not part of the object key, and nothing in the type system says
  so. `documents_cloud` passed the whole `s3://b3/ab/<digest>` URI to the bucket
  as the key, so every object landed under a literal `s3:` pseudo-folder.
  ADR-0012 states the rule because the rule was broken; a rule is what you write
  when the model cannot express the constraint.
- One column admits one answer, so every feature needing a **second** copy
  invented its own columns. `cloud_storage_s3` carries `s3_blob_name` and
  `s3_mirror_pending`, readable only by that module. Reconciliation could detect
  content was gone and the mirror could restore it; neither could ask the other,
  so a content-scope repair quarantined rows whose bytes sat byte-identical in
  the bucket.

A third, quieter cost: reference counting ("is this key still used?") had to go
through `ir.attachment._search`, which silently injects `res_field = False`.
Every call site therefore needs `skip_res_field_check=True`, and forgetting it
makes binary-field attachments invisible and their content collectable. That
workaround appears in nine places across base, `cloud_storage`,
`cloud_storage_s3`, `documents_cloud` and the reconciler. **Nine copies of one
subtle precondition is not nine mistakes; it is a missing entity.**

## Decision

Make the copy the entity: `ir.content.placement`, one row per copy of an
attachment's content.

```
attachment_id  store_name  key  role  state  size  etag  verified_at
               ^^^^^^^^^^  ^^^
               separate columns — a key can never carry a scheme
```

- **`role`** — `primary` (written synchronously; what the row reads from) or
  `replica` (written after commit; exists to be restored from).
- **`state`** — `pending` / `present` / `missing` / `stale`, the vocabulary
  reconciliation already used, now stored per copy rather than flattened onto
  the attachment.

### Placements are derived, not written by callers

`_placements_sync()` runs from `create`, `write` and `_rewrite_stored_content`
and reads `store_fname`. A placement written at each call site is a placement
someone forgets — which is how the one module holding a second copy became the
only module that could find it.

### Two-phase write

A replica is created `pending` **inside** the caller's transaction, before any
upload, making the write crash-safe in both directions:

| outcome | result | who handles it |
|---|---|---|
| transaction rolls back | no row; the uploaded object is unreferenced | orphan sweep, after grace |
| commits, upload failed | row stays `pending` | replication cron retries |
| commits, upload succeeded | row is `present` | — |

`s3_mirror_pending` was a degenerate single-store version of this.

### Repair is replication reversed

`pending → present` uploads from a copy that has the bytes; `missing → present`
writes them back from a copy that has them. One operation, so one
implementation: `_restore_content_from_replica()` reads the same placements the
replication engine writes. Reconciliation calls it before quarantining, and a
read whose primary is unreadable falls back to a `present` replica rather than
answering `b""`.

### Both read paths recover, and a download prefers a redirect

`raw` and `/web/content` reach storage by different routes — `_stored_content`
and `_to_http_stream` — so closing the gap in one left the other answering `b""`
for a row the first could recover. Both fall back to a `present` replica on the
failure path only, so a healthy read pays nothing.

The download path prefers signing a URL over streaming: per ADR-0012, a redirect
releases the worker in 0.149 ms while carrying the payload holds one for
seconds. Existence is checked before signing — the primary is already known
broken, so the extra `head` is rare, and redirecting to a second missing object
spends the same worker to produce a 404.

A `url` stream is never judged empty: presigning does not fetch, so a redirect
to a missing object is indistinguishable from one to a present object. That case
belongs to reconciliation.

### Reads do not repair

`_content_from_replica` serves the bytes and returns. A read that rewrote its
own storage would mutate on a GET, and the cursor serving that GET may be
read-only. Recording the drift belongs to reconciliation, which sweeps every
store declaring `CAP_LIST` rather than only the filestore.

## Consequences

- The `s3://`-in-the-object-key bug is **unrepresentable**: store and key are
  different columns, and nothing concatenates them on the way to a store.
- A second copy is policy (`_replica_store_names()`), not a module's private
  columns. Anything that can read a placement can restore from it.
- `storage_state` becomes retractable: a scan that verified a row, or a copy
  that supplied it, can now assert health without a rewrite.
- Reference counting has somewhere correct to live. Counting placement rows on
  an indexed FK does not go through `ir.attachment._search` and cannot be got
  wrong by omitting `skip_res_field_check`.
- Creating attachments costs measurably more, and not much: A/B'd in-process
  over 400 bulk creates, placement sync adds 0.028 ms per attachment (4.5%). The
  sync is batched — one query to read existing placements, one to insert — and
  the replica path returns before any per-record query when no replica is
  configured.

### Deliberately not done

- **`store_fname` is not retired.** It stays authoritative for reads; placements
  describe where content is, not what is read. Retiring it is a data migration
  on every attachment row and wants its own decision.
- **`s3_blob_name` / `s3_mirror_pending` are not deleted.** Redundant with a
  `replica` placement, but `documents_cloud`'s migration onto
  `KeyedObjectStorage` is in flight on a separate branch. A follow-up, not a
  disagreement.
- **The `skip_res_field_check` call sites are not migrated.** Counting
  placements instead of searching attachments is safe only if placements are
  complete for every row, and these sites gate *deletion of content*. Being
  wrong there costs data, not a retry.

  The caution was warranted: three write paths — `copy()`,
  `_set_attachment_data` and the streamed upload behind `_create_from_stream` —
  reached `store_fname` through `super().write()` and produced rows referencing
  an object while claiming no copy of it. All three are fixed with a test per
  path, and `_gc_unplaced_content` repairs the invariant on autovacuum rather
  than only asserting it, so a later bypass costs a delayed placement instead of
  deleted content. The refcount migration becomes reasonable once that sweep has
  run clean in a real database for a while.
- **`ir.content` (a blob entity keyed by digest) is not introduced.** Placements
  are per attachment, so deduplicated content has one row per referencing row —
  correct for reconciliation and reference counting, redundant for storage
  accounting. The natural next step, needed by nothing here.
- **The resolved delivery mode is deliberately not stored.** ADR-0012 asked for
  delivery as a column; what it gets is `delivery_intent`. Whether a redirect is
  *possible* belongs to the store (can it presign?) and to the deployment (is
  the `x_sendfile` location configured?), and both change without the row. A
  stored resolution would let a row claim a byte-path its store no longer
  offers.

  So intent is stored and resolution stays derived: a row may **forbid** a
  byte-path, never conjure one. `no_redirect` is its first meaningful value, for
  content that must not outlive its ACL as a signed URL. Choosing delivery per
  folder is a policy hook on top of this field, not a further column.

## Amendments

### 2026-08-07 — Status corrected to `Proposed`; none of this is built

Like ADR-0012, committed as `Accepted` and written throughout in the past tense
— including a paragraph reporting three write-path bugs "are fixed and pinned by
a test per path". No such code exists. `ir.content.placement` appears in no ref
of any repository in this workspace nor anywhere on the filesystem; neither do
`_placements_sync`, `_restore_content_from_replica`, `_content_from_replica`,
`_gc_unplaced_content` or `delivery_intent`. The commit that added this file
(`50d1487d710`) touched only documentation.

The Context's diagnosis of the present tree holds: one `store_fname` column does
fuse "which store" with "which key", and `_rewrite_stored_content`
(`odoo/addons/base/models/ir_attachment.py:693`) is real. The
`skip_res_field_check` argument is the strongest part of this record and is
unaffected by the status change.

### 2026-08-14 — Withdrawn: the work is not intended

Withdrawn together with ADR-0012, which it extends: confirmed 2026-08-14 that
the content-placement model will not be built.

What survives is what the previous amendment already named — nine copies of one
subtle precondition is evidence of a missing entity, not of nine mistakes. That
is a general observation about this codebase and does not depend on the
placement model.

The Context's diagnosis holds: one `store_fname` column carries both which store
and which key, which is why nothing can map a store back to the content it
holds. `doc/architecture/data.md` states that seam directly rather than
delegating it here.
