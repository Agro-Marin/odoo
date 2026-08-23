# Architecture Decision Records

An **ADR** captures one significant architectural decision: its context, the
choice made, and the consequences. A record is immutable from the moment it
leaves `Draft` — to change a decision, add a new ADR that supersedes the old one
and mark the old one `Superseded by ADR-XXXX`. `Draft` is the one editable
state, and it exists so that "still being written" does not have to borrow a
status that promises more than it means.

## When a decision needs a record

A record is required when a decision **constrains future work in a way the code
does not state plainly**. The test is not how much effort the change took; it is
whether a competent newcomer, reading only the tree, would propose undoing it.
If they would, the argument they are missing belongs here.

Required:

- **A new CI-blocking gate**, or a material widening of an existing one's scope.
- **A new package, layer or dependency direction** in core — anything that
  changes what may import what.
- **A cross-cutting mechanism**: a seam other packages or addons must consume,
  as opposed to a facility they may.
- **A change to a public surface** — the façades, an inheritance contract, a
  route family — where the cost is paid by code outside this repository.
- **Mandatory infrastructure**: a build step, a native extension, an interpreter
  floor, a driver choice. The mark is that a checkout without it does not run.
- **A decision whose rejected alternative is plausible.** If the option not
  taken is one a reasonable reviewer would propose, the record exists to stop it
  being re-litigated. This is what `Alternatives considered` is for, and the
  strongest single reason to write a record at all.

Not required:

- **A bug fix**, however subtle. The fix goes in the tree with its regression
  test; the reasoning goes in the commit message.
- **A refactor inside a layer** that moves no dependency direction and renames
  nothing public.
- **A naming or style rule.** That is `doc/coding_guidelines.rst`'s job, and
  splitting rules across two authorities is how both stop being read.
- **Anything the tree already states plainly.** A record that restates what a
  reader would find in the code is a second copy, and the second copy drifts.

**Coverage is measured, not assumed.** Left to inclination, a register fills up
wherever its authors happened to be working. Measured 2026-08-14, this one
argued for the Python import boundaries of the core and for the enforcement
philosophy, and for very little else the fork gates: the JS checkers in
`tooling/architecture/`, the mandatory Rust extension in `crates/` and the JS
test runner carried no record between them.

So the gap is counted. Every runnable gate in `tooling/architecture/` declares a
module-level `ADR`: the record that argues for it, or `unrecorded`.
`test_gate_adr_coverage.py` requires a cited record to exist and be `Accepted`,
and pins the unrecorded set **drift-zero and one-way** — a new gate must name its
record or be added to that set deliberately, and writing one up means deleting
its entry, so the number can only fall. `layer_check.py` does the same per
*contract*, pinned by `test_layer_check.py`.

**The backlog is the register's own to-do list.** It stood at 34 of 36 gates
when the pin was introduced on 2026-08-14, and the JavaScript client
architecture was twenty of those. Writing the first of them up (ADR-0019)
cleared **five**, not most: the twenty are not one argument with twenty
enforcement points — layering, public surface, extension and patch discipline,
and render behaviour are separate decisions, and a record stretched to cover all
of them would cite gates it does not argue for. Expect roughly one record per
cluster. Read the current count from the pin, not from this paragraph.

## Claiming a number

Numbers run contiguously from 0001 — no gaps, no duplicates, gated by
`test_numbers_are_contiguous_from_one`. Several sessions typically work this
checkout at once, so the rule that matters is who gets the next one.

**A number is claimed by committing the file and its index row, not by starting
to write.** Commit the skeleton as soon as the subject is settled — a status, a
date and a Context is enough — then fill in the argument. The claim is visible
to everyone who pulls, and a collision surfaces as a merge conflict on this file
rather than as a record silently overwritten.

**If your number is taken by the time you commit, renumber.** A record's number
is not part of its identity: renumbering is a filename change and one index row,
and nothing else addresses a record by number except a contract naming one that
has already landed. Never renumber someone else's committed record to make room,
and never leave a gap to avoid the edit — the gate rejects both.

**A number is never reused, and a record is never deleted.** A decision that
lost still spent the argument, and deleting it breaks contiguity and destroys
the reason the next person will need when they propose the same thing again.
Where a later record won, the loser keeps its number and is marked `Superseded
by ADR-YYYY`. Where nothing replaced it — a proposal abandoned — the status is
`Withdrawn`, and an amendment says what abandoned it.

## Status is a claim about the tree, not a mood

| Status | Means | Gated? |
|---|---|---|
| `Draft` | Being written, and **not yet a decision**. The one editable state: revise it freely, and let git carry the history. No contract may cite it. | exempt from the existence check |
| `Proposed` | The decision is argued but **not built**. Naming code that does not exist yet is correct here. | exempt from the existence check |
| `Accepted` | The decision is **in the tree**. Every file, symbol and model the record names resolves. | `test_adr_coherence.py` enforces it |
| `Superseded by ADR-YYYY` | Replaced. Kept for the history. | as `Accepted`, until superseded |
| `Withdrawn` | Proposed, argued, and **abandoned** — nothing replaced it. Kept for the argument; an amendment says why. No contract may cite it. | exempt from the existence check |

Those five are the whole vocabulary, pinned by `test_status_kind_is_known`.

**`Withdrawn` exists because `Proposed` was doing its job.** A proposal nobody
pursues sits at `Proposed` indefinitely — exempt from the existence check, and
indistinguishable from one still being worked on. That is
fiction-with-an-exemption arriving through the status word rather than through
the prose. Withdrawing is not a failure state: the argument was made, it lost or
was overtaken, and the record is worth keeping for that.

**`Draft` exists because the alternative was happening anyway.** A record under
active revision was being parked at `Accepted` or `Proposed` — statuses that
make a promise about the tree — and then quietly rewritten, which is the one
thing immutability forbids. A `Draft` carrying a `**Revised:** YYYY-MM-DD` line
is welcome; on any other status a revision is an Amendment or a supersession,
never an edit.

**Citing code outside this repository.** Several decisions span repos. The
existence check resolves names against *this* checkout, and CI checks out this
repository alone, so a name in `enterprise/` or `agromarin/` cannot be verified
here. Teaching the gate to load them would be worse: it would pass silently
wherever the siblings are absent, which is green-while-verifying-nothing. So the
rule is a writing convention. Name sibling code in prose or by bare module name,
never as a rooted path or a dotted model name — those shapes assert
verifiability the register does not have, and a reader is entitled to assume a
backticked path was checked. Say which repository it lives in, so the claim is
attributable even though it is unverified.

`Accepted` is earned, not assigned at commit time. `TestReferencedNamesExist`
resolves every backticked path, `name()` and dotted model name in an `Accepted`
record against the tree, so the cheap way past the gate is to be honest about
status. The rule exists because ADR-0012 and ADR-0013 sat at `Accepted` for a
week describing a subsystem this repository has never contained.

## Three rules that keep a frozen record from rotting

**An ADR is past tense; `doc/architecture/ARCHITECTURE.md` is present tense.**
The rule the other two follow from. An ADR says *on this date, given these
forces, we chose X over Y* — a claim about a moment, and therefore true forever.
`doc/architecture/ARCHITECTURE.md` says *this is how the system is today* — a
claim about now, which is why it is gated and re-derived. **A sentence in an ADR
written in the present tense about the tree is a bug**: the record is immutable
and the tree is not, so it can only become false, and nothing will notice. Write
"at this decision the count was N", not "the count is N"; "run the checker", not
"currently clean at zero". Gated by
`test_adr_coherence.TestNoLiveStatusClaims`.

**Never restate a number that lives somewhere else.** Ratchet floors, contract
counts and file counts belong to `tooling/ratchet/baselines/*.json` and
`layer_check.py`'s `CONTRACTS`. Cite the file, not the value. Every count
written into an ADR body so far has since gone stale, and one — ADR-0006's mypy
figure — never matched the baseline committed beside it. A *dated* measurement
is not a restatement and is welcome: "measured 2074 on 2026-06-25" stays true,
"the count is 2074" does not.

**Corrections go in an append-only `## Amendments` section.** Immutability
protects the *decision*, not a path that has since moved. An amendment is dated,
never edits the argument above it, and may correct a citation in place when it
says so.

These records document the framework-core architecture of the `19.0-marin` fork.
The companion overview is
[`doc/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md); the
boundaries several of these ADRs establish are enforced by
[`tooling/architecture/layer_check.py`](../../tooling/architecture/layer_check.py).

ADRs 0001–0004 are **retroactive**: they record decisions already embodied in
the code, written down so the reasoning is not lost. ADR-0005 is the decision to
enforce them.

| ADR | Title | Date | Status |
|-----|-------|------|--------|
| [0001](0001-layered-orm.md) | Layered ORM (Layer 0–3) | 2026-06-23 | Accepted |
| [0002](0002-pure-python-orm-components.md) | Pure-Python ORM components with dependency injection | 2026-06-23 | Accepted |
| [0003](0003-packagize-sql_db-into-db.md) | Decompose `sql_db.py` into a `db/` package | 2026-06-23 | Accepted |
| [0004](0004-libs-vs-tools-split.md) | `libs/` (agnostic) vs `tools/` (Odoo-coupled) split | 2026-06-23 | Accepted |
| [0005](0005-enforce-architecture-boundaries-in-ci.md) | Enforce architectural boundaries in CI | 2026-06-23 | Accepted |
| [0006](0006-ratchet-countable-quality-gates.md) | Drift-zero ratchet for countable quality gates | 2026-06-25 | Accepted |
| [0007](0007-db-backed-integration-test-gate.md) | DB-backed integration test gate | 2026-06-25 | Accepted |
| [0008](0008-enforce-facade-boundary.md) | Enforce the public façade boundary (`odoo.addons` → `odoo.orm`) | 2026-06-25 | Accepted |
| [0009](0009-close-the-enforcement-loop.md) | Close the enforcement loop (mainline gating, full façade scope, true floors) | 2026-06-25 | Accepted |
| [0010](0010-consolidate-cache-compute-access-surfaces.md) | Consolidate the internal cache/compute access surfaces around `env._core` | 2026-06-26 | Accepted |
| [0011](0011-persistence-backend-port.md) | Persistence backend port (`env.backend`) | 2026-06-26 | Accepted |
| [0012](0012-attachment-storage-layers.md) | Attachment storage layers (object store, key policy, delivery) | 2026-07-30 | Withdrawn |
| [0013](0013-content-placement.md) | Content placement — where an attachment's bytes are, as data | 2026-07-30 | Withdrawn |
| [0014](0014-packagize-service-db.md) | Packagize service/db.py into `odoo/service/db/` | 2026-08-08 | Accepted |
| [0015](0015-batch-reservation-in-action-assign.md) | Decide a batch's reservation before writing any of it | 2026-08-08 | Accepted |
| [0016](0016-root-modules-are-foundational.md) | The root modules are foundational | 2026-08-09 | Accepted |
| [0017](0017-two-inbound-webhook-mechanisms.md) | Inbound HTTP — one gate, two dispatchers | 2026-08-12 | Accepted |
| [0018](0018-upstream-is-a-baseline.md) | Upstream is a baseline — there is no merge, and none is wanted | 2026-08-14 | Accepted |
| [0019](0019-client-layering.md) | Client layering — a rank in `web`, a bundle subset in `mail`, on both graphs | 2026-08-14 | Accepted |
| [0020](0020-client-public-surface.md) | Declare the client's public surface — the set, the entry point, and the override points | 2026-08-14 | Accepted |
| [0021](0021-closure-services.md) | A service's own callers go through its facade, and its facade should be an instance | 2026-08-14 | Accepted |
| [0022](0022-objects-passed-by-value.md) | An object passed by value is an interface — declare `archInfo`, `env.config` and the field record | 2026-08-14 | Accepted |
| [0023](0023-tests-follow-their-source.md) | A moved file must not silently disconnect its tests | 2026-08-14 | Accepted |
| [0024](0024-mixin-composition-is-a-coupling-surface.md) | Mixin composition is a coupling surface, and it has no import edges | 2026-08-14 | Accepted |
| [0025](0025-function-length-budget.md) | Budget function length — and ratchet the excess, not the offenders | 2026-08-14 | Accepted |
| [0026](0026-a-module-must-evaluate-to-something.md) | A source file must never be its own generated bridge | 2026-08-14 | Accepted |
| [0027](0027-forced-render-hides-unsubscribed-reads.md) | A forced render is not a stronger render — it hides unsubscribed reads | 2026-08-14 | Accepted |
| [0028](0028-the-underscore-is-a-claim.md) | In client code the underscore is a claim, and it is budgeted | 2026-08-14 | Accepted |
| [0029](0029-dependencies-without-import-edges.md) | Inventory the dependencies that produce no import edge | 2026-08-14 | Accepted |
| [0030](0030-documentation-is-re-derived.md) | Documentation that describes the tree is re-derived against it | 2026-08-14 | Accepted |
| [0031](0031-a-symbol-a-consumer-imports-must-exist.md) | A symbol a consumer imports must still exist — including across repositories | 2026-08-14 | Accepted |
| [0032](0032-half-the-client-graph-is-xml-strings.md) | Half the client's dependency graph is written in XML, as strings | 2026-08-14 | Accepted |
| [0033](0033-naming-vocabulary-is-counted-not-blocked.md) | The naming vocabulary is a count, and only the decidable part of it | 2026-08-14 | Accepted |
| [0034](0034-the-core-import-graph-is-acyclic.md) | The core's import graph is acyclic, which direction alone does not give | 2026-08-14 | Accepted |
| [0035](0035-odoo-rust-is-mandatory.md) | `odoo_rust` is mandatory, and a stale build is refused at import | 2026-08-14 | Accepted |
| [0036](0036-one-interpreter-and-a-gil-free-future.md) | One supported interpreter, and an ORM being made ready for its GIL-free build | 2026-08-14 | Accepted |
| [0037](0037-the-gate-records-its-own-verdict.md) | The inbound gate records its own verdict | 2026-08-15 | Accepted |
| [0038](0038-a-webhook-action-may-go-through-an-endpoint.md) | A webhook server action may go through a configured endpoint | 2026-08-15 | Accepted |
| [0039](0039-a-model-is-not-a-provider.md) | A model is not a provider — cost and capability follow the name, not the key | 2026-08-15 | Accepted |
| [0040](0040-the-fallback-chain-is-a-chain-of-models.md) | The fallback chain is a chain of models, and the orchestrator selects one | 2026-08-15 | Proposed |
| [0041](0041-prose-figures-are-machine-maintained.md) | A figure stated in prose is regenerated, not retyped | 2026-08-16 | Accepted |
| [0042](0042-t-out-on-a-recordset.md) | What `t-out` should render when the value is a recordset | 2026-08-16 | Proposed |
| [0043](0043-machine-doc-figures-are-gated-or-frozen.md) | A machine-doc figure is gated or frozen, never bare | 2026-08-16 | Accepted |
| [0044](0044-a-zero-count-assertion-names-a-class-the-tree-declares.md) | A zero-count assertion names a class the tree declares | 2026-08-17 | Accepted |
| [0045](0045-duplication-is-measured-not-reviewed.md) | Duplication is measured, not reviewed | 2026-08-17 | Accepted |
| [0046](0046-a-presentational-component-takes-its-data-as-props.md) | A presentational component takes its data as props | 2026-08-18 | Accepted |
| [0047](0047-a-component-directory-is-entered-at-a-face.md) | A component directory is entered at a face | 2026-08-18 | Accepted |
| [0048](0048-edi-names-three-things.md) | "EDI" names three things, and only one of them is interchange | 2026-08-18 | Accepted |
| [0049](0049-a-field-hook-is-named-for-its-field.md) | A field hook is named for the field it serves, and the count says how far that is true | 2026-08-19 | Accepted |
| [0050](0050-a-domain-is-its-own-family.md) | A domain is its own family, and `domain=` is a field hook like the rest | 2026-08-19 | Superseded by ADR-0054 |
| [0051](0051-a-field-hook-does-one-job.md) | A field hook does one job, and the ones that do two are counted | 2026-08-19 | Accepted |
| [0052](0052-a-count-of-an-x2many-is-a-field.md) | A count of an x2many is a field, not a compute | 2026-08-19 | Accepted |
| [0053](0053-the-vocabulary-reaches-public-model-methods.md) | The naming vocabulary reaches public model methods, and renaming one is a surface change | 2026-08-19 | Accepted |
| [0054](0054-a-domain-builder-leads-with-its-object.md) | A domain builder leads with its object, not with a suffix | 2026-08-20 | Accepted |
| [0055](0055-in-over-a-tuple-is-the-builders-job.md) | `IN` over a bound value goes through the SQL builder | 2026-08-20 | Accepted |
| [0056](0056-stored-python-is-a-binding-no-checkout-holds.md) | Stored Python is a binding no checkout holds, and `_for_xml_id` is renamed across it | 2026-08-20 | Accepted |
| [0057](0057-a-count-asked-only-whether-it-is-nonzero.md) | A count asked only whether it is nonzero takes a limit | 2026-08-21 | Accepted |
| [0058](0058-a-call-resolves-to-something-this-checkout-defines.md) | A call resolves to something this checkout defines | 2026-08-21 | Accepted |
| [0059](0059-transfer-state-is-read-from-quantities-not-pickings.md) | `transfer_state` is read from the quantities, not the pickings | 2026-08-22 | Accepted |
| [0060](0060-invoice-state-reports-progress-not-only-what-is-billable-now.md) | `invoice_state` reports progress, not only what is billable now | 2026-08-22 | Accepted |
| [0061](0061-a-merge-repoints-references-and-absorbing-values-is-a-choice.md) | A merge re-points references always, and absorbs values by choice | 2026-08-23 | Accepted |

## Template

```markdown
# ADR-XXXX: <short title>

- **Status:** Draft | Proposed | Accepted | Superseded by ADR-YYYY | Withdrawn
- **Date:** YYYY-MM-DD
- **Revised:** YYYY-MM-DD   (`Draft` only; omit otherwise)

## Context
What forces are at play — technical, organisational, historical.

## Decision
The change we are making, stated in active voice.

## Alternatives considered
What else was on the table, and why each lost. **Required for every record from
the fourteenth on** (`ALTERNATIVES_REQUIRED_FROM` in
`tooling/architecture/test_adr_coherence.py`) — earlier records predate the rule
and are not back-filled, because inventing a rejected alternative months later
is fiction. This is the section that makes a record worth reading once the
decision is old news: the Decision says what we built, and anyone can read the
tree for that; only this says what we already tried not to build. ADR-0010 is
the worked example.

## Consequences
What becomes easier, what becomes harder, and what we now must maintain.

## Enforcement
How the decision is kept true over time (tests, linters, CI gates). **Required
on every `Accepted` record from the nineteenth on**
(`ENFORCEMENT_ANSWER_REQUIRED_FROM`) — not because every decision must have a
checker, but because every accepted decision must *answer the question*. "No
checker, and here is why, and here is the shape one would take" is a complete
answer and often the right one; silence is not. A boundary added to
`layer_check.py` sets `adr="XXXX"` on its contract, which `test_layer_check.py`
checks resolves to this file and to an `Accepted` record.

## Amendments
Omit until there is one. Append-only, newest last, each dated and headed with
what it corrects. Never edit the sections above except to fix a citation an
amendment announces. **Required on a `Withdrawn` record**, where it carries the
reason.
```

**Do not add an `## Implementation status` section.** Whether the decision has
landed is a present-tense claim about the tree, in the one document that can
never be corrected — so it can only decay, and nothing re-derives it. ADR-0010
is the worked example: its implementation section reported three steps done, and
its own amendment later recorded that two of those were not true when they
shipped. Put the state in `doc/architecture/`, where it is re-derived, or date
the sentence. Gated by
`test_no_record_carries_an_implementation_status_section` from the thirty-sixth
record on (`IMPLEMENTATION_STATUS_FORBIDDEN_FROM`), because correcting ADR-0010
would mean editing an immutable record.

**The order above is the argument, so it is enforced** — what forced this, what
we chose, what we rejected, what it costs, what keeps it true. A record that
answers those out of sequence is harder to read for no gain, and the deviation
is invisible without a check. `test_template_sections_appear_in_template_order`
pins it **from the nineteenth record on** (`SECTION_ORDER_REQUIRED_FROM`):
reordering an existing record would mean editing an immutable one, and the
earlier corpus is allowed its history. Only the template's own sections are
ordered — a record may interleave bespoke sections of its own wherever they read
best, as ADR-0014 and ADR-0015 do.
