# ADR-0017: Inbound HTTP — one gate, two dispatchers

- **Status:** Accepted
- **Date:** 2026-08-12
- **Revised:** 2026-08-14

## Context

The fork receives inbound HTTP two ways, and on 2026-08-11 an audit of the
API/credential stack read that as duplication to be removed.

`base_automation` carries webhook rules: an automation with `trigger` set to
`on_webhook`, reached at a UUID path, payload handed to a server action.
`api_transport` carries `api.endpoint.inbound`, an `AbstractModel` a concrete
model inherits so the *record itself* is the endpoint.

Their configuration surfaces look alike field for field — `base_automation` has
`webhook_signature_header`, `webhook_signature_prefix`,
`webhook_timestamp_check`, `webhook_ip_allowlist`, `webhook_rate_limit`;
`api.endpoint.inbound` has `signature_header`, `signature_prefix`,
`timestamp_verification_enabled`, `ip_whitelist`, `rate_limit_enabled`.

The primitives underneath are already shared, and deliberately so:
`verify_signature`, `verify_timestamp` and `ip_in_allowlist` live in
`addons/credential/tools/authentication.py`, and both mechanisms consume
`rate.limit.bucket`. `ip_in_allowlist`'s docstring records what consolidating
bought: the two previous copies disagreed on whether an empty allowlist matches
nothing or everything, and agreed in practice only because both callers guarded
the call.

So what remains duplicated is the configuration surface and the controller, not
the security logic. The question is whether that remainder collapses too.

### What the first draft could not see

The 2026-08-12 draft answered "no" from reading the two field sets. A second
audit on 2026-08-14 ran them, and three measurements changed the answer.

**An authenticated `base_automation` webhook stopped working after 100 calls in
an hour.** Measured 2026-08-14 against a scratch database: 130 POSTs carrying a
valid bearer token to `/web/hook/<uuid>` returned 100 × `200` then 30 × `422`,
and the credential access log held 100 `read` rows and 30 `read_rate_limited`
rows, all attributed to the public user. `api.endpoint.inbound` compares a
presented token against `credential_fingerprint`, a stored SHA-256 costing no
decryption; `base_automation._verify_webhook_request` reads the credential's
plaintext per request, and that read goes through `_enforce_access_rate_limit`,
whose cap is per user per hour and whose purpose is to stop a *user* harvesting
credentials. Every sender of a public webhook shares one bucket, because
`auth="public"` gives them all one uid.

Neither mechanism is wrong about its own job. The defect is that "verify the
caller's identity" was written twice, and the second copy did not inherit the
first's decision about how to do it cheaply.

**Two of the three inbound gates are inside `api_transport`, not one.**
`api.endpoint.inbound` carries both `authenticate_request`, which dispatches on
`auth_type`, and `check_inbound_auth`, which until 2026-08-14 did not: it called
`_check_token` unconditionally, so an endpoint configured for HMAC or custom
verification was checked as though it held a bearer token. That pair is not
about rules versus records, so the split this record describes does not account
for it.

**Inbound identity has four shapes in this workspace, not two.**
`api_stock_scale` reaches its routes with upstream's `auth="bearer"`, which
authenticates a `res.users.apikeys` and yields a real user session;
`telegram_bot` uses `auth="public"` with the vendor's token in the URL path.
Neither gets an IP allowlist, a payload cap, a replay window or a rate limit,
and nothing in the tree says whether they should.

## Decision

**Keep two dispatchers. Share one gate.**

Inbound HTTP is three concerns, and they do not split the same way:

| concern | question | varies by mechanism? |
|---|---|---|
| **identity** | who is calling, and can they prove it | **no** |
| **admission** | should we spend work on this caller at all | **no** |
| **dispatch** | what happens once they are admitted | **yes** |

**Dispatch stays split.**

*`base_automation` webhooks are for a rule.* The endpoint is configuration: an
administrator publishes one, points it at a server action, and the payload is
`record_getter` away from an existing record. No registry of callers, no
per-caller state. The right answer when the sender is a SaaS product posting a
notification.

*`api.endpoint.inbound` is for a fleet.* The endpoint *is* a record, so the
device has an identity, its own credential, its own rate limit and a row that
survives the request. It models three things the rule path does not: duplicate
detection over a configurable window, an async processing queue, and
`api.event.log` — the same log the outbound half writes, so one query answers
"what did we exchange with the field last night" in both directions.

On the day the first draft landed the concrete implementers lived in
`agromarin`: the `remote` device model inherited it, and `remote_access_device`
and `remote_gps` called `check_inbound_auth` and `_inbound_auth_mode` directly.
The same repository's scale-station module went the other way on purpose — its
Confirm-Tarima ingest is a `base_automation` rule delegating to an abstract
handler model, because a station posting a completed weighing is a notification,
not a device whose state we hold.

**A rule when the endpoint is configuration, a record when the endpoint is a
thing you own.**

**Identity and admission move to one mixin in `base_credential_manager`** — the
module that already owns every primitive both halves call
(`credential.credential`, `rate.limit.bucket`, the verifiers in
`addons/credential/tools/authentication.py`) and the only common ancestor of
`api_transport` and `base_automation`, which depend on `mail` and on
`digest`/`resource`/`sms` respectively and so cannot depend on each other.
Dependency direction is the criterion, per ADR-0016.

The mixin carries the fields a gate needs and no others, and exposes one entry
point returning a verdict rather than raising. Three load-bearing properties:

1. **Token schemes compare a stored fingerprint; no inbound path decrypts a
   credential per request.** `api.endpoint.inbound`'s existing decision, made
   universal.
2. **Where a scheme genuinely needs the plaintext** — HMAC cannot be computed
   from a hash — **the read is internal**, outside the per-user decryption cap.
   That cap stops a user harvesting secrets; a webhook verifying a signature is
   the system authenticating a caller, and counting it against a human's hourly
   allowance was a category error, measured above at 100 calls.
3. **Two rate limits, on opposite sides of authentication.** A cheap
   caller-keyed one before, protecting the server from expensive work for
   strangers; the existing endpoint-keyed bucket after, protecting the
   legitimate sender's quota from anyone who knows the URL. The two orderings in
   the tree were each half-right, because they limited different things. The
   pre-auth limit is the in-memory limiter in
   `addons/credential/tools/rate_limiter.py`, whose per-worker inaccuracy is
   acceptable for a coarse guard and whose freedom from a database write is what
   the hot path needs; the post-auth limit stays `rate.limit.bucket`, exact
   across workers.

## Alternatives considered

**Keep three gate implementations** (the 2026-08-12 decision). Rejected on the
evidence: a webhook that dies at 100 authenticated calls an hour, a
`check_inbound_auth` that ignored `auth_type` for as long as it existed, and a
divided audit trail. Independent implementations of one security check do not
stay in step; two of the three had already drifted before anyone compared them.

**Fold the configuration surface into `api.channel.mixin`** — the option the
first draft rejected, correctly. That mixin held 18 fields when measured on
2026-08-14; inheriting it would put credentials, retry policy, `code`,
`sequence`, `description`, `date_last_activity` and a *required* `name` onto
every automation rule.

**That objection does not carry to a narrow gate mixin, which is why this record
changes.** Of the 18 fields, 7 are gate fields. Counting the inbound-only fields
on `api.endpoint.inbound` — the signature pair, the timestamp trio, the
custom-verifier hook, the allowlist, the payload cap — a gate mixin came to 15
when measured on 2026-08-14, and `base_automation` already carried its own
spelling of 12 under a `webhook_` prefix. For that model the change is a
**rename, not an addition**: it gains a stored fingerprint, a custom-verifier
hook and an explicit strict-mode flag, and loses nothing.

**Collapse onto `base_automation` and delete `api.endpoint.inbound`.** Rejected,
unchanged. The device fleet loses duplicate detection, the async queue and its
half of `api.event.log`. The first is not cosmetic: a GPS unit on a flaky link
retries, and a rule-based endpoint would process the same fix twice. Rebuilding
them on `base.automation` reinvents the deleted model one server action at a
time.

**Collapse onto `api.endpoint.inbound` and drop the webhook trigger.** Rejected,
unchanged. The trigger is upstream surface integrators already target, and
making an administrator declare a model to receive one JSON POST is a worse
trade than the duplication it removes.

**Bring `auth="bearer"` and the Telegram route under the same gate.** Deferred.
Both authenticate something real; what they lack is admission control.
Extending the gate to routes that own no endpoint record is a larger design
question, and nothing measured on 2026-08-14 showed it costing anything yet.

## Consequences

Two mechanisms remain, so the reason they exist is still recorded; one gate
serves both, so the next drift between their security checks cannot happen.

**`base_automation` pays a rename.** Its gate fields move to the mixin's
spelling — a data migration plus edits to its views and tests, and to
`api_stock_scale` in `agromarin`, which seeds those field names. Cross-repo work,
sequenced as such. Nothing outside those places referenced the fields when
measured on 2026-08-14.

**The ordering question gets an answer, and it is not one of the two in the
tree.** Both comments arguing it — in
`addons/base_automation/models/base_automation.py` and in the inbound controller
— stop being contradictory once the two limits are distinguished.

**A gate serving two dispatchers can be pulled toward the lowest common
denominator.** The guard is that it owns identity and admission only: duplicate
windows, queues, event rows and server actions stay out by construction, and
that boundary is what to defend in review.

Adding a checker to `tooling/architecture/` is deliberately not part of this.
The invariant worth enforcing is "no second implementation of the gate", which
is a review rule until it can be stated so a script can check it.

## Amendments

### 2026-08-14 — one Consequence was asserted, not built

The Consequences section claimed the divided audit trail closes, because a
shared gate writes `api.event.log` by construction. Wrong when written. The gate
writes no such row and cannot: that model belongs to `api_transport`, and the
gate lives in `base_credential_manager` precisely so `base_automation` can reach
it without depending on `api_transport`. The dependency direction that makes the
consolidation possible forbids the gate logging there.

The trail is still divided: `base_automation` webhooks log to `ir.logging`,
`api.endpoint.inbound` events to `api.event.log`, and no single query covers all
inbound HTTP.

What the shared gate changes is that closing it is a seam rather than a second
implementation: a dispatcher hook the gate calls after a verdict, which
`api.endpoint.inbound` implements by writing `api.event.log`. Nothing about that
is designed yet, and this record does not decide it.

### 2026-08-14 — decision revised, then built

The 2026-08-12 record decided "keep both, share nothing further" at `Accepted`.
Revised rather than superseded because it was still a working draft. It sat at
`Proposed` while the gate did not exist and returned to `Accepted` the same day
once it did: `credential.auth.mixin` and `inbound.gate.mixin` are in
`base_credential_manager`, `api.endpoint.inbound` and `base.automation` both
inherit the gate, and the `webhook_`-prefixed field set is gone from
`base.automation` bar a deprecated alias for each.

Two things found in the building:

- **The gate had to be two mixins, not one.** `api.channel.mixin` also backs
  `api.endpoint.outbound`, so a single gate would have put the allowlist, the
  replay window and the payload cap onto every *outbound* endpoint — the
  pollution the first draft refused. Identity is `credential.auth.mixin` (both
  directions authenticate something); admission is `inbound.gate.mixin` (only a
  callee admits).
- **`none` meant two different things.** `base_automation` read it as "no
  authentication configured", its documented default; `verify_signature` reads
  it as a kill switch defaulting to off, logging "SECURITY RISK: Signature
  verification DISABLED". The gate answers the first and leaves the kill switch
  to direct callers of the verifier. No inbound endpoint in the workspace used
  `none` on that date — every occurrence was outbound, which never enters the
  gate.

What changed:

- The **Decision** kept the configuration surface split by mechanism; it is now
  split by concern. The rule-versus-record distinction is kept verbatim.
- The **Alternatives** rejected one shared mixin on the ground that it would put
  the whole channel vocabulary onto every automation rule. Still true of
  `api.channel.mixin`. What it did not establish, and this revision measured, is
  that a mixin scoped to the gate carries none of those fields.
- The **Consequences** named "teaching the webhook path to write
  `api.event.log`" as the thing to fix first if the decision were revisited. It
  was revisited for a different reason, and a shared gate subsumes that fix.

The trigger was not a re-reading but three measurements on 2026-08-14: the
100-call ceiling, `check_inbound_auth` ignoring `auth_type`, and the
four-not-two shapes of inbound identity. The first is a live defect in a shipped
module, and it exists because one security check has two implementations.
