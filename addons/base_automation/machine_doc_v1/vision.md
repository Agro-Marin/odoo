# base_automation — Vision & Roadmap

## The Goal: n8n Inside Odoo

Transform `base_automation` into a best-in-class workflow engine with:

- **Visual DAG editor** (via `web_flow` with BPMN-js)
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

## Design Decisions (Locked)

### Decision 1: Visual Layer

`web_flow` (`addons_custom/web_flow/`) provides the visual editor today:
- BPMN-js modeler (536KB, interactive) + viewer (180KB, read-only)
- Mermaid widget (alternative for simpler diagrams)
- OWL `flow` view type registerable in XML

Both visual systems coexist. `web_flow` is a candidate for promotion to
`core/addons/` when the workflow engine stabilizes. Business case determines
timing — do not force the move prematurely.

The `flow.diagram` model (BPMN XML + element_mappings JSON) becomes the visual
layout layer for `base.automation` workflows: one diagram per automation rule,
with element IDs mapped to `ir.actions.server` IDs and edge IDs.

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
| Execution isolation | `action_state` on definition (broken) | All state on `automation.runtime.line` |
| Trigger coverage | Only `on_hand` creates `automation.runtime` | All triggers create instances |
| Edge model | Many2many (`predecessor_ids`) — untyped | `workflow.edge` with `condition` field |
| Node types | Only `ir.actions.server` existing states | + wait, branch, parallel, join, approval, subflow |
| `automation.runtime` scope | Meta-workflows only (domain restriction) | All workflows |
| Visual layer | `web_flow` in `addons_custom/` (standalone) | Integrated with `base.automation` form |
| `use_workflow_dag` flag | Required to enable DAG | Removed — all automations are DAG-capable |
| Execution history | Only `last_run` timestamp | Full `automation.runtime` history per trigger |

---

## Phased Roadmap

### Phase 1 — Execution Model Foundation

Goal: make `automation.runtime` the canonical execution record for all triggers.

1. Remove `use_workflow_dag` and `auto_execute_workflow` from `base.automation`.
   All automations become DAG-capable.
2. Remove `action_state`, `is_ready`, `error_message` from `ir.actions.server`
   (they belong on `automation.runtime.line`).
3. Remove domain restriction on `automation.runtime.automation_id` — any
   automation can have runtime instances, not just meta-workflows.
4. Wire all trigger paths to create an `automation.runtime` + lines before
   executing `ir.actions.server` actions.
5. Preserve backward-compat: simple automations with one action still work;
   the runtime record is created transparently.

Outcome: every automation execution is traceable. `action_state` corruption
on concurrent runs is eliminated.

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

1. Promote `web_flow` to `core/addons/web_flow/` (or integrate directly into
   `base_automation`'s static assets).
2. Replace the `action_server_ids` list view in the automation form with the
   BPMN-js modeler embedded in an OWL component.
3. Saving a diagram auto-creates/updates `ir.actions.server` nodes and
   `workflow.edge` records via RPC.
4. Execution monitoring: overlay live `automation.runtime` state onto the diagram
   (highlight running/done/error nodes in real time via polling or websocket).

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
