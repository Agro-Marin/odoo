# ADR-0040: The fallback chain is a chain of models, and the orchestrator selects one

- **Status:** Proposed
- **Date:** 2026-08-15

## Context

ADR-0039 moved cost, capability and the ratings off `ai.provider` onto
`ai.model`, on the rule that a value belongs where its decider lives: the API key
decides the endpoint, the model name decides the price. It left one thing on the
provider that fails the same test — the fallback chain.

`fallback_provider_ids` was a `Many2many` from `ai.provider` to `ai.provider`,
and `execute_with_fallback` walked it. What a request executes is a model.

### The chain could not express its most ordinary case

Because the relation held providers, a hop was necessarily a *vendor* change — a
different key, a different wire, a different bill. The cheapest and most common
recovery in this domain is not that. It is a smaller model on the vendor already
authenticated: rate-limited or over budget on the large model, retry on the small
one.

Inexpressible. A `Many2many` cannot list the same provider twice, and a second
entry would resolve the same `default_model_id` if it could.

### The chain was empty in everything shipped

Measured 2026-08-15: no seed data and no module set `fallback_provider_ids` —
only tests did, each building its own chain. The one production caller of
`execute_with_fallback`, the OCR module in the agromarin repository, passed no
explicit chain either.

So `providers_to_try` evaluated to `[primary_provider]` in every shipped
configuration, and the retry classification, the chain walk and the `after:`
event-log annotation all ran over a list of one. The manifest advertised that
`execute_with_fallback` walks the chain on failure. It did not.

An inert feature is worse than an absent one where the manifest names it: a
reader configures nothing, believing resilience is already there.

### Selection asked the vendor a question only a model can answer

`select_provider` filtered candidates on `required_capabilities`, and the OCR
module asked for `has_vision`. After ADR-0039 that flag is a roll-up — true when
*some* model of the vendor reads images. For Groq that is the vision model, while
the model the provider would run by default is blind. The caller then depended on
`OpenAICompatibleClient.vision_completion` silently substituting the catalog's
`vision_model`: a correct rescue for a caller that knows nothing about models,
and a trap for one that passes a model of its own.

## Decision

**`fallback_model_ids` on `ai.model`, and an orchestrator that selects and walks
models.**

- `ai.model` gains an ordered `Many2many` to itself. A chain may stay on one
  vendor, cross to another, or both: `claude-opus-5 → claude-sonnet-5 →
  gpt-4o-mini` is one chain, and the first hop costs no new credential.
- `execute_with_fallback(primary_model, …)` walks models, deriving each one's
  provider through `provider_id` to build the client.
- `request_func(client, model)` receives the model about to run, not the vendor.
  A caller that names a model on the wire names the right one on every hop.
- `select_model(…)` is added beside `select_provider`, filtering and ranking
  `ai.model` records on their own capability and cost.

`select_provider` stays. "Which vendor" remains a real question — it is what a
credential, a breaker and a rate limit are scoped to. What changes is that
answering it is no longer how a caller finds something to *run*.

### Selecting a model is what fixes the vision case structurally

Asked for a vision-capable model, `select_model` returns a row whose own
`has_vision` is true. For Groq that is the vision model, never the blind chat
model, so the caller can send the selected model's code on the wire without
consulting the catalog and without depending on a client-side substitution. The
rescue in `vision_completion` remains for callers that pass no model; it stops
being load-bearing for callers that do.

### The event log names the model

The orchestrator's contribution to the transport's row was
`ai_provider:<code>,fallback:<bool>,after:<code>`. It now carries the model on
both sides — `ai_model:<code>`, and `after:<code>` naming a model — because the
provider no longer identifies what ran. A chain staying on one vendor produces
two rows with the same `ai_provider` tag, indistinguishable without it.

## Alternatives considered

**Keep the provider chain and seed sensible defaults.** The smallest change that
makes the advertised feature fire, and not taken deliberately: it would seed a
structure that cannot express the hop worth seeding most — the cheaper model on a
key you already hold — so the seeds would be rewritten by the redesign they
postponed. The emptiness and the wrong unit are one defect, not two.

**Derive the chain instead of storing it** — "the next cheapest model of the same
provider, then the next cheapest anywhere". Needs no configuration and can never
be empty. Rejected because the cheapest sibling is frequently wrong: a smaller
model may not hold the context the prompt needs, may lack the vision or
function-calling the caller depends on, or may be the one already rate-limiting.
A chain is an operator's statement about acceptable degradation, and this fork
has no data to infer it from.

**Accept a chain per call and store nothing.** `execute_with_fallback` already
takes `fallback_chain`. It keeps the schema still and moves the decision to the
code that knows the request, and loses the property that makes the feature worth
having: degradation policy is a deployment concern, tuned by whoever watches the
bill and the incident, and code is the one place they cannot change it.

**Keep `fallback_provider_ids` beside the new field.** Rejected as the shape this
register exists to prevent — two fields answering one question, drifting apart,
with `execute_with_fallback` deciding which wins when both are set. Nothing
outside this module set the old field, so there is no compatibility to keep.

## Consequences

- A fallback can stay on the vendor whose key is already configured — the common
  case, and the one the old relation could not hold.
- The chain is a chain of what executes, so a caller naming a model on the wire
  names the correct one on every hop.
- `request_func(client, provider)` becomes `request_func(client, model)`. The
  signature is consumed outside this repository — the OCR module in the agromarin
  repository is the one caller — and that module changes with it.
- An `ai.model` may be referenced by other models, so removing one is no longer
  purely local; the relation is `ondelete` cascade on both sides of the join
  table, which drops the hop rather than the chain.
- Selection can return a model whose provider differs from the vendor a caller
  might have guessed at. That is the intent, and the event log names both.
- The chain still ships empty. This makes it expressible and correct; what an
  operator's acceptable degradation is remains theirs to state.

## Enforcement

`api_ai/tests/test_ai_orchestrator.py` covers the walk, the retry classification
and the ranking; `api_ai/tests/test_orchestrator_event_log.py` covers the
annotations, including the case the provider tag alone cannot distinguish — two
hops on one vendor.

**What nothing enforces:** that a configured chain degrades sensibly. A chain may
name a model with a smaller context window than the prompt needs, and the
fallback will fail the same way the primary did. That is a judgement about a
workload; the log names every hop so a bad chain is visible after the fact.
