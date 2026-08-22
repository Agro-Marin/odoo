# ADR-0046: A presentational component takes its data as props

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

`js_layer_check`'s `components-below-entity` contract forbids `components/` from
importing `@web/model`, and states why:

> Presentational components take their data as props. Reaching into `model/`
> would let a component bind itself to the relational datapoint rather than to
> the values it renders.

The sentence is the argument. The contract enforces one sixth of it.

`@web/model` is not the only way a component reaches the server, and it is not
the way any component in this tree actually does. Eleven modules under
`addons/web/static/src/components/` acquire data at runtime instead — through
`useService("orm")`, `useService("field")`, `useService("name")`, or by calling
`rpc` directly. Every one passes `components-below-entity`, because those
services live in `core/` and the contract names one forbidden import prefix.

So the rule reads as a principle and behaves as a spelling restriction — the
worst of both. A reader takes the rationale at face value, writes a component
that fetches, and nothing objects; a reader who checks discovers the sentence
describes a tree that does not exist and stops trusting the rationale, which also
carries the layering rules that *are* enforced.

Two ways out: narrow the sentence to what the gate checks, or gate what the
sentence says. Narrowing is cheaper and is the wrong trade — divergence from
upstream is bought with architecture, and a component that fetches its own data
cannot be rendered anywhere its service is not started, a constraint a dialog, a
POS screen and a public page each run into separately.

## Decision

**A module under `components/` does not acquire data at runtime.** Data arrives
as props, or through a hook the consumer supplies.

Enforced by `tooling/architecture/js_component_data_access.py`, which counts
`useService("orm" | "field" | "name")` and direct `rpc` calls under
`addons/web/static/src/components/` and compares the set against a pinned list —
**shrink-only**. An acquisition site not on the list fails the build; a site on
the list that goes away must leave it in the same commit, so the debt cannot be
paid once and re-spent.

The pin is a list of *sites*, not a count, for the reason `js_extension_surface`
pins points rather than a total: a number says eleven exist, a list says which,
so removing one is a task rather than an investigation.

## Alternatives considered

**Narrow the rationale to what the gate checks** — "must not import
`@web/model`". Cheapest, and the first draft. Rejected because the smaller
boundary is not the one anyone wants: a component that fetches through a service
has the same problem as one that imports the datapoint, and the sentence would
document the accident rather than the intent.

**Forbid the services outright, with no pin.** Drift-zero, no debt, and not
landable: eleven sites exist and each is a separate migration with a separate
design question (`AutoComplete`'s `props.sources` is the shape most want, but
`error_handlers` polling for a restored connection is not a picker). A gate
nobody can turn on is worth less than one that stops the count growing today.

**Count the sites instead of listing them.** Rejected for the reason above: only
the list turns "reduce this" from an investigation into a task.

**Widen it to every service.** `dialog`, `notification`, `ui` and `overlay` would
join. They are not the failure: a component that opens a dialog still renders
wherever the overlay container is mounted, and the rationale is about components
that cannot render at all where their data source is absent.

## Consequences

The eleven sites are debt, recorded as such, each with a different distance to
travel:

- `record_selectors`, `model_selector`, `model_field_selector`,
  `domain_selector` and `tree_editor` fetch to populate a picker. The data is the
  component's subject, and moving the fetch out means the consumer supplies a
  source function — which `AutoComplete` already models with `props.sources`.
- `name_and_signature` fetches fonts, and `error_handlers` polls
  `/web/webclient/version_info` to detect a restored connection. Neither is view
  data; both are closer to a service that happens to live here.

Nothing is migrated by this record. The list exists so the count cannot grow
quietly, and so the rationale in `js_layer_check` describes a boundary something
checks.

`components-below-entity` is unchanged. It still forbids `@web/model` for its own
reason: an import binds a component to the datapoint's shape at build time, a
service call binds it to the data at runtime. Different failures, both worth
refusing.

## Enforcement

`tooling/architecture/js_component_data_access.py`, run with `--check` in
`architecture.yml`. It fails on a site not in `PINNED` and on a pinned site that
has stopped acquiring, so the list can only shrink and a migration cannot be
banked twice.

`tooling/architecture/test_js_component_data_access.py` pins the detector: that
each data service in one file is its own site, that a client-side service is not
one, and that `this.orm.rpc(...)` and `silentRpc(...)` are not counted as direct
`rpc` calls. `test_every_gate_refuses_an_empty_tree` covers the empty scan.
