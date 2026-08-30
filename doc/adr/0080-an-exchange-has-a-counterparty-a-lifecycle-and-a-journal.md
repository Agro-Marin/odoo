# ADR-0080: An exchange has a counterparty, a lifecycle and a journal, and none of the three is a localisation

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

ADR-0078 consolidated the format layer: `odoo/libs/documents` answers what bytes
are, what can be read out of them, and what bytes to produce. It is symmetric and
gated. The censuses behind it — document ingestion and data egress, both in the
AgroMarin knowledge vault under research, dated 2026-08-29 — stopped at the same
boundary without saying so. They answered *what the document is*. Neither asked
*who we are sending it to*.

A third census, dated 2026-08-30, asked. Measured against `odoo` @ `71ed9938cfa`,
`enterprise` @ `d3177a7fd31`, `agromarin` @ `57b88c082`:

**Forty-seven distinct state vocabularies across seventy-six fields**, in modules
whose names carry a clearance or interchange token. They are the same five phases
spelled forty-seven ways — `to_send` / `ready` / `pending` / `invoice_not_indexed`
for one of them, `accepted` / `valid` / `done` / `confirmed` / `invoice_validated`
for another.

**The modelling error is legible in the longest one.** `l10n_mx_edi.state` carries
sixteen values that are exactly `{invoice, global invoice, payment} × {issue,
annul} × {ok, failed}`, flattened into a string. Three orthogonal facts as one
Selection, so every predicate over any one of them is a string prefix test.
`l10n_hu_edi` needed `cancel_sent`, `cancel_timeout` and `cancel_pending` because
the annulment lifecycle had nowhere to live except inside the issuing field.

**Ten private transmission models, 8410 lines, no shared line.** Every one is
`(subject, intent, phase, when, payload, counterparty reference, message)`. The
only variable is what the counterparty calls its reference — `uuid`,
`mydata_mark`, `chain_index`, `zip_key`, `identifier`, `attachment_uuid`. That is
one field, not ten models. A name sweep for `l10n_*_edi*` finds only seven of
them; `l10n_co_dian`, `myinvois` and `l10n_id_efaktur_coretax` are the same model
under a name the sweep cannot match, which is ADR-0048 arriving from the other
direction.

**Sixty-three crons doing five jobs.** Eleven poll an inbox, thirteen poll for a
verdict, nine drain an outbound queue, two refresh an OAuth token —
a feature `api.endpoint.outbound` already has — and six keep a registration
alive.

**One hundred and twenty-four modules dial out with raw `requests`; four keep a
record.** `api_transport`, 4854 lines this fork wrote, already provides per
endpoint: bearer / HMAC / OAuth 2.0 / basic / digest auth, IP allowlisting, rate
limiting, exponential backoff with an attempt cap, a response cache with health
tracking, TLS policy with a private-address guard, secret redaction, and
`api.event.log` — with `retry_count`, `date_next_retry`, `trace_id`, a
size-capped payload hash (ADR-0066), duplicate detection and a working retry
cron.

**Twenty-one fiscal modules hold a secret in a plain `Char`.**
`credential.credential` — encrypted, fingerprinted, access-logged — has eighteen
consumers and one of them is fiscal. The certificate half went the other way:
`certificate.certificate` has thirteen fiscal consumers, because someone
consolidated it.

### The distinction the forty-seven keep losing

`api.event.log` carries a `state` of `pending | processing | success | failed |
duplicate | retry`. That is the **transport** lifecycle: did the call complete. It is not the
**verdict** lifecycle: did the counterparty accept. An HTTP 200 carrying
`<Estado>Rechazado</Estado>` is a transport success and a business rejection, and
no single Selection can be both.

Three of the forty-seven do not model the verdict at all —
`l10n_rs_edi` (`sent | sending_failed`), `l10n_gt_edi` (`invoice_sent |
invoice_sending_failed`) and `l10n_jo_edi` (`to_send | sent | demo`). A document
those modules report as `sent` may have been refused. Others lose the transport:
`l10n_hu_edi`'s `send_timeout` is a verdict value meaning "we never heard back".

## Decision

**`addons/exchange` holds the conversation, once, for every counterparty
that has one.** It depends on `api_transport` and `certificate`, and sits above
`odoo/libs/documents`. Four concepts:

**`exchange.channel` — who, and with what secret.** One record per (company,
counterparty, environment). It *delegates* to `api.endpoint.outbound` through
`_inherits`, as `ai.provider` does (ADR-0039), and points at
`credential.credential` and `certificate.certificate`. Its own fields are only
what a counterparty decides that an endpoint does not: the protocol, the
participant identifier, the annulment window, whether documents chain, whether
there is an inbox. `counterparty` carries ADR-0048's three categories on the
record rather than in a module name.

**`exchange.transmission` — what happened, with the two facts kept apart.**
`intent` is what we are asking for (`issue`, `annul`, `amend`, `query`); `state`
is where that ask has got to (`draft`, `queued`, `sent`, `accepted`, `rejected`,
`expired`). They are separate fields because they are separate facts. An
annulment that failed is `intent=annul, state=rejected` — a second row, not five
more values in the issuing field.

**It does not inherit `api.event.log`; it points at it.** Two models, two
lifecycles, one shared mechanism. A constraint says an accepted transmission
cannot stand on a failed call, which is the one relation between them that is
always true. What is shared is already written: the `(state, date_next_retry)`
queue index, `compute_payload_hash`, and `mixin.api.channel`'s backoff.

**`exchange.protocol` — how, as an `AbstractModel` registry.** The mechanism
`account.edi.xml.*` already proves and ADR-0078 chose for readers: discovered
from the registry, never dispatched from a literal. Six methods —
`_prepare_message`, `_check_message`, `_seal_message`, `_send_message`,
`_read_verdict`, `_read_inbox`. The thirty-one spellings of `_send` become one
`_send_message` per protocol; the forty spellings of `_cancel` become
`_prepare_message` on an `intent="annul"` transmission.

**`mixin.exchange.subject` — what a business record carries.** Its fields are all
computed and unstored, so a model gains them without a migration.

**Three crons replace forty-one**: drain the queue, read the verdicts, read the
inboxes. Each iterates channels and calls the protocol.

## Alternatives considered

**Extend `account_edi` rather than write a new addon.** Rejected. `account_edi` is
the first of three generations and the one seventeen modules route around — seven
by extending `account.edi.format`, ten by writing a private transmission model. It
is also bound to `account.move`, and the subjects here include `stock.picking`,
a payslip and a point-of-sale order. Building on it would mean every non-accounting
subject taking an `account` dependency to record that a file was sent.

**Put the lifecycle on `api.event.log` and add the missing fields.** Rejected, and
this is the alternative most likely to be proposed again. It reads as the cheaper
move — the retry, the hash, the queue index and the correlation id are all there.
But that `state` answers whether a call completed, and no value can be
added to it that answers whether a counterparty accepted without making the field
mean two things at once. That is precisely the defect this record exists to stop,
and `l10n_mx_edi`'s sixteen values are what it looks like at scale. `origin_model`
and `origin_record_id` are also a `Char` and an `Integer` — the transport journal
can mention an `account.move`, never hold one — and giving it a real relation
would put an accounting dependency inside `api_transport`.

**A per-country `.document` model with a shared abstract base.** Rejected. It is
what the tree already has, minus the sharing, and the sharing is the part that
does not survive: ten models with ten tables means the queue cron, the retry
policy and the reporting are still per-country. One table with a `protocol`
column is what makes three crons possible.

**Name the module `edi`.** Refused by ADR-0048, correctly. Seventy-one of the
seventy-nine modules carrying that word have a government as their counterparty,
which is not interchange. An exchange has a counterparty of any kind, and
`counterparty` is a field on the channel precisely so the distinction is data.

**Keep the state Selections and add a mapping layer.** Rejected. A mapping from
forty-seven vocabularies to one is forty-seven pieces of code that must each stay
correct, and nothing would gate them. The vocabularies are not a compatibility
surface — they are internal fields on `account.move` — so there is no external
consumer to preserve them for.

## Consequences

**Delegation gives fields, not behaviour, and this cost two defects in the first
draft.** `_inherits` made `name`, `company_id`, `environment` and the retry policy
*fields* available on `exchange.channel` while leaving `action_test_connection`,
`should_retry` and `calculate_retry_delay` unreachable — the first failed view
validation at install, the second failed a test. `exchange.channel` now forwards
the three explicitly. Any future consumer of a delegated model should expect the
same split.

**A SQL `UNIQUE` cannot name a delegated field.** `UNIQUE(protocol, company_id,
endpoint_id)` on `exchange.channel` produced `column "company_id" named in key
does not exist` — logged as an `ERROR` while the install exited 0, so the
constraint silently did not exist. It is a Python `@api.constrains` now. The
general rule: a table object may only name columns of its own table, and
`_inherits` puts them on another.

**A transmission's `reference` is uniquely indexed only where it is set**, on
`api.event.log._event_external_unique`'s pattern. A full `UNIQUE` would collide
every draft.

**Migration is per-module and none of it is forced.** A localisation keeps its own
fields until someone ports it; `mixin.exchange.subject` adds no column, so
adopting it is not a schema change. The order is smallest first —
`l10n_gt_edi` (37 lines), `l10n_id_efaktur_coretax` (93), `l10n_gr_edi` (103) —
with `l10n_mx_edi` last, because 3508 lines and sixteen states is where a wrong
contract is most expensive to discover.

**`account_edi` does not retire in this record.** It is the obvious next step and
it is a separate decision with its own blast radius: seven `account.edi.format`
inheritors and a queue `account.move` reads.

## Enforcement

`.github/workflows/integration_tests.yml` runs the suite in the small-suites lane,
as ADR-0079 requires — 42 tests covering the lifecycle, the retry cap, the
transport/verdict constraint, the registry and the rollup.

`tooling/architecture/module_suite_lane.py` holds the module to that lane; without
the entry the count rises and the `suite_lane` ratchet fails.

A gate counting `Selection` fields named `*state` in a module carrying an exchange
token — default-deny over an allowlist, on `edi_vocabulary.py`'s pattern — is the
mechanism that keeps a forty-eighth vocabulary from appearing. It is not yet
written; until it is, this record is what a reviewer cites. Writing it means
deleting its entry from `UNRECORDED_GATES`, which is why the record comes first.
