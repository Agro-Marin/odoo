# Scenario view — end-to-end threads through the other views

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> Each other view is a projection: modules, runtime, data, deployment. A
> scenario is a **thread that crosses all of them**, which is the only way to
> see an interaction that no single view contains.

`runtime.md` already threads two: [process
boot](runtime.md#process-boot) and the [request
lifecycle](runtime.md#request-lifecycle-http). This page carries the two that
cross the most views and are least visible from any one of them — installing a
module, and upgrading a database that already holds data.

## Scenario A — installing a module

The thread that makes *"the schema is data"* concrete. Entry point is
`modules/loading.py::load_modules`, whose phases are named methods on
`_ModuleLoader` and run in this order:

| # | Phase | Crosses into |
|---|---|---|
| 1 | `bootstrap()` — create the base schema if the database is empty | data (DDL) |
| 2 | `run_pre_upgrade_scripts()` — *only* when upgrading existing modules | data |
| 3 | `capture_database_field_metadata()` — snapshot `ir_model_fields` **before** anything changes it | data |
| 4 | `open_environment_and_load_base()` — `base` must exist before any graph work | runtime |
| 5 | `load_languages()` | data |
| 6 | `process_module_requests()` — "updating modules list": reconcile `ir_module_module` against `addons_path` | data + module |
| 7 | `converge_module_graph()` — resolve dependencies and load each module's Python, data and views | module + data |
| 8 | `untranslate_dropped_fields()` | data |
| 9 | `finish_registry_setup()` | runtime |
| 10 | `run_end_migrations()` | data |
| 11 | `finalize_constraints()` — SQL constraints last, once all columns exist | data |
| 12 | `uninstall_removed_modules()` | data + module |
| 13 | `reinit_models_to_check()` | runtime |

Thirteen of `load_modules`' 22 calls, in call order — the nine left out are
reporting and bookkeeping (`report_modules_that_never_loaded`,
`log_assertion_report`, `flag_partially_updated_database` and the rest), which
cross no view. The numbering is this table's, not the loader's; what is pinned
is the *order*, by `test_scenario_a_phase_table_is_ordered_and_says_it_is_partial`.

Three things this ordering encodes that no other view states:

**Metadata is captured before it is mutated (3 before 7).** The comparison that
produces DDL is between the *previous* `ir_model_fields` and the field set the
loaded Python declares. Capture it after the graph converges and there is
nothing left to compare against — the schema diff is computed from a snapshot,
not from live state.

**Constraints are finalised last (11).** A constraint can reference a column a
later module in the same run adds, so applying them per module would fail on
orderings that are otherwise legal. This is the same argument as the flush
fixpoint, applied to DDL.

**Uninstalling can force a second full registry build.** Phase 12 may raise
`_UninstallRequiresReload`, which is caught and answered with a fresh
`Registry.new(…)` — logged as *"Reloading registry once more after uninstalling
modules."* Uninstall is therefore the one operation that can pay the cold
registry cost **twice** in a single command; at the 35.85 s measured in
[`qualities.md`](qualities.md#scenario-2--registry-build-and-boot), that is
the difference between a minute and two.

Under `workers > 0` the whole thread runs in one worker, and every other worker
learns about it only through the signalling tables — see
[`data.md`](data.md#2-the-signalling-tables--cross-process-coordination).

## Scenario B — upgrading a database that holds data

Installing into an empty database and upgrading a populated one are the *same
code path* with different consequences, and the difference is entirely in the
migration hooks. `modules/migration.py::migrate_module` runs at three stages:

| Stage | Marker | Runs | Use |
|---|---|---|---|
| `pre` | `[>version]` | **before** the module's models are loaded and its DDL applied | reshape data the new schema could not read |
| `post` | `[version>]` | after the module's data is loaded | backfill using the new schema |
| `end` | `[$version]` | after **every** module in the run has finished | cross-module reconciliation |

Scripts are discovered by filename prefix (`pre-`, `post-`, `end-`) under a
version directory, so a migration is selected by *the version being crossed*,
not by the module's current state.

The architectural consequence: **`pre` is the only stage that can see the old
shape.** Once the graph converges the columns have already changed, so a
migration that needs the previous representation and is written as `post` has
nothing to read. That is not recoverable at run time and not caught by any gate
in [`gates.md`](gates.md) — every one of them is structural and DB-free.

Two further asymmetries against Scenario A:

- **Cost is not comparable.** Scenario A's measured 35.85 s installs 105 modules
  into an *empty* database. An upgrade additionally rewrites existing rows, and
  nothing in this document set measures that — it is listed as a gap in
  [`qualities.md`](qualities.md#what-this-page-does-not-measure).
- **Failure is not symmetric.** A failed install leaves a database nobody was
  using; a failed upgrade leaves one somebody was. The filestore is not
  transactional with PostgreSQL either
  ([`data.md`](data.md#the-dual-storage-seam)), so a rolled-back upgrade can
  still have written attachment bytes.

## What this view does not thread

- **Backup and restore**, which crosses PostgreSQL and the filestore and is the
  most common way a deployment is broken by a torn pair.
- **Rolling restart under `workers > 0`**, where old and new workers hold
  different registries simultaneously.
- **A cron job's lifecycle**, from `ir_cron` row to `WorkerCron` execution.
