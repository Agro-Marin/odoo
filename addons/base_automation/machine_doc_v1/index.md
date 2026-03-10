# base_automation — Machine Documentation v1

## Purpose

`base_automation` is the **workflow engine** for this Odoo fork. It is being
evolved into an n8n-style visual workflow manager: DAG-based, per-execution
isolated, with typed nodes and full execution history.

This is a **strategic core module**. It sits at the intersection of the ORM
trigger system, async infrastructure, and the visual flow editor (`web_flow`
in `addons_custom/`). Upstream Odoo removed their workflow engine in v11;
this module fills that gap with a modern design.

## Files at a Glance

| File | Purpose |
|------|---------|
| `models/base_automation.py` | Rule definition, trigger system, ORM patching, cron |
| `models/ir_actions_server.py` | Node extension: DAG edges, `action_state` (transitional) |
| `models/automation_runtime.py` | Per-execution instance (currently meta-workflow only) |
| `models/automation_runtime_line.py` | Per-step execution state within a runtime instance |
| `models/ir_cron.py` | Thin bridge: cron → `action_open_automation()` |
| `controllers/main.py` | Webhook HTTP endpoint (`/web/hook/<uuid>`) |
| `tests/test_automation.py` | Core trigger tests (`@tagged post_install`) |
| `tests/test_triggers.py` | All trigger types (no `@tagged`, runs at-install) |
| `tests/test_workflow_dag.py` | DAG dependency and orchestration (no `@tagged`) |
| `tests/test_mail_composer.py` | Mail trigger tests |

## Related Modules

| Module | Location | Role |
|--------|----------|------|
| `web_flow` | `addons_custom/web_flow/` | Visual DAG editor (BPMN-js + Mermaid + OWL flow view). Candidate for promotion to `core/`. |

## Read Next

- [`models.md`](models.md) — All models, fields, relationships, known issues
- [`architecture.md`](architecture.md) — Trigger system, hook patching, execution flow
- [`vision.md`](vision.md) — n8n target, phased roadmap, design decisions
- [`conventions.md`](conventions.md) — Naming, patterns, gotchas, what NOT to do
