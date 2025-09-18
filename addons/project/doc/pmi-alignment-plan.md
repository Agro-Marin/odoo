# PMI Terminology Alignment Plan — Project Module

## Executive Summary

The Odoo project module conflates three distinct project management concepts under
inconsistent naming. This plan aligns the module's terminology with PMI/PMBOK
standards through a **full code change** — no aliases, no backward-compatibility
shims, no deprecation timeline.

A `pre_init_hook` performs SQL-level data migration (table renames, column renames,
value updates) **before** the ORM loads, so the new model definitions find their
data already in place.

**Core Problem**: The module uses "stage" to mean three different things:
1. A **workflow step** in a project pipeline (Kanban column)
2. A **task state** (approval/completion/dependency status)
3. A **personal triage bucket** (user's time-horizon categorization)

PMI/PMBOK defines precise, non-overlapping terms for each concept. This plan
adopts those definitions.

**Approach**: This is our fork — we own all dependent modules. No need for
coexistence or gradual deprecation. One clean cut:
1. `pre_init_hook` migrates data at SQL level
2. All Python/XML/JS code uses new names exclusively
3. All dependent modules updated in the same pass

---

## 1. PMI Reference Terminology

| PMI Term | PMBOK Definition | Odoo Current | Odoo Proposed |
|----------|-----------------|--------------|---------------|
| **Phase** | "A collection of logically related project activities that culminates in the completion of one or more deliverables." | `project.project.stage` | `project.phase` |
| **Workflow Step** | The column/position of a work item on a Kanban board. Represents WHERE in the process the item sits. | `project.task.type` (shared rows) | `project.workflow.step` |
| **Status** | The current condition of a project element — a judgment/report ("on track", "at risk"). | `project.update.status` / `last_update_status` | Already correct |
| **State** | The internal condition of a work item (blocked, approved, done). | `project.task.state` | Clean up values (see §4) |
| **Milestone** | "A significant point or event in a project." Zero duration. | `project.milestone` | Already correct |
| **Activity** | "A distinct, scheduled portion of work." The formal PMI term for what Odoo calls "task." | `project.task` | Keep "task" (industry standard) |
| **Logical Relationship** | "A dependency between two activities." Types: FS, FF, SS, SF. | `depend_on_ids` / `dependent_ids` | `predecessor_ids` / `successor_ids` (see §5) |
| **Priority** | Relative importance used to determine sequencing. PMI favors ordinal ranking. | `priority` (0-3 categorical) | Refine labels (see §6) |

---

## 2. Conceptual Model (Target State)

```
project.project
├── phase_id (M2O → project.phase)           # Project lifecycle phase
├── status (Selection: on_track/at_risk/...)  # Project health status
├── milestone_ids (O2M → project.milestone)   # Key deliverable dates
└── workflow_step_ids (M2M → project.workflow.step) # Available workflow steps

project.task
├── step_id (M2O → project.workflow.step)     # Kanban column position
├── state (Selection: in_progress/...)        # Internal condition
├── triage_id (M2O → project.triage)          # Personal time-horizon bucket
├── priority (Selection: 0-3)                 # Urgency ranking
├── milestone_id (M2O → project.milestone)    # Linked milestone
├── predecessor_ids (M2M → project.task)      # "Blocked by" (FS deps)
└── successor_ids (M2M → project.task)        # "Blocks" (FS deps)
```

---

## 3. Workflow Steps (Currently: "Task Stages")

### Problem

`project.task.type` is a **god model** serving two incompatible purposes:
- Shared workflow steps (when `user_id` is null, `project_ids` is set)
- Personal triage buckets (when `user_id` is set, `project_ids` is empty)

The constraint at line 279 is a code smell:
```python
@api.constrains("user_id", "project_ids")
def _check_personal_stage_not_linked_to_projects(self):
    # "A personal stage cannot be linked to a project"
```

Two unrelated concepts forced into one table, then constrained apart.

### Plan: Split `project.task.type` into two models

**Old model `project.task.type` is REMOVED.** The `pre_init_hook` splits
`project_task_type` into two new tables before the ORM loads.

**New model: `project.workflow.step`** (shared workflow steps)
- Stores: `name`, `sequence`, `fold`, `color`, `project_ids`
- Stores: `mail_template_id`, `rating_template_id`, `auto_update_state`
- Stores: `rotting_threshold_days`, `sms_template_id`
- Does NOT have `user_id`
- Table: `project_workflow_step`

**New model: `project.triage`** (personal triage buckets)
- Stores: `name`, `sequence`, `fold`, `user_id`
- Does NOT have `project_ids`, `rating_*`, `mail_template_id`
- Table: `project_triage`
- Default values: Inbox, Today, This Week, This Month, Later, Done, Cancelled

**Junction model: `project.task.triage`** (replaces `project.task.stage.personal`)
- `task_id` → `project.task`
- `user_id` → `res.users`
- `triage_id` → `project.triage`
- Table: `project_task_triage`

**Project phases: `project.phase`** (replaces `project.project.stage`)
- Same fields as `project.project.stage`
- Table: `project_phase`

---

## 4. Task State (Currently: `state` field)

### Problem

The `state` field has:
- Inconsistent value prefixes (`01_`, `02_`, `03_`, `04_` vs `1_`)
- A vestigial suffix (`04_waiting_normal` — `_normal` from old `kanban_state`)
- Approval semantics mixed with dependency-blocking semantics
- `date_last_stage_update` that tracks state changes too

### Plan: Clean up state values

| Current Value | New Value | Rationale |
|---------------|-----------|-----------|
| `01_in_progress` | `in_progress` | Drop numeric prefix |
| `02_changes_requested` | `changes_requested` | Drop numeric prefix |
| `03_approved` | `approved` | Drop numeric prefix |
| `04_waiting_normal` | `blocked` | PMI term. Drop `_normal` vestige. |
| `1_done` | `done` | Drop numeric prefix |
| `1_canceled` | `canceled` | Drop numeric prefix |

**Constants update**:
```python
CLOSED_STATES = {
    "done": "Done",
    "canceled": "Canceled",
}
```

**Timestamp rename**: `date_last_stage_update` → `date_last_status_change`

**Field rename**: `auto_validation_state` → `auto_update_state` on `project.workflow.step`

---

## 5. Dependencies (Currently: `depend_on_ids` / `dependent_ids`)

### Problem

PMI calls these **Logical Relationships** with specific terms:
- **Predecessor**: activity that must finish before this one starts (Finish-to-Start)
- **Successor**: activity that waits on the predecessor

### Plan: Rename to PMI terms

| Current | New | PMI Term |
|---------|-----|----------|
| `depend_on_ids` (string: "Blocked By") | `predecessor_ids` (string: "Predecessors") | Predecessor |
| `dependent_ids` (string: "Blocking") | `successor_ids` (string: "Successors") | Successor |
| `depend_on_count` | `predecessor_count` | — |
| `closed_depend_on_count` | `closed_predecessor_count` | — |
| `dependent_count` | `successor_count` | — |
| `allow_task_dependencies` | `allow_dependencies` | Shorter, same meaning |
| `is_blocked_by_dependences` (method) | `is_blocked_by_predecessors` | Clearer + fixes typo |
| relation table: `task_dependencies_rel` | `project_task_dependency_rel` | Follows Odoo naming convention |

---

## 6. Priority (Currently: 0/1/2/3)

Labels only — no value changes needed. Pure UI improvement.

| Current Value | Current Label | New Label | Rationale |
|---------------|--------------|-----------|-----------|
| `"0"` | "Low priority" | "Normal" | Default should be neutral, not "low" |
| `"1"` | "Medium priority" | "Important" | Clearer than "medium" |
| `"2"` | "High priority" | "High" | Consistent |
| `"3"` | "Urgent" | "Urgent" | Already good |

---

## 7. `pre_init_hook` — Data Migration

The hook runs raw SQL before the ORM loads. It is **idempotent** — safe to run
multiple times (uses `IF EXISTS` / `IF NOT EXISTS` guards).

```python
def _pre_init_hook(env):
    """Migrate project data to PMI-aligned schema.

    Runs BEFORE the ORM loads new model definitions. Renames tables and
    columns so the new models find their data already in place.
    """
    cr = env.cr

    # ── 1. Split project_task_type → project_workflow_step + project_triage ──

    # 1a. Create project_workflow_step from shared rows (user_id IS NULL)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS project_workflow_step AS
        SELECT id, name, sequence, fold, color,
               mail_template_id, rating_template_id,
               auto_validation_state AS auto_update_state,
               rotting_threshold_days, sms_template_id,
               description, legend_blocked, legend_done, legend_normal,
               create_uid, create_date, write_uid, write_date
        FROM project_task_type
        WHERE user_id IS NULL
    """)

    # 1b. Create project_triage from personal rows (user_id IS NOT NULL)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS project_triage AS
        SELECT id, name, sequence, fold, user_id,
               create_uid, create_date, write_uid, write_date
        FROM project_task_type
        WHERE user_id IS NOT NULL
    """)

    # 1c. Migrate M2M: project_task_type ↔ project_project
    #     Old: project_task_type_rel (type_id, project_id)
    #     New: project_workflow_step_project_rel (step_id, project_id)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS project_workflow_step_project_rel AS
        SELECT type_id AS step_id, project_id
        FROM project_task_type_rel
    """)

    # 1d. Set up sequences for new tables
    cr.execute("""
        DO $$
        BEGIN
            -- project_workflow_step
            IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'project_workflow_step_id_seq') THEN
                CREATE SEQUENCE project_workflow_step_id_seq;
                SELECT setval('project_workflow_step_id_seq',
                    COALESCE((SELECT MAX(id) FROM project_workflow_step), 0) + 1);
                ALTER TABLE project_workflow_step
                    ALTER COLUMN id SET DEFAULT nextval('project_workflow_step_id_seq');
            END IF;

            -- project_triage
            IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'project_triage_id_seq') THEN
                CREATE SEQUENCE project_triage_id_seq;
                SELECT setval('project_triage_id_seq',
                    COALESCE((SELECT MAX(id) FROM project_triage), 0) + 1);
                ALTER TABLE project_triage
                    ALTER COLUMN id SET DEFAULT nextval('project_triage_id_seq');
            END IF;
        END $$;
    """)

    # 1e. Add primary keys and indexes
    cr.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'project_workflow_step_pkey'
            ) THEN
                ALTER TABLE project_workflow_step ADD PRIMARY KEY (id);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'project_triage_pkey'
            ) THEN
                ALTER TABLE project_triage ADD PRIMARY KEY (id);
            END IF;
        END $$;
    """)

    # ── 2. Rename project_project_stage → project_phase ──

    cr.execute("""
        ALTER TABLE IF EXISTS project_project_stage
        RENAME TO project_phase
    """)

    # ── 3. Rename columns on project_task ──

    # 3a. stage_id → step_id (now points to project_workflow_step)
    cr.execute("""
        ALTER TABLE project_task
        RENAME COLUMN stage_id TO step_id
    """)

    # 3b. date_last_stage_update → date_last_status_change
    cr.execute("""
        ALTER TABLE project_task
        RENAME COLUMN date_last_stage_update TO date_last_status_change
    """)

    # ── 4. Rename columns on project_project ──

    # 4a. stage_id → phase_id (now points to project_phase)
    cr.execute("""
        ALTER TABLE project_project
        RENAME COLUMN stage_id TO phase_id
    """)

    # ── 5. Rename dependency relation table ──

    cr.execute("""
        ALTER TABLE IF EXISTS task_dependencies_rel
        RENAME TO project_task_dependency_rel
    """)
    cr.execute("""
        ALTER TABLE IF EXISTS project_task_dependency_rel
        RENAME COLUMN task_id TO task_id
    """)  # column names TBD based on current schema
    # depend_on_ids M2M uses (task_id, depends_on_id) — verify actual column names

    # ── 6. Rename personal stage junction ──
    #     project_task_user_rel → project_task_triage
    #     stage_id column → triage_id

    cr.execute("""
        ALTER TABLE IF EXISTS project_task_user_rel
        RENAME TO project_task_triage
    """)
    cr.execute("""
        ALTER TABLE IF EXISTS project_task_triage
        RENAME COLUMN stage_id TO triage_id
    """)

    # ── 7. Migrate state values ──

    cr.execute("""
        UPDATE project_task SET state = CASE state
            WHEN '01_in_progress'       THEN 'in_progress'
            WHEN '02_changes_requested' THEN 'changes_requested'
            WHEN '03_approved'          THEN 'approved'
            WHEN '04_waiting_normal'    THEN 'blocked'
            WHEN '1_done'              THEN 'done'
            WHEN '1_canceled'          THEN 'canceled'
            ELSE state
        END
        WHERE state IN (
            '01_in_progress', '02_changes_requested', '03_approved',
            '04_waiting_normal', '1_done', '1_canceled'
        )
    """)

    # ── 8. Update ir_model_data references ──
    #     XML IDs referencing old model names need updating so the ORM
    #     doesn't try to recreate records that already exist.

    cr.execute("""
        UPDATE ir_model_data SET model = CASE model
            WHEN 'project.task.type'           THEN 'project.workflow.step'
            WHEN 'project.project.stage'       THEN 'project.phase'
            WHEN 'project.task.stage.personal' THEN 'project.task.triage'
            ELSE model
        END
        WHERE model IN (
            'project.task.type',
            'project.project.stage',
            'project.task.stage.personal'
        )
    """)

    # Split ir_model_data for project.task.type:
    # Records with user_id should point to project.triage instead
    cr.execute("""
        UPDATE ir_model_data imd
        SET model = 'project.triage'
        FROM project_triage pt
        WHERE imd.model = 'project.workflow.step'
          AND imd.res_id = pt.id
    """)

    # ── 9. Update ir_model ──

    cr.execute("""
        UPDATE ir_model SET model = CASE model
            WHEN 'project.task.type'           THEN 'project.workflow.step'
            WHEN 'project.project.stage'       THEN 'project.phase'
            WHEN 'project.task.stage.personal' THEN 'project.task.triage'
            ELSE model
        END
        WHERE model IN (
            'project.task.type',
            'project.project.stage',
            'project.task.stage.personal'
        )
    """)

    # ── 10. Update ir_model_fields for renamed columns ──

    cr.execute("""
        UPDATE ir_model_fields
        SET name = 'step_id'
        WHERE model = 'project.task' AND name = 'stage_id'
    """)
    cr.execute("""
        UPDATE ir_model_fields
        SET name = 'date_last_status_change'
        WHERE model = 'project.task' AND name = 'date_last_stage_update'
    """)
    cr.execute("""
        UPDATE ir_model_fields
        SET name = 'phase_id'
        WHERE model = 'project.project' AND name = 'stage_id'
    """)

    # ── 11. Update mail tracking / automation references ──
    # (ir.rule, ir.filters, ir.actions.server, etc. that reference old field names)

    _update_ir_filters(cr)
    _update_ir_rules(cr)
    _update_server_actions(cr)
```

### Hook Design Principles

1. **Idempotent**: Every statement uses `IF EXISTS`/`IF NOT EXISTS` guards.
   Running the hook twice produces the same result.

2. **No ORM**: Pure SQL only. The ORM is not loaded yet.

3. **Preserves IDs**: Table renames and `CREATE TABLE AS SELECT` preserve original
   row IDs. All foreign keys remain valid.

4. **Handles fresh installs**: On a fresh database (no `project_task_type` table),
   the hook does nothing — `IF EXISTS` guards skip everything. The ORM creates
   the new tables from scratch.

5. **Transaction safety**: The hook runs inside the module installation transaction.
   If anything fails, the entire install rolls back.

---

## 8. Documentation Cleanup

### Delete outdated documentation
- **Delete** `core/addons/project/doc/stage_status.rst` — written for Odoo 8.0,
  references removed fields (`kanban_state`), claims `state` was removed (it's back).

### Write new terminology reference

Create `core/addons/project/doc/terminology.rst`:

```rst
Project Module Terminology
==========================

This module follows PMI/PMBOK terminology where applicable.

Workflow Step (``project.workflow.step``)
    A named position in a project's Kanban board. Tasks move through
    workflow steps as work progresses (e.g., "Backlog → Development →
    Review → Done"). Each project defines its own set of steps.

    Displayed as: Kanban columns, statusbar in form view.

Task State (``project.task.state``)
    The internal condition of a task. Fixed set of values:

    - **In Progress** — actively being worked on
    - **Changes Requested** — reviewer requested modifications
    - **Approved** — validated, ready to proceed
    - **Blocked** — cannot proceed due to unfinished predecessors
    - **Done** — completed
    - **Canceled** — abandoned

    State is partially auto-computed: tasks with open predecessors are
    automatically set to "Blocked". Closed states (Done, Canceled) are
    never overridden by computation.

Personal Triage (``project.triage``)
    A user's personal time-horizon categorization for tasks they are
    assigned to. Not visible to other users. Not part of the project
    workflow. Default buckets: Inbox, Today, This Week, This Month,
    Later, Done, Cancelled.

    Displayed as: Kanban columns in "My Tasks" view only.

Project Phase (``project.phase``)
    The lifecycle stage of a project itself (not its tasks). Examples:
    "Planning", "Execution", "Closing". A project has exactly one
    current phase.

Milestone (``project.milestone``)
    A significant point or event in a project with zero duration.
    Milestones have a deadline and a reached/not-reached status.

Predecessor / Successor
    A dependency between two tasks. Task B has Task A as a predecessor
    if B cannot start until A is done (Finish-to-Start relationship).
    Task A is then a successor of nothing — Task B is A's successor.

Project Status (``project.update.status``)
    A health indicator for the project as a whole: On Track, At Risk,
    Off Track, On Hold, Complete. Updated via project updates.

Priority
    Relative urgency of a task: Normal (default), Important, High, Urgent.
```

---

## 9. CSS/JS Cleanup

### Dead CSS selectors
- `project_task_form_view.scss` lines 2, 7 reference `.o_kanban_state` — dead
  selectors from removed `kanban_state` field. **Delete**.

### Widget renames
| Current Widget | New Widget | Location |
|---------------|-----------|----------|
| `project_task_state_selection` | `project_task_state_selection` | Keep (still shows state) |
| `task_stage_with_state_selection` | `task_step_with_state_selection` | Rename to match field |
| `rotting_statusbar_duration` | Keep | Generic enough |
| `badge_rotting` | Keep | Generic enough |

---

## 10. Implementation Phases

### Phase 1: `pre_init_hook` + New Models
**Risk**: MEDIUM — data migration is the riskiest part, but contained in one function
**Scope**: Write the hook, define all new models, remove old models

1. Write `_pre_init_hook()` in `__init__.py` (SQL migration as described in §7)
2. Register hook in `__manifest__.py`: `"pre_init_hook": "_pre_init_hook"`
3. Define `project.workflow.step` model (fields from `project.task.type` minus `user_id`)
4. Define `project.triage` model (personal bucket fields)
5. Define `project.task.triage` junction model
6. Define `project.phase` model
7. **Remove** `project.task.type` model definition
8. **Remove** `project.task.stage.personal` model definition
9. **Remove** `project.project.stage` model definition
10. Add security rules for new models (`ir.model.access.csv`)
11. Remove security rules for old models

### Phase 2: Rename Fields on Existing Models
**Risk**: MEDIUM — all code must use new names consistently

1. Rename `stage_id` → `step_id` on `project.task` (points to `project.workflow.step`)
2. Rename `personal_stage_type_id` → `triage_id` on `project.task`
3. Rename `personal_stage_id` → `personal_triage_id` on `project.task`
4. Rename `personal_stage_type_ids` → `triage_ids` on `project.task`
5. Rename `date_last_stage_update` → `date_last_status_change` on `project.task`
6. Rename `depend_on_ids` → `predecessor_ids` on `project.task`
7. Rename `dependent_ids` → `successor_ids` on `project.task`
8. Rename count fields: `depend_on_count` → `predecessor_count`, etc.
9. Rename `allow_task_dependencies` → `allow_dependencies`
10. Rename `stage_id` → `phase_id` on `project.project`
11. Rename `type_ids` → `workflow_step_ids` on `project.project`
12. Clean up state values (drop prefixes, `waiting_normal` → `blocked`)
13. Update `CLOSED_STATES` constant and all references
14. Update priority labels

### Phase 3: Migrate Logic
**Risk**: MEDIUM — compute methods, constraints, business logic

1. Rename `_compute_stage_id` → `_compute_step_id`
2. Rename `_read_group_stage_ids` → `_read_group_step_ids`
3. Rename `_compute_personal_stage_id` → `_compute_personal_triage_id`
4. Rename `_search_personal_stage_id` → `_search_personal_triage_id`
5. Rename `_get_default_personal_stage_create_vals` → `_get_default_triage_vals`
6. Rename `_populate_missing_personal_stages` → `_populate_missing_triages`
7. Rename `_read_group_personal_stage_type_ids` → `_read_group_triage_ids`
8. Rename `is_blocked_by_dependences` → `is_blocked_by_predecessors`
9. Update `_compute_state` to depend on `step_id` + `predecessor_ids.state`
10. Update `write()` to use new field names
11. Rename `auto_validation_state` → `auto_update_state`

### Phase 4: Views & UI
**Risk**: MEDIUM — XML changes, widget updates

1. Update all form/kanban/list/calendar views to use new field names
2. Update search filters and group-by options
3. Rename JS widget `task_stage_with_state_selection` → `task_step_with_state_selection`
4. Remove dead CSS selectors (`.o_kanban_state` references)
5. Update `project_todo` views (switch to `triage_id`)
6. Update priority labels in selection definitions
7. Update demo data and sample data XML

### Phase 5: Dependent Modules (All at Once)
**Risk**: HIGH — blast radius across 23+ modules, but no aliases means clean code
**Approach**: grep-based audit, fix every reference in one pass

1. Update `project_sms` (switch to `step_id`, `project.workflow.step`)
2. Update `sale_project` (inherit `project.workflow.step`)
3. Update `project_enterprise` (switch state value references)
4. Update `industry_fsm` (switch to `step_id`, fold logic)
5. Update `hr_timesheet`, `sale_timesheet`, `timesheet_grid`
6. Update all other inheriting modules (s/stage_id/step_id/ everywhere)
7. Update reports (`project_report.py`) to reference new fields
8. Update security rules for modules extending project
9. Update state value references (`01_in_progress` → `in_progress`, etc.)
10. Each dependent module gets its own `pre_init_hook` if it has stored
    references to old field names or state values

### Phase 6: Documentation & Tests
1. Delete `stage_status.rst`, write `terminology.rst`
2. Update all test files to use new field names and state values
3. Update test data (demo data, sample data XML)
4. Run full test suite for project + all dependent modules

---

## 11. Naming Convention Summary

### Models

| Old Model (REMOVED) | New Model | New Table |
|---------------------|-----------|-----------|
| `project.task.type` (shared rows) | `project.workflow.step` | `project_workflow_step` |
| `project.task.type` (personal rows) | `project.triage` | `project_triage` |
| `project.task.stage.personal` | `project.task.triage` | `project_task_triage` |
| `project.project.stage` | `project.phase` | `project_phase` |
| `project.task` (no change) | `project.task` | — |
| `project.milestone` (no change) | `project.milestone` | — |
| `project.update` (no change) | `project.update` | — |

### Fields on `project.task`

| Old Field (REMOVED) | New Field | Type | Notes |
|---------------------|-----------|------|-------|
| `stage_id` | `step_id` | Many2one → `project.workflow.step` | Column renamed in DB |
| `stage_id_color` | `step_color` | Integer (related) | — |
| `state` | `state` (same) | Selection | Values cleaned (drop prefixes) |
| `personal_stage_type_ids` | `triage_ids` | Many2many → `project.triage` | — |
| `personal_stage_id` | `personal_triage_id` | Many2one → `project.task.triage` | — |
| `personal_stage_type_id` | `triage_id` | Many2one (related) | — |
| `date_last_stage_update` | `date_last_status_change` | Datetime | Column renamed in DB |
| `depend_on_ids` | `predecessor_ids` | Many2many → `project.task` | Relation table renamed |
| `dependent_ids` | `successor_ids` | Many2many → `project.task` | Inverse of predecessor_ids |
| `depend_on_count` | `predecessor_count` | Integer | — |
| `closed_depend_on_count` | `closed_predecessor_count` | Integer | — |
| `dependent_count` | `successor_count` | Integer | — |
| `allow_task_dependencies` | `allow_dependencies` | Boolean (related) | — |
| — | `milestone_id` (no change) | Many2one | Already correct |
| — | `priority` (no change) | Selection | Labels updated only |

### Fields on `project.workflow.step` (ex `project.task.type`)

| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `name` | `name` | No change |
| `sequence` | `sequence` | No change |
| `fold` | `fold` | No change |
| `color` | `color` | No change |
| `project_ids` | `project_ids` | No change |
| `auto_validation_state` | `auto_update_state` | Rename + new string |
| `mail_template_id` | `mail_template_id` | No change |
| `rating_template_id` | `rating_template_id` | No change |
| `rotting_threshold_days` | `rotting_threshold_days` | No change |
| `user_id` | REMOVED | Moved to `project.triage` |

### Fields on `project.project`

| Old Field (REMOVED) | New Field | Type |
|---------------------|-----------|------|
| `stage_id` | `phase_id` | Many2one → `project.phase` |
| `stage_id_color` | `phase_color` | Integer (related) |
| `type_ids` | `workflow_step_ids` | Many2many → `project.workflow.step` |

### State Values on `project.task`

| Current | New | String |
|---------|-----|--------|
| `01_in_progress` | `in_progress` | "In Progress" |
| `02_changes_requested` | `changes_requested` | "Changes Requested" |
| `03_approved` | `approved` | "Approved" |
| `04_waiting_normal` | `blocked` | "Blocked" |
| `1_done` | `done` | "Done" |
| `1_canceled` | `canceled` | "Canceled" |

### Methods

| Old Method (REMOVED) | New Method | Notes |
|---------------------|------------|-------|
| `_compute_stage_id` | `_compute_step_id` | |
| `_read_group_stage_ids` | `_read_group_step_ids` | |
| `_compute_personal_stage_id` | `_compute_personal_triage_id` | |
| `_search_personal_stage_id` | `_search_personal_triage_id` | |
| `_get_default_personal_stage_create_vals` | `_get_default_triage_vals` | Shorter |
| `_populate_missing_personal_stages` | `_populate_missing_triages` | |
| `_read_group_personal_stage_type_ids` | `_read_group_triage_ids` | |
| `is_blocked_by_dependences` | `is_blocked_by_predecessors` | Fix typo + PMI term |

---

## 12. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `pre_init_hook` SQL error | MEDIUM | HIGH | Test on DB copy first. Transaction rolls back on failure. |
| Missing rename in dependent module | MEDIUM | HIGH | grep-based audit of entire codebase. No aliases = immediate error = fast detection. |
| State value migration misses rows | LOW | HIGH | `CASE ... ELSE state END` preserves unknown values. Verify with `SELECT DISTINCT state`. |
| JS widget breakage | MEDIUM | MEDIUM | Comprehensive widget testing. |
| Fresh install (no old tables) | LOW | LOW | Hook guards with `IF EXISTS`. ORM creates new tables from scratch. |
| ir_model_data mismatch | MEDIUM | HIGH | Hook updates `ir_model_data`, `ir_model`, `ir_model_fields` before ORM loads. |
| Third-party modules | N/A | N/A | Not applicable — this is our fork, no third-party modules. |

---

## 13. Success Criteria

- [ ] `pre_init_hook` migrates existing database cleanly (test on production DB copy)
- [ ] Fresh install works (no old tables → ORM creates everything from scratch)
- [ ] New models exist: `project.workflow.step`, `project.triage`, `project.task.triage`, `project.phase`
- [ ] Old models fully removed: `project.task.type`, `project.task.stage.personal`, `project.project.stage`
- [ ] No code anywhere references old model/field names (grep verification)
- [ ] State values cleaned (no numeric prefixes, no `_normal` suffix)
- [ ] Dependency fields use PMI "predecessor/successor" terminology
- [ ] `stage_status.rst` replaced with `terminology.rst`
- [ ] All 23+ dependent modules updated and passing tests
- [ ] Dead CSS selectors removed
- [ ] Priority labels updated (Low → Normal, Medium → Important)
- [ ] Full test suite passes for `project` and all dependent modules
