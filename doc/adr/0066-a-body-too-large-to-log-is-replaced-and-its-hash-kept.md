# ADR-0066: A body too large to log is replaced, and its hash is kept

- **Status:** Accepted
- **Date:** 2026-08-25

## Context

`InboundController.validate_inbound_request` writes the whole request body into
the `request_payload` column of `api.event.log` — a `fields.Text` with no bound — and does so
*before* the duplicate check, so a body refused as a duplicate is stored in full
too. Duplicate detection then compares a hash the controller computed from the
request against the `request_payload_hash` column, which is a stored computed
field derived from `request_payload`.

For an endpoint whose body is a document rather than a description of one, that
is a copy of the document in a log column. Measured on a disposable database
with `remote_mobile` installed: a phone posting a 2 MB call recording as base64
wrote **2 666 793 characters** into `request_payload`, while the same audio was
also stored as a 2 000 000-byte filestore attachment on
`remote.call.recording.audio`. The app's own cap is 36 MB, so the ceiling is
roughly 48 MB of base64 per recording, SHA-256'd on the way in and retained
until `_gc_old_logs` reaches it.

The outbound half of the same module already treats this as a policy question:
`log_request_payload` on `api.endpoint.outbound` suppresses the body, and
`_serialize_payload_for_log` truncates what it does keep at
`_MAX_LOGGED_PAYLOAD`. The inbound half has neither.

Two constraints make the obvious fix wrong.

**The hash is derived from the stored body.** Truncating `request_payload`
changes `request_payload_hash`, and `_refuse_duplicate` compares that column
against `compute_payload_hash(payload_dict)`. The two would no longer agree, and
the failure is silent: duplicate detection would stop matching rather than raise.

**For an asynchronous endpoint the stored body is the work queue.**
`api.endpoint.inbound._run_queued_event` replays the row, and
`remote.device._process_queued_event` reads it back through `get_payload_dict()`
and passes that same column on as `raw_payload`. Shortening it there does
not shorten a log; it discards the work.

## Decision

An inbound endpoint may declare `log_request_payload_max_bytes`. When the body
exceeds it, the row stores a JSON placeholder naming the real size and the first
512 characters, and carries the true hash in a new
`request_payload_hash_override` column and the real size in
`request_payload_omitted_bytes`.

- `_compute_payload_hash` prefers the override, so duplicate detection compares
  the same value it always did.
- `_compute_payload_sizes` prefers the omitted count, so the recorded size
  describes the request and not the placeholder.
- `_payload_log_limit()` returns 0 — no limit — whenever `processing_mode` is
  `async`, so the setting cannot be applied where the payload is the queue.
- The default is 0, so no existing endpoint changes behaviour. `remote_mobile`
  sets 64 KiB on devices in the Mobile Phone category, which is above a
  200-point location batch (~24 KB) and a 100-call batch (~10 KB) and far below
  any recording.

The placeholder is valid JSON so `get_payload_dict()` returns a dict rather than
logging a parse warning.

The same change collapses three copies of one hash computation —
`tools.compute_payload_hash`, and `_compute_payload_hash` and
`check_duplicate_before_create`, both on `api.event.log` — onto the first. They had to
agree exactly, for the same reason the override exists, and nothing checked that
they did.

## Alternatives considered

**Truncate unconditionally in `_open_event_log`.** Silently breaks duplicate
detection through the hash, and silently breaks async replay. Both failures are
invisible: no exception, just a system that stops deduplicating and a queue that
processes empty payloads.

**Pass `create_event_log=False` for the recording route.** `_refuse_duplicate`
requires an event log, so this trades the storage for duplicate detection on the
one route where a retried upload creates a second copy of an audio file. The
cost lands on exactly the data the mechanism protects.

**Strip `audio_b64` from the body before storing it.** Keeps the surrounding
metadata, but the hash must still be of the body as received, so it needs the
override anyway — and it puts knowledge of one addon's field names into the
transport layer.

**Cap the field globally, with a default limit.** A single default cannot serve
an endpoint that receives a 30-byte reading and one that receives a document,
and it would change behaviour for every existing endpoint at once, including
asynchronous ones whose payload is load-bearing.

## Consequences

An operator reading an event log for a capped endpoint sees the placeholder
rather than the body. That is the point, and the head of the body plus the true
size are kept so the row still identifies what was posted.

`request_payload_size` no longer always equals the length of
`request_payload`. It equals the size of the body as received, which is what the
field is for; a reader who wants the stored length has `request_payload`.

A future endpoint that gains asynchronous processing after a limit was set on it
silently stops applying that limit. This is the safe direction — the payload
becomes load-bearing at the same moment — but it means a limit that appears set
may not be in force, and `_payload_log_limit()` is the only correct way to read
it.

## Enforcement

`api_transport/tests/test_api_endpoint_inbound.py` pins the policy and the
hash override. The end-to-end half — that a capped endpoint stores the
placeholder, that the duplicate check still refuses the second identical
request, and that a body under the limit is still logged whole — is pinned by
the recording suite of the `remote_mobile` module, which lives in the AgroMarin
addons repository and so is named here in prose rather than as a path this
checkout can resolve. No new CI gate; the existing suites cover it.
