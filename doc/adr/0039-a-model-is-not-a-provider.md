# ADR-0039: A model is not a provider — cost and capability follow the name, not the key

- **Status:** Accepted
- **Date:** 2026-08-15

## Context

`api_ai` reached vendors through `ai.provider`, one record per vendor,
`_inherits`-delegating to `api.endpoint.outbound` for the URL, the credential and
the transport. On top it carried, at this decision: `has_vision`,
`has_embeddings`, `has_audio`, `supports_streaming`, `supports_function_calling`,
`max_context_window`, `max_output_tokens`, four cost fields, three 1-to-5
ratings, a free-tier pair, `default_model` and `available_models`.

Most of that is not a property of a vendor. It is a property of a *model*, and
there was one row per vendor to hold it.

Which model actually ran was decided elsewhere: `BaseAIClient._resolve_model`
resolved it per call — the caller's argument, then `default_model`, then the
catalog's `chat_model`, then a class constant — so the model was a string
parameter, never a record, and nothing tied it to the numbers the record carried.

### The record described one model and was named after the vendor

The seeded Claude row carried one input price, one context window and one
accuracy rating, while its `available_models` listed five model names sharing
none of those three values. The row described whichever model `default_model`
happened to name, and answered to the vendor's name.

`available_models` was a comma-separated `Text`. Measured 2026-08-15, nothing
read it but the provider form view.

### The catalog had already outgrown the shape

`api_ai/tools/vendor_catalog.py` describes how each vendor is spoken to. Its Groq
entry carried both a `chat_model` and a separate `vision_model`, with the comment
that the text model is blind. The corresponding provider record carried
`has_vision` true.

Both were accurate about different models. The record's flag described the vision
model; the model the record would run could not see. The dict grew a second slot
the moment one model per vendor stopped being enough; the record had no way to.

### The conflation had already cost money once

`migrations/19.0.1.1.0` through `19.0.1.8.0` include one written for exactly this
failure: `default_model` for OpenAI had been seeded with one model while the
catalog named another, and its docstring records the consequence — a sixteenfold
difference in input price, decided by which entry point the caller used. Two
models, one vendor, one record.

That fix made the catalog authoritative for the *default* and pinned the seed
against it. It did not give a second model anywhere to live.

### Selection and execution consulted different sources

`AIOrchestrator._optimize_selection` ranked candidates on `cost_per_1m_input`,
`accuracy_rating` and `speed_rating`. The model was resolved afterwards, by
`_resolve_model`, from an order the orchestrator never consulted. A caller asking
to optimise for cost could be given a provider chosen on one model's price and
then run another — and within a vendor's line-up the two are not close.

### A test enforced the conflation

`api_ai/tests/test_registry_coherence.py` asserted a provider's `has_vision`
equalled the catalog's `vision` key. Groq satisfied it while being wrong about
the model it would run. The guard was pointed at the level at which the fact is
not decidable.

## Decision

**`ai.model` — one record per model a caller can actually run, with a required
`provider_id`.** `ai.provider` keeps the endpoint, the credential and what an
account decides; the model record takes what a model name decides.

The boundary is one question, and every field answers one side: **does this value
change when you swap the API key, or when you swap the model string?**

Key-decided, staying: the endpoint delegation, `reliability_rating` (uptime is
the vendor's), the free-tier pair (an account property), `best_for_tag_ids` (a
routing hint). Name-decided, moving: the four cost fields, the context window and
output cap, `has_vision`, `supports_function_calling`, `supports_streaming`,
`accuracy_rating`, `speed_rating`. `default_model` becomes a `Many2one`;
`available_models` is deleted rather than migrated.

### Two capability flags are honestly both, and become stored roll-ups

`has_vision` and `has_audio` are model-level facts callers legitimately ask at
the vendor level — *can I get vision out of this vendor at all* is what a
candidate filter asks. They stay on `ai.provider` as computed Booleans over the
provider's model rows.

They must be **stored**. `AIOrchestrator.select_provider` turns
`required_capabilities` into a search domain, and `api_ai_agent` in the
enterprise repository searches providers on `has_embeddings`. A non-stored
compute has no column to search and both callers break at query build.

The roll-up is what makes Groq expressible: the provider answers true (some model
of its can see) and its chat model answers false. Both were previously crushed
into one bit, and the bit was wrong for the model that ran.

**`has_embeddings` is the third flag and is NOT a roll-up**, which is worth
stating because deriving all three is the symmetric-looking answer. Nothing in
this module reaches an embedding endpoint — no client class implements one, the
catalog describes none — so there is no model row to derive it from, and
inventing one would mean seeding a model name copied out of another repository's
table. It stays an ordinary Boolean asserted per vendor, and its help text says
so. A flag with no reader in this module is a vendor claim a *different* module
consumes; dressing it as derived would assert a model this module cannot run.

### The orchestrator ranks the model it will run

`_optimize_selection` reads `cost_per_1m_input`, `accuracy_rating` and
`speed_rating` through `default_model_id`. The numbers a provider is chosen on
are the numbers of the model the request will execute.

### The seed is the catalog's models, and nothing else

`available_models` named models this fork has never called. Seeding a record for
each would assert a price, a context window and an accuracy rating nobody
measured — manufacturing the drift the OpenAI migration was written to stop, with
more columns to drift in.

So the seed is one row per model `vendor_catalog.PROVIDERS` actually names — its
`chat_model`, and its `vision_model` or audio model where the entry has one.
Every seeded row is a model the code can reach. A deployment running a different
model adds a row carrying the numbers it is actually billed, which is the point
of making this configuration rather than source.

### Model names are unique within a provider, not globally

Two vendors serve the same open-weights model, and one vendor may appear as two
provider records where it offers both a native and an OpenAI-compatible wire.
Uniqueness is scoped to `provider_id`, in both the code constraint and the
inherited catalog name rule — the scoped re-declaration `catalog.mixin`
documents for a catalog whose names are unique only within a parent.

## Alternatives considered

**Add per-model columns to `ai.provider`** — a `vision_model` beside
`default_model`, a `vision_cost` beside the chat cost, mirroring the catalog
dict. No new table, no migration. It loses because the column count grows with
the number of model *kinds* while still being unable to express two models of the
*same* kind, which is the ordinary case: a cheap chat model and an expensive one,
both reachable, differing in every field. The one-model-per-vendor assumption
spelled longer.

**Keep models in `vendor_catalog.PROVIDERS` only, adding no records.** Cheapest,
and the catalog was already the maintained copy. It loses twice: the catalog is
source code and per-model pricing is deployment data — a company on a negotiated
rate has nowhere to record it, and price changes arrive by upgrade — and
`AIOrchestrator` selects and ranks *recordsets*, so it cannot sort a dict, filter
it by company credential, or let an administrator deactivate one entry.

**Adopt the shape upstream already uses.** The `ai` module in the enterprise
repository carries a provider table whose entries hold `(code, label)` model
pairs — containment as data, no schema change. Worth citing as prior art for the
containment, and it loses for the reason this record exists: those pairs carry no
cost, no context window and no capability. They feed a picker. The absence of
exactly those fields produced the sixteenfold incident.

**Let each consumer store the model it wants, and leave `ai.provider` alone.**
Attractive because the consumers are few. It distributes one fact across every
caller — the OCR module in the agromarin repository, the Telegram bot module
beside it, and `api_ai_agent` in enterprise would each hold an answer to "what
does this cost" — and every copy drifts. This module's history is three
consolidations of exactly that shape: duplicated JSON parsing, duplicated wire
readers, and the triplicated default model.

**Do nothing, and document that `ai.provider` means "this vendor on its default
model".** Honest and free. It leaves `optimize_for="cost"` correct only while no
caller passes an explicit model, with nothing to stop one, and leaves Groq's
vision flag wrong about the model that runs — an error prose cannot retract.

## Consequences

- The economics an administrator reads and the economics the orchestrator ranks
  on become the same numbers as the model that runs. They were not before.
- A deployment can record what it is actually billed, per model.
- A vendor whose vision and chat models differ becomes expressible without a
  special case, and its capability question is answerable at both levels.
- `available_models` is deleted. It described models nobody had measured, and
  the new table is worse than useless filled with the same guesses.
- Cost is paid outside this repository. The OCR module in the agromarin
  repository reads a provider's vision flag and default model directly, and
  `api_ai_agent` in enterprise searches on the embeddings flag. The stored
  roll-ups keep both compiling; the first still needs its two reads retargeted at
  the model. That external cost is why this is a record rather than a commit
  message.
- An existing database needs a data migration, and the provider seed is
  `noupdate`, so an administrator's overridden `default_model` must be rescued
  rather than replaced.
- **The fallback chain is now visibly the wrong unit, and stays wrong for the
  moment.** `execute_with_fallback` walks providers, but what executes is a
  model; a caller that pins an explicit model has it carried unchanged to
  whichever vendor answers next. This record makes the mismatch legible and
  leaves it to its own decision, because changing the orchestrator's signature
  and moving twelve columns in one step is how a migration becomes unreviewable.

## Enforcement

`api_ai/tests/test_registry_coherence.py` is the natural home: it exists to stop
the registries that name vendors from disagreeing, and gains the model table as a
fourth. Its default-model assertion moves from comparing a string to comparing
the related record's code, and its vision assertion moves from the provider to
the vision model row — where Groq stops being the case the guard excuses and
becomes the case that proves it.

**What nothing enforces:** that a seeded model's price is the price the vendor
charges. No test can reach a rate card, and a stale cost is invisible until a
bill arrives. The mitigation is scope, not verification — seed only models the
catalog names, so the set stays small enough to re-check by hand.
