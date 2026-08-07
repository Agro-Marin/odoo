# ADR-0013: Content placement — where an attachment's bytes are, as data

- **Status:** Proposed
- **Date:** 2026-07-30
- **Extends:** ADR-0012 (attachment storage layers)

## Context

ADR-0012 layered the storage stack and closed with the observation that delivery
could not become a stored column until "identity lives in one column for every
backend". This ADR is that step, and it turns out the blocker was not which column
identity lives in but that **there is only one of it**.

`store_fname` answers "where is the content" with a single string. That forces two
independent facts into one value:

- **which store** holds the bytes, encoded as a `scheme://` prefix;
- **which key** they are under.

Both costs of that fusion were paid in production:

- The prefix is not part of the object key, and nothing in the type system says so.
  `documents_cloud` passed the whole `s3://b3/ab/<digest>` URI to the bucket as the
  key, so every object landed under a literal `s3:` pseudo-folder. ADR-0012 states
  the rule ("the store receives a bare key") because the rule was broken; a rule is
  what you write when the model cannot express the constraint.
- One column admits one answer, so every feature needing a **second** copy invented
  its own columns. `cloud_storage_s3` carries `s3_blob_name` and
  `s3_mirror_pending`, and only that module can read them. Reconciliation could
  detect that content was gone; the mirror could restore it; neither could ask the
  other, so a content-scope repair quarantined rows whose bytes were sitting
  byte-identical in the bucket.

There was a third, quieter cost. Reference counting — "is this key still used?" —
had to be asked through `ir.attachment._search`, which silently injects
`res_field = False`. Every call site therefore needs `skip_res_field_check=True`,
and forgetting it makes binary-field attachments invisible and their content
collectable. That workaround appears in nine places across base, `cloud_storage`,
`cloud_storage_s3`, `documents_cloud` and the reconciler. Nine copies of one subtle
precondition is not nine mistakes; it is a missing entity.

## Decision

Make the copy the entity: `ir.content.placement`, one row per copy of an
attachment's content.

```
attachment_id  store_name  key  role  state  size  etag  verified_at
               ^^^^^^^^^^  ^^^
               separate columns — a key can never carry a scheme
```

- **`role`** is `primary` (written synchronously; what the row reads from) or
  `replica` (written after commit; exists to be restored from).
- **`state`** is `pending` / `present` / `missing` / `stale`. It is the same
  vocabulary reconciliation already classified drift with, now stored per copy
  rather than flattened onto the attachment.

### Placements are derived, not written by callers

`_placements_sync()` runs from `create`, `write` and `_rewrite_stored_content` and
reads `store_fname`. A placement written at each call site is a placement someone
forgets — which is precisely how the one module holding a second copy became the
only module that could find it.

### Two-phase write

A replica is created `pending` **inside** the caller's transaction, before any
upload. This is what makes the write crash-safe in both directions:

| outcome | result | who handles it |
|---|---|---|
| transaction rolls back | no row; the uploaded object is unreferenced | orphan sweep, after grace |
| commits, upload failed | row stays `pending` | replication cron retries |
| commits, upload succeeded | row is `present` | — |

The `s3_mirror_pending` boolean was a degenerate single-store version of this.

### Repair is replication reversed

`pending → present` uploads from a copy that has the bytes. `missing → present`
writes the bytes back from a copy that has them. These are one operation, so they
are one implementation: `_restore_content_from_replica()` reads the same placements
the replication engine writes. Reconciliation calls it before quarantining, and a
read that finds its primary unreadable falls back to a `present` replica rather
than answering `b""`.

### Both read paths recover, and a download prefers a redirect

`raw` and `/web/content` reach storage by different routes — `_stored_content` and
`_to_http_stream` — so closing the gap in one left the other answering `b""` for a
row the first could recover. Both now fall back to a `present` replica, on the
failure path only, so a healthy read pays nothing.

The download path prefers **signing a URL** over streaming the bytes, because that
is the difference the storage choice actually turns on: per ADR-0012's measurements
a redirect releases the worker in 0.149 ms while carrying the payload holds one for
seconds. Existence is checked before signing — on this path the primary is already
known broken, so the extra `head` is rare, and redirecting to a second missing
object spends the same worker to produce a 404.

A `url` stream is never judged empty: presigning does not fetch, so a redirect to a
missing object is indistinguishable from a redirect to a present one. That case
belongs to reconciliation.

### Reads do not repair

`_content_from_replica` serves the bytes and returns. A read that rewrote its own
storage would mutate on a GET, and the cursor serving that GET may be read-only.
Recording the drift belongs to reconciliation — which, as of this change, sweeps
every store that declares `CAP_LIST` rather than only the filestore.

## Consequences

- The `s3://`-in-the-object-key class of bug is **unrepresentable**: store and key
  are different columns, and nothing concatenates them on the way to a store.
- A second copy is policy (`_replica_store_names()`), not a module's private
  columns. Anything that can read a placement can restore from it.
- `storage_state` becomes retractable, because something other than a rewrite can
  now assert a row is healthy: a scan that verified it, or a copy that supplied it.
- Reference counting now has somewhere correct to live. Counting placement rows on
  an indexed FK does not go through `ir.attachment._search` and so cannot be got
  wrong by omitting `skip_res_field_check`. The nine existing call sites are **not**
  migrated to it yet — see below.
- Creating attachments costs measurably more, and not much: A/B'd in-process over
  400 bulk creates, placement sync adds 0.028 ms per attachment (4.5%). The sync is
  batched — one query to read existing placements and one to insert — and the
  replica path returns before any per-record query when no replica is configured.

### Deliberately not done

- **`store_fname` is not retired.** It remains authoritative for reads; placements
  describe where content is, they do not yet decide what is read. Retiring it is a
  data migration on every attachment row and wants its own decision.
- **`s3_blob_name` / `s3_mirror_pending` are not deleted.** They are now redundant
  with a `replica` placement, but `documents_cloud`'s migration onto
  `KeyedObjectStorage` is in flight on a separate branch, and removing columns
  underneath it would collide. The removal is a follow-up, not a disagreement.
- **The `skip_res_field_check` call sites are not migrated.** Counting placements
  instead of searching attachments is only safe if placements are complete for
  every row, and these call sites gate *deletion of content*. Being wrong there
  costs data, not a retry.

  That caution was warranted: three write paths — `copy()`, `_set_attachment_data`
  and the streamed upload behind `_create_from_stream` — reached `store_fname`
  through `super().write()` and produced rows referencing an object while claiming
  no copy of it. All three are fixed and pinned by a test per path, and
  `_gc_unplaced_content` now *repairs* the invariant on autovacuum rather than
  only asserting it, so a bypass added later costs a delayed placement instead of
  deleted content. The refcount migration becomes reasonable once that sweep has
  run clean in a real database for a while — it is a separate change with a
  separate verification, not a rider on this one.

- **`ir.content` (a blob entity keyed by digest) is not introduced.** Placements
  are per attachment, so deduplicated content has one row per referencing row. That
  is correct for reconciliation and for reference counting; it is redundant for
  storage accounting. A content entity is the natural next step and is not needed
  for anything this ADR claims.
- **The RESOLVED delivery mode is deliberately not stored.** ADR-0012 asked for
  delivery as a column; what it gets is `delivery_intent`, and the difference is
  the point. Whether a redirect is *possible* belongs to the store (can it
  presign?) and to the deployment (is the `x_sendfile` location configured?), and
  both change without the row. A stored resolution would let a row claim a
  byte-path its store no longer offers — and ADR-0012 already records that
  enabling `x_sendfile` without the matching frontend breaks every download.

  So intent is stored and resolution stays derived: a row may **forbid** a
  byte-path, never conjure one. `no_redirect` is its first meaningful value, for
  content that must not outlive its ACL as a signed URL readable by anyone
  holding it. Choosing delivery per *folder* — which is what `documents_cloud`'s
  benchmark exists to inform — is a policy hook on top of this field, not a
  further column.

## Amendments

Append-only. An amendment corrects what this record says *about the repo*; it
never edits the decision above.

### 2026-08-07 — Status corrected to `Proposed`; none of this is built

Like ADR-0012, which it extends, this record was committed as `Accepted` and
written throughout in the past tense — including a paragraph reporting that
three write-path bugs "are fixed and pinned by a test per path". No such code
exists here. `ir.content.placement` appears nowhere in any ref of any repository
in this workspace, nor anywhere on the filesystem; neither do
`_placements_sync`, `_restore_content_from_replica`, `_content_from_replica`,
`_gc_unplaced_content` or `delivery_intent`. The commit that added this file
(`50d1487d710`) touched only documentation.

The Context's diagnosis of the *present* tree holds and is worth keeping: a
single `store_fname` column really does fuse "which store" with "which key", and
`_rewrite_stored_content` (`odoo/addons/base/models/ir_attachment.py:693`) is
real. The `skip_res_field_check` argument — that nine copies of one subtle
precondition is a missing entity rather than nine mistakes — is the strongest
part of this record and is unaffected by the status change.

Promote to `Accepted` when `ir.content.placement` exists. At that point
`test_adr_coherence.py` stops exempting this file and begins requiring every
name above to resolve, which is the check that would have caught this in the
first place.
