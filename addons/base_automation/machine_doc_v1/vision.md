# base_automation — Vision & Roadmap

## The Goal: n8n Inside Odoo

Transform `base_automation` into a best-in-class workflow engine with:

- **Visual DAG editor** (library undecided — see Decision 1)
- **Per-execution isolation** (every trigger creates an `automation.runtime`)
- **Typed nodes** (code, write, email, http, wait, branch, parallel, join,
  approval, subflow)
- **Conditional edges** (always / on_success / on_error / expression)
- **Full execution history** (what ran, when, on which record, what output)

The unique advantage over external workflow tools (n8n, Zapier, Temporal): nodes
operate directly on live Odoo business models with full ORM access, multi-company
context, and access control. An `approval` node that reads `partner_id.country_id`
fiscal rules and posts a `mail.activity` is trivial here.

---

## Design Decisions

Decisions 2–4 are locked. **Decision 1 was reopened on 2026-08-26** because the
module it rested on was deleted as unused on 2026-04-21, four months before this
document noticed.

### Decision 1: Visual Layer — OPEN

This decision previously read that `web_flow` (agromarin/web_flow/) provided a
BPMN-js modeler, a Mermaid widget and an OWL `flow` view type, and that
`flow.diagram` would become the layout layer. That was **true when written on
2026-03-10 and false six weeks later**: `agromarin` `60b5a7eef` (2026-04-21,
task 21062) deleted the module as unused, and nothing connected the deletion to
this document. Re-derive before believing either version:

```bash
find odoo enterprise agromarin design-themes -maxdepth 3 -type d -name web_flow
grep -rl -E 'web_flow|flow\.diagram|bpmn' --include='*.py' --include='*.xml' \
    --include='*.js' agromarin odoo/addons enterprise
```

The first returns nothing; the second returns only this directory and an unrelated
mention in agromarin/web_network/README.md. This module carries no factcheck
harness, which is how a locked decision outlived its own subject by four months.

**Read the removal before proposing BPMN again.** `60b5a7eef` did not delete
`web_flow` to make room for something better — it deleted it as dead weight:

>     flow_diagram table has 0 records in marin190
>     No module declares web_flow as a dependency (web_flow_demo,
>     its only consumer, was removed in T-21048)
>     Bundled 2.9MB of dead JS assets (bpmn-js + mermaid) served
>     on every session
>     The `flow` view type has no active consumers

That is this fork's own measured verdict on a BPMN canvas: nobody drew a diagram
with it, and it cost every session 2.9 MB to offer. Both facts constrain the
replacement — see the notation and lazy-loading points below.

So the visual layer is **undecided**. What the reopening settled, and what a
replacement decision must respect:

* **BPMN is the wrong notation, and was already tried.** It models business
  processes with pools, lanes and gateways; this engine is a plain DAG of server
  actions. A BPMN editor means adopting a notation whose semantics the engine does
  not implement — and `web_flow` shipped exactly that, to zero diagrams.
* **No React.** The fork is OWL and vendors no React, so a React SDK — including
  `synergycodes/workflowbuilder`, the proposal that prompted this review — is
  rejected on runtime grounds: two component systems, two state systems and two
  theming systems on one page. The objection is *not* the build step; the fork
  bundles with esbuild 0.25 and would compile it fine.
* **The integration constraint is one file.** A library must be reducible to a
  single browser-ready ESM file vendored into `<addon>/static/lib/` and declared
  under the module manifest's `esm.external_libs` key. That is weaker than it
  sounds: agromarin/geoengine/static/lib/ol/ builds exactly such a file from a
  curated entry.js with a pinned esbuild, and that recipe is the one to copy.
* **Load it lazily.** A top-level import in `web.assets_backend` resolves on every
  backend page — the 2.9 MB `web_flow` charged every session is the cautionary
  measurement, and agromarin/geoengine hit the same wall at ~770 KB and moved to
  a single dynamic `import()`. Only `base.automation` form views need a canvas, so
  it belongs in a lazy bundle (`web.ace_lib` is the pattern).

Recommendation pending sign-off: **JointJS core** (MPL-2.0, zero runtime
dependencies, ships `joint.mjs`, SVG-in-DOM so nodes theme from Odoo's own SCSS),
with **diagram-js** (MIT, notation-agnostic) as the fallback. Rete.js is rejected —
its core is framework-agnostic but no vanilla renderer exists. Full comparison,
including the licence trap in elkjs (EPL-2.0 against LGPL-3 addons):
agromarin-knowledge/research/2026-08-26-workflow-visual-layer-options.md.

**This decision is not blocking.** Phase 2 (`workflow.edge`) and node coordinate
storage gate the canvas, and no library supplies either — see Phase 4.

### Decision 2: Async / Wait Nodes

The `wait` node type (pause execution, resume after delay) will be implemented
as a **temporal/polling system**: a separate cron job checks for paused
executions whose resume time has passed and re-enters the DAG.

**This temporal system is explicitly provisional.** It will be deprecated and
replaced when real async infrastructure ships at the framework level (see the
ongoing async work in other fork layers). Design the temporal system for easy
removal: isolate it in a single method `_resume_waiting_executions()` and a
dedicated cron job. No other code should depend on the polling behavior.

### Decision 3: Node Model

`ir.actions.server` is kept as the node model for now. This preserves
compatibility with Odoo's existing action system (buttons, server actions in
menus, etc.) and allows the DAG concept to be proven without a full model
extraction. The extension is in `models/ir_actions_server.py`.

When the engine matures, evaluate whether to extract to a dedicated
`workflow.node` model. Criteria: does the current coupling to `ir.actions.server`
cause real problems (naming confusion, unwanted field pollution, permission
model mismatch)?

### Decision 4: Document Before Code

Architectural changes to this module require updating this `machine_doc_v1/`
first. The doc is the design contract; the code implements it.

---

## Current State vs Target

| Concern | Current State | Target |
|---------|--------------|--------|
| Execution isolation | **done** — all state on `automation.runtime.line` | — |
| `automation.runtime` scope | **done** — `automation_id` carries no domain | — |
| `use_workflow_dag` flag | **done** — removed, every automation is DAG-capable | — |
| Trigger coverage | partial — `_process` creates a runtime for any automation whose actions have predecessors, not only `on_hand` | All triggers create instances |
| Edge model | Many2many (`predecessor_ids`) — untyped | `workflow.edge` with `condition` field |
| Node types | Only `ir.actions.server` existing states | + wait, branch, parallel, join, approval, subflow |
| Node coordinates | **none** — nothing persists a node position | stored, so a canvas can round-trip a layout |
| Visual layer | **none — `web_flow` was deleted as unused, 2026-04-21** | Integrated with `base.automation` form |
| Execution history | `automation.runtime` per DAG run; `last_run` only for the rest | Full history per trigger |

---

## Phased Roadmap

### Phase 1 — Execution Model Foundation — MOSTLY DONE

Goal: make `automation.runtime` the canonical execution record for all triggers.

1. ~~Remove `use_workflow_dag` and `auto_execute_workflow` from `base.automation`.~~
   **Done** — neither field exists; every automation is DAG-capable.
2. ~~Remove `action_state`, `is_ready`, `error_message` from `ir.actions.server`.~~
   **Done** — none is declared there, and `error_message` now lives on
   `automation.runtime.line` where it belongs. `factcheck.sh` asserts all three
   stay gone, so a reintroduction fails the gate rather than silently
   resurrecting the corruption this phase removed.
3. ~~Remove domain restriction on `automation.runtime.automation_id`.~~
   **Done** — the field declares no domain.
4. **Open.** `_process` creates a runtime and lines for any automation whose
   actions carry predecessors, which is broader than the original `on_hand`-only
   behaviour but still not every trigger path. A single-action automation on a
   plain `on_create` still executes without a runtime record.
5. Preserve backward-compat: simple automations with one action still work;
   the runtime record is created transparently.

Outcome, once 4 lands: every automation execution is traceable. The
`action_state` corruption on concurrent runs is already eliminated by 1–3.

### Phase 2 — Edge Model

Goal: conditional routing between nodes.

1. Add `workflow.edge` model: `source_node_id`, `target_node_id`,
   `condition` (Selection: always/on_success/on_error/expression),
   `condition_expr` (Char, Python expression), `label` (Char).
2. Migrate `predecessor_ids` data to `workflow.edge` records.
3. Update DAG resolution in `automation.runtime.line` to use edge conditions
   when activating successors after a step completes.
4. Remove `predecessor_ids` / `successor_ids` from `ir.actions.server`.

Outcome: IF-node behavior (branch on success/error/expression).

### Phase 3 — Node Type System

Goal: typed nodes beyond `ir.actions.server` existing states.

New `node_type` on `ir.actions.server` (or wrapper model):

| Type | Behavior |
|------|---------|
| `wait` | Pause execution until datetime. Resume via provisional cron (see Decision 2). |
| `branch` | Evaluate expression, activate only the matching outgoing edge. |
| `parallel` | Activate all outgoing edges simultaneously (fan-out). |
| `join` | Wait until ALL incoming edges complete (fan-in AND gate). |
| `approval` | Create `mail.activity`, pause until user marks done (human-in-the-loop). |
| `subflow` | Invoke another `base.automation` rule, wait for its runtime to complete. |
| `http_request` | Call external HTTP endpoint (inbound webhook equivalent for outbound). |

The `wait` and `approval` nodes introduce cross-transaction execution — an
`automation.runtime` instance spans multiple cron/user interactions. This
requires `automation.runtime.state` to have `waiting_resume` as a new value.

### Phase 4 — Visual Integration

Goal: `base.automation` form view shows the workflow as an interactive DAG.

0. **Add node coordinate storage.** Nothing in the module persists a node
   position today — no `pos_x`/`pos_y`, no diagram blob. A canvas cannot round-trip
   a layout without it, and this step was missing from the roadmap entirely.
1. Settle Decision 1, then vendor the chosen library per that decision's
   constraints: one ESM file under `static/lib/`, declared in `esm.external_libs`,
   built by a build.sh with a pinned esbuild, reached through a lazy bundle.
2. Replace the `action_server_ids` kanban in the automation form with an OWL
   component wrapping that library.
3. Saving a diagram auto-creates/updates `ir.actions.server` nodes and
   `workflow.edge` records via RPC, with `_check_no_dag_cycle` and
   `_check_predecessors_scope` still enforcing on the server side.
4. Execution monitoring: overlay live `automation.runtime` state onto the diagram
   (highlight running/done/error nodes in real time via polling or websocket).
   `automation.runtime.line.state` and `automation.runtime.progress` already model
   everything this needs.

---

## What NOT to Build Here

- **Per-record state machines**: Odoo's native computed fields + `state` Selection
  field pattern handles this better (sale.order, account.move, etc.). The workflow
  engine handles *cross-model, multi-step, human-in-the-loop* orchestration that
  no single model owns.

- **Replacing `ir.cron`**: cron stays for scheduled jobs. The workflow engine
  uses cron as a trigger and as the resume mechanism for `wait` nodes, but does
  not replace it.

- **High-frequency event streaming**: automations on high-volume write triggers
  (e.g., stock.move) that create a runtime record per event will generate huge
  history tables. Provide a `create_runtime_instance` boolean on `base.automation`
  to let lightweight automations opt out of history tracking.
