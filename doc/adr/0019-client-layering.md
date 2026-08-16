# ADR-0019: Client layering — a rank in `web`, a bundle subset in `mail`, on both graphs

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

The Python core's import direction is a drift-zero gate with a decision record
behind every contract (ADR-0001, ADR-0005). The client had the gates and none of
the records: measured 2026-08-14, twenty checkers in `tooling/architecture/`
enforced the JavaScript architecture and no ADR argued for any of them. A reader
could learn from `tooling/architecture/js_layer_check.py` *what* is forbidden and
had nowhere to learn why.

Three forces shaped what those gates became, and none of them is obvious from the
outside.

**ESLint could not hold the rule.** The layering existed as
`no-restricted-imports` blocks in `eslint.config.mjs`, whose findings fold into
one aggregate lint count. A new layering breach is +1 in a six-figure floor —
signal inside noise — and the ratchet's exact mode lets unrelated lint churn mask
it. The blocks were also copy-pasted per layer, so they drifted: the `model/`
rule forbade the widget and page layers but not `@web/fields`, an
entity-reaches-feature breach that passed lint for as long as it existed.

**The two big client trees are organised on different axes.** `web` files are
filed by *what the code does*; `mail` files are filed by *where the code runs* —
`core/common/`, `chatter/web_portal/`, `discuss/core/public/` — and that path
segment decides which asset bundles the file lands in. `mail`'s own
`addons/mail/machine_doc_v1/ARCHITECTURE.md` calls this the module's most
distinctive architectural trait. Every addon-scoped gate in this directory
resolved `web`'s source root, so the rule in the repo's second-largest client
tree lived in prose only.

**Reading imports sees half the graph.** A dependency taken through the registry
binds at runtime and is invisible to every import-reading checker.
`addons/web/static/src/core/utils/hooks.js` imports nothing from the UI layer, so
the `core-below-ui-components` contract reported clean, while `useOwnedDialogs`
in that same file reached `addons/web/static/src/ui/dialog/dialog_service.js`
through a service lookup. Written as an import it is a `core -> ui` edge the gate
rejects on sight; routed through the registry it passed. The contract was
satisfied in letter and broken in fact.

## Decision

**Client layering is a drift-zero gate, on both dependency graphs, in the shape
each tree's axis actually has.**

### 1. In `web`, the layers are a rank

A total order, low to high, in which a file may import its own layer or lower:

    core/ < ui/ < components/ < model/ < fields/ < search/ < views/ < webclient/

`addons/web/static/src/core/domain.js` is pinned to the entity layer beside
`model/`; `boot/`, `public/` and `libs/` sit outside the stack and are ungoverned.

**The order is deliberately stricter than the import graph requires.** Seven of
the eight-factorial orderings score zero against the real edges, differing in
where `model/` and `search/` sit; the extra constraints are chosen, not measured
— the data layer is held below the UI layers so it reaches them only through the
declared hook seam. Each such constraint argues for itself where it is defined,
and the per-contract rationales, not this summary, are the authority.

### 2. In `mail`, the layers are a bundle subset, and a rank would be wrong

The obvious model is a linear ordering and it does not exist here. Deployment
contexts are not ranked: `web` and `public` are mutually exclusive targets, and
`public_web` and `web_portal` overlap only in the backend, so neither pair can be
ordered against the other. The true rule falls out of asset membership:

| layer | ships in |
|---|---|
| `common` | backend, public, portal |
| `public_web` | backend, public |
| `web_portal` | backend, portal |
| `web` | backend |
| `public` | public |

    A may import B  <=>  bundles(A) is a subset of bundles(B)

"B must ship everywhere A ships." An import is a promise that the target is
present, so the target must exist in every context the importer reaches.

**The failure this prevents is not stylistic.** `common` ships in the standalone
bundle for the anonymous discuss page, which contains no `web` layer at all. A
`common` file importing a `web` module resolves to undefined at runtime on that
page and only on that page — which no unit suite loads.

### 3. The registry is the second graph, and it is checked

Registry-mediated dependencies are ranked against the same layer order as
imports. A gate that reads only `import` statements certifies a property the
runtime does not have, and this fork does not ship gates that are true in letter.

### 4. A layer must be a module, not a namespace

A top-level directory earns layer status by cohesion: its files depend on one
another. Where they merely share a *mechanism* — everything that registers
something, everything called a helper — the directory is a namespace, could be
dissolved without any import changing but its own path, and ordering it against
the others asserts nothing. This is not hypothetical; the directory that failed
it has since been dissolved.

### 5. Layers are acyclic

Direction is not enough: every edge of a cycle can sit inside one layer and break
no contract, and nothing else in the toolchain looks — ESLint has no cycle rule
enabled, and a cycle is invisible to the typechecker and to the suite, because
whether it hurts depends on which module the bundle evaluates first. The
`addons/web/static/src/core/py_js` cycle was correct or broken purely as a
function of entry point.

## Alternatives considered

**Leave it to ESLint.** Rejected on the evidence above: the aggregate count
cannot express drift-zero, the per-layer blocks drifted from each other, and the
one breach anybody checked had been passing lint. This is the same argument
ADR-0006 makes for countable gates generally — a floor that mixes concerns hides
the one that matters.

**One layering model for both trees.** Rejected because it is false. Forcing
`mail`'s deployment contexts into a rank would either forbid edges the tree
legitimately has or permit the `common -> web` edge that breaks the public page,
depending on where the incomparable pairs were put. Two axes with two shapes is
more machinery than one, and it is what is true.

**Rank the deployment layers by "how public" they are.** The intuitive
ordering, and the one that fails: it makes `public` and `web` comparable when
they are mutually exclusive targets. The subset rule was not invented for this
gate — it is read off the asset table the addon already maintained.

**Check imports only, and treat registry edges as out of scope.** Rejected: it
was the status quo, and it certified `core-below-ui-components` as clean while a
`core` file reached a UI service. A gate whose green is not evidence is worse
than no gate, because it stops anyone looking.

**Write one record for the whole client architecture.** Rejected while writing
this one. The twenty JS gates are not one decision: layering, public surface,
extension and patch discipline, and render behaviour are separate arguments with
separate consequences, and a record covering all of them would cite gates it does
not argue for — the failure mode ADR-0014's mention of a checker it never argued
for already illustrates. This record takes the five layering gates; the surface
and extension gates are a separate record, not yet written.

## Consequences

- The client's layering is enforced at the same standard as the core's, and a
  breach fails immediately rather than becoming +1 in a lint floor.
- **Two models must be maintained, and told apart.** The cost is real: a
  contributor to `mail` who reasons by rank will be wrong, and a contributor to
  `web` who reasons by bundle membership will be wrong. Each gate names its own
  tree and its own shape for that reason.
- The `web` order is stricter than measured need, so a future import that the
  graph would tolerate can still fail. That is intended, and the per-contract
  rationale is where the argument for each such constraint lives.
- Registry coverage means a layering fix can no longer be a service lookup. The
  seam has to be declared instead, which is more work and is the point.
- The deployment-layer rule was pinned while the tree already satisfied it in
  full, which is the cheapest moment to pin anything and the reason it could be
  drift-zero from the first commit rather than starting from a floor.
- Four ungoverned directories remain outside the `web` stack. They are named
  above rather than quietly excluded, so their status is a decision a reader can
  challenge.

## Enforcement

Five gates in `tooling/architecture/`, each declaring `ADR = "0019"`, all run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_layer_check.py` | the `web` rank, as a contract table |
| `tooling/architecture/js_deployment_layers.py` | the bundle-subset rule across the addon trees |
| `tooling/architecture/js_registry_layering.py` | the same order over registry-mediated edges |
| `tooling/architecture/js_layer_cohesion.py` | that a layer is a module, not a namespace |
| `tooling/architecture/js_cycle_check.py` | acyclicity within and across layers |

`tooling/architecture/test_gate_adr_coverage.py` checks that citation resolves to
this record and that this record is `Accepted`. For each gate's live status, run
it — this record does not restate one.
