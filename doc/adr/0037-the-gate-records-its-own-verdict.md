# ADR-0037: The inbound gate records its own verdict

- **Status:** Accepted
- **Date:** 2026-08-15 (Draft while the model did not exist; Accepted the same day, once it did)

## Context

ADR-0017 consolidated inbound authentication into `inbound.gate.mixin`, shared
by `api.endpoint.inbound` and `base.automation`. Its Consequences claimed the
divided audit trail closed as a result; an amendment the same day withdrew that,
because the gate lives in `base_credential_manager` precisely so
`base_automation` can reach it without depending on `api_transport`, and
`api.event.log` belongs to `api_transport`. The amendment named the remedy as
"a dispatcher hook the gate calls after a verdict, which `api.endpoint.inbound`
implements by writing `api.event.log` and `base.automation` by writing whatever
it should", and said nothing about it was designed yet.

**That remedy is the wrong shape, and the reason is what measuring the two paths
turned up.** A hook that lets each side write its own record does not unify
anything: it produces two stores again, with the same query gap, reached by a
shared call. Worse, it assumes both sides already record their verdicts and
merely disagree about where. Neither does.

### What the two paths actually record

The gate answers `(allowed, status, reason)`. Both callers branch on `allowed`
and drop `reason` into a log line:

- `base_automation/controllers/main.py` returns a JSON error on refusal and
  writes nothing anywhere. Its `log_webhook_calls` flag governs `ir.logging`
  rows written by `_execute_webhook` — *after* admission — so it does not cover
  a request that never got that far.
- `api_transport/controllers/inbound_controller.py` returns the refusal at line
  88. `_open_event_log` is at line 94. A refused caller therefore produces no
  `api.event.log` row either.

So the trail is not merely divided:

| | recorded by |
|---|---|
| admitted request | `api.event.log` (transport); `ir.logging` free text, opt-in (automation) |
| **refused request** | **nothing, on either path** |

"Who has been failing authentication against our inbound surface, and how often"
is unanswerable in this fork today, in any store, for either mechanism. That is
the security-relevant half of the question and the half nobody can ask. A
brute-force attempt against a webhook UUID or a bearer token is visible only as
`_logger.warning` text, which is unqueryable, unretained by policy, and absent
entirely wherever log level is raised.

### Why the dependency direction forbids the obvious answers

Both callers already depend on `base_credential_manager`, which depends only on
`base`. Neither direct dependency between the two callers is affordable:

- `api_transport` → `base_automation` drags in `digest`, `resource` and `sms`.
  A GPS endpoint should not require the SMS module.
- `base_automation` → `api_transport` drags in endpoints, the response cache and
  the event log. An automation rule is not an API integration.

A link module depending on both is the canonical Odoo answer to that bind, and a
process-global sink registry is the decoupled one. Both are answers to a problem
this fork does not have to have.

## Decision

**The gate writes the record, because the gate is what makes the decision.**

A new model `inbound.access.log` in `base_credential_manager`, beside
`credential.access.log` — which already answers the sibling question, "who read
a credential". `_check_inbound_request` writes it on every verdict it reaches.

This needs no new dependency, no link module and no registry, because the layer
that owns the decision is already the layer both callers share. A future inbound
implementer gets the trail by inheriting the mixin rather than by remembering to
log, which is the property the per-side hook could not offer.

### Refusals are always recorded; successes are not, unless asked for

This is the load-bearing half of the decision and it is a volume judgement, not
a squeamish one.

Recording every admission repeats a mistake this stack already made and
measured. `check_inbound_auth` is on the path a GPS unit takes once per position
fix; routing it through `authenticate_request`, which writes a
`credential.access.log` row, was measured to turn a fleet's ordinary reporting
into six-figure daily audit volume, and the fix was to split the scheme dispatch
away from that side effect. A row per successful admission puts it straight
back.

So:

- **Every refusal is recorded.** It is the security event, it is rare in ordinary
  operation, and when it stops being rare that is precisely the signal the record
  exists to carry.
- **Successes are recorded only where the gate's owner opts in**, via a field on
  the implementing record. Where they matter they are already covered:
  `api.event.log` for transport endpoints, `ir.logging` for automation rules with
  `log_webhook_calls`.

### A refusal flood must not become the attack

An attacker controls how many refusals they generate, so unbounded refusal
logging is a disk-fill vector — a log that helps until the moment it is needed
most is not a control.

The gate already refuses a caller on its own rate limit before authentication
(`_check_inbound_caller`). Those refusals **collapse**: one row per caller per
window, carrying a count, rather than one row per request. A caller hammering a
closed door leaves one row per window saying how hard.

## Alternatives considered

**A hook per implementer, as the ADR-0017 amendment sketched.** Rejected above:
it preserves two stores and the query gap, and it leaves each new implementer
free to record nothing, which is the state both current implementers are in.

**Move `api.event.log` down into `base_credential_manager`.** It would make one
store reachable from both, and it is wrong by concern: 42 fields describing a
full request/response exchange — payloads, headers, cache hits, retry counts,
performance rating — inside a module about credentials. The credential manager
would become the home of a model it has no business knowing.

**Extend `credential.access.log` instead of adding a model.** Rejected on the
key. That model is keyed on `credential_id` and describes an operation on a
credential. An admission is keyed on the endpoint or rule, and the interesting
case — a token matching no credential at all — has no `credential_id` to key on.

**A link module, or a process-global sink registry.** Both are sound answers to
a dependency bind that does not exist here, since the shared floor already holds
the gate. A registry additionally needs a per-database guard, because a
process-global handler registered at import outlives the question of whether the
subscribing module is installed in the database being served.

**Record everything and rely on retention to bound it.** This is the option the
volume measurement rules out. Retention bounds disk, not write cost, and the
write cost is paid on the hot path of every device in the fleet.

## What the building added

**The status cannot carry the outcome.** The caller's rate limit and the
endpoint's quota both answer 429, and they are opposite facts — a stranger
hammering a closed door, versus a legitimate sender who authenticated and then
ran out of allowance. Only the exit that produced the verdict knows which, so
the decision returns the outcome as a fourth element and the recorder is told
rather than left to infer. Inferring it from the status was written first and
collapsed the two into one category, which the tests caught.

**Audit mode is admitted and recorded anyway.** It is an unauthenticated request
let through on purpose, which is the state an operator most needs a list of, and
it is not the ordinary success the opt-in exists to keep out of the table. The
skip is keyed on the `allowed` outcome specifically, not on the boolean.

## Consequences

- One query answers "who was refused, by what, from where, how often" across
  both inbound mechanisms, and across any future one that inherits the gate.
- The trail for *admitted* requests stays divided, deliberately. `api.event.log`
  records an exchange; `ir.logging` records an execution; neither is the
  admission decision, and unifying two records of different things would be
  worse than leaving them. This ADR closes the question it can answer and says
  plainly which one it does not.
- `base_credential_manager` gains a model, a retention cron and an access rule.
  It does not gain a dependency.
- A refusal now costs a write. The rate-limit collapse bounds the pathological
  case; the ordinary case is bounded by refusals being rare.
- Anything inheriting `inbound.gate.mixin` is audited from the moment it
  inherits, with no per-implementer work — which is the property that makes this
  a floor rather than a convention.

## Enforcement

`base_automation/tests/test_inbound_access_log.py` — thirteen tests, driven
through `base.automation` because it is the concrete implementer that had no
structured record at all (`api.endpoint.inbound` is an `AbstractModel` with no
table, and its concrete implementers live in a sibling repo). They pin the two
halves that are decisions rather than mechanism: that an ordinary success writes
nothing unless the record opts in, and that repeated caller-limit refusals
collapse to one row per window.

**What nothing enforces**, stated plainly rather than left to be discovered:
`_decide_inbound_request` is callable directly, and a caller who reaches for it
gets the verdict with no record written. That is deliberate — a health probe
should not fill the table — and it is also the way this decision can be
undermined by accident. Nothing distinguishes the two intents at the call site.
A checker would have to be an AST rule refusing `_decide_inbound_request` outside
this mixin and its tests, which is a rule worth adding the first time somebody
calls it from a controller, and not before: today the only callers are
`_check_inbound_request` and the tests.

Retention is a cron rather than a gate, and an operator who disables it gets an
unbounded table. That is the same contract `credential.access.log` beside it
already has, so it is a property of this module rather than of this decision.
