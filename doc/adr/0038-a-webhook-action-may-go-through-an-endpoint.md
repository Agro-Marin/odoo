# ADR-0038: A webhook server action may go through a configured endpoint

- **Status:** Accepted
- **Date:** 2026-08-15

## Context

`ir.actions.server` with `state="webhook"` is how an automation calls out of
Odoo. Its entire surface is `webhook_url`, `webhook_timeout`,
`webhook_field_ids` and a hard-coded `Content-Type: application/json`. There is
no credential field, no header configuration, and no hook to add either.

**So a receiver that requires authentication cannot be called by an automation
at all.** That is a missing capability, not a missing guarantee, and it is a
different order of problem from the ones an audit usually turns up: the circuit
breaker, the rate limiter and the event log this fork's `api_transport` provides
are improvements to a working path, while auth is the difference between the
feature working and not.

The obvious remedy — route the action through `OutboundAPIClient` — was assessed
and rejected once, and the rejection was partly wrong. Three obstacles were
identified; one dissolved on a second look.

### The transaction boundary, which is real but solved elsewhere

The action sends from a `cr.postcommit` hook, deliberately, so a rolled-back
transaction fires no webhook. The transport writes `api.event.log` from a
`cr.precommit` hook, and `commit()` runs `flush()` (which drains precommit) →
`_cnx.commit()` → `clear()` (which empties `precommit.data`) → `postcommit.run()`.
A client called from postcommit therefore queues rows into a callback that never
fires, on a cursor about to close. The same is true of everything else the
client touches: it reads its endpoint and credential, spends a rate-limit token
and moves the circuit breaker, all through the ORM.

This was first called decisive. It is not. `credential.credential.
_log_access_out_of_band` in `base_credential_manager` already writes an audit row
on a fresh `registry.cursor()`, for exactly this reason, with a documented
fallback and the rule that a failed audit must never break the operation it
records; eight other places in the tree do the same (`mail_mail`,
`delivery_carrier`, `google_sync`, …). A cursor of one's own is an established
pattern here, not an invention.

### The dependency direction, which is real and permanent

`_run_action_webhook` lives in `odoo/addons/base`, which `api_transport` depends
on transitively. `base` cannot reach the transport. So this can never be a
*move*; it is an override contributed from above, which `api_transport` already
does twice (`credential.access.log`, `credential.credential`).

### The endpoint record, which the opt-in dissolves

The client resolves an `api.endpoint.outbound` by code and refuses to build
without one, while the action has a free-text URL. Requiring every webhook URL
to become an endpoint would be wrong — an endpoint is a vendor you configured, a
webhook URL is a per-action destination.

## Decision

**An optional `webhook_endpoint_id` on `ir.actions.server`, contributed by
`api_transport`.** Unset — the default, and every existing action — is the
unauthenticated POST `base` has always done. Set, the call goes through
`OutboundAPIClient` and carries that endpoint's credential, breaker and rate
limit.

The endpoint supplies *identity*, not *address*: `webhook_url` stays a full URL
and the client's `_build_url` already passes an absolute URL through untouched.
An action keeps owning where it points, which is what makes the opt-in additive
rather than a reinterpretation of an existing field.

### `base` exposes a delivery seam, and the seam is a closure

`_run_action_webhook` now resolves `self._webhook_delivery(...)` **before**
registering the postcommit hook, and the hook calls what it returns. The return
is a plain callable over plain values, not a bound method.

That shape is the decision, not a detail. An override needs the ORM to decide
how to send — resolving an endpoint, a credential, a company — and after commit
it can read nothing. Returning a callable puts every ORM read on the living side
of the boundary and makes the boundary visible: `api_transport`'s override
captures the database name, endpoint code, company and user as strings and ints,
and the delivery opens a cursor of its own to do the rest.

`_EndpointDelivery` is a class rather than a closure so that what crossed the
boundary is inspectable — in a traceback, and in the test that asserts every
captured attribute is a `str`, `int` or `None`. A closure that accidentally
captured `self` would fail intermittently, after commit, and the receiver would
be blamed.

### An endpoint that retries is refused

`retry_enabled` defaults to `True` on an endpoint, and retry is wrong for this
caller. The send happens after the transaction committed, while the worker still
holds the request; exponential backoff there parks that worker for the whole
chain, for a delivery nobody awaits and whose result nothing reads. A server
action is explicitly not a delivery guarantee — its own timeout message says so.

So a constraint refuses the configuration and names the fix. This is deliberate
friction: it means an action usually wants its own endpoint record rather than
sharing the one your integration code calls, which is also the better modelling
— its own breaker and its own allowance, separate from your API traffic.

## Alternatives considered

**Send during the transaction instead of postcommit.** Removes the whole
problem, and removes the property the postcommit hook exists for: a rolled-back
transaction would still have fired the webhook. Rejected outright.

**Resolve auth pre-commit, POST raw in postcommit.** Captures the headers while
the cursor lives and keeps the delivery ORM-free — genuinely simpler. It buys
auth and nothing else: no breaker (its state is a write), no event log, no
usage counters. Given a fresh cursor is a pattern the codebase already carries,
paying for it once and getting all four is the better trade.

**Move the action out of `base` into an addon.** Every automation in every
database depends on it; the migration cost is enormous and the benefit is only
that the dependency could point the other way.

**Make `base_automation` or `base` depend on `api_transport`.** Considered and
rejected under ADR-0037 for the inbound direction, for the same reason: a module
about automation is not an API integration, and the transport would arrive with
endpoints, a response cache and an event log wherever automations are used.

## Consequences

- An automation can call an authenticated receiver. It could not before.
- Nothing changes for an action that does not set the field, which is all of
  them until someone does. `base`'s behaviour, its SSRF guard and its logging
  are untouched.
- The action's own SSRF guard still runs first and stays the stronger one:
  `_webhook_url_blocked_reason` resolves DNS and refuses anything not globally
  routable, which `is_private_host` deliberately does not match, because there
  the same question is asked to *permit* disabling TLS.
- A delivery through an endpoint costs one pooled connection for its duration.
  Postcommit hooks run sequentially in the request thread, so the ceiling is one
  per worker.
- The event log now covers webhook actions that opt in — the same trail the rest
  of the outbound stack writes, rather than a second one.
- A failure in the delivery is logged and swallowed. It runs after commit, where
  raising reaches no caller and can only break whichever postcommit hook happens
  to run next.

## Enforcement

`api_transport/tests/test_webhook_action_endpoint.py` — eight tests. The
load-bearing ones are the boundary: that an unset field still yields `base`'s
own delivery, that the returned callable holds no recordset (asserted over every
captured attribute, so a future field of the wrong type fails), that it opens
its own cursor, and that the request carries the endpoint's `Authorization`
header while still addressing the action's own URL.

`base`'s side is guarded by the 19 tests in
`base/tests/test_ir_actions_webhook_{timeout,logging}.py`, which were run
unchanged across the seam extraction to show it moved no behaviour.

**What nothing enforces:** a future override of `_webhook_delivery` may capture
a recordset, and only its own tests would catch it. The type assertion above
covers this module's implementation, not the pattern. An AST rule could refuse
recordset captures in that method's return; it is not worth writing for one
implementer, and this note is where the second one should look first.
