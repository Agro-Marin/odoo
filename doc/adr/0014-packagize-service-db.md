# ADR-0014: Packagize service/db.py into `odoo/service/db/`

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

odoo/service/db.py was **1633 lines and 42 top-level definitions** — the largest
un-decomposed module in the core and the least cohesive of its large ones. Size
is not the argument: `tools/config.py` is bigger (1971) and `orm/fields/base.py`
comparable, and both are cohesive — few top-level names, deep bodies. This one
was large **and** flat, holding four unrelated concerns:

| Concern | Members |
|---|---|
| Database lifecycle DDL | `_create_empty_database`, `_drop_database`, `_duplicate_database`, `_rename_database`, the two rollbacks, the terminate-then-DDL retries |
| Backup / restore, incl. archive-bomb defence | `dump_db`, `restore_db`, `_run_pg_dump_blocking`, `_run_pg_dump_streaming`, `_write_zip_dump`, `_extract_members_bounded`, `_unpack_budget` |
| The `/web/database/manager` RPC surface | the 14 `exp_*` functions, `dispatch`, `_DISPATCH`, `_REQUIRES_MASTER_PASSWORD` |
| Listing and static metadata | `list_dbs`, `list_db_incompatible`, `exp_list_lang`, `_scan_countries`, `exp_list_countries`, `exp_server_version` |

Zip-bomb bounds and pg_dump timeout escalation were interleaved with DDL retry
logic; "what does the database manager expose" had no one-file answer.

ADR-0003 made this move one package over, packagising sql_db.py into `odoo/db/`
on the same argument. This record applies that precedent.

## Decision

Split into `odoo/service/db/`, five modules with a one-way dependency order:

```
rpc          dispatch table + master-password gate
 ├── restore   restore_db, and the bounds that stop a hostile archive
 │    ├── lifecycle
 │    └── listing
 ├── dump      pg_dump, the zip envelope, the filestore beside it
 │    └── listing
 ├── lifecycle create / drop / duplicate / rename + the DDL retries
 │    └── listing
 └── listing   which databases exist, which are exposed, static lists
```

`__init__.py` re-exports the public surface (`__all__`, 33 names), so every
existing importer is unchanged — `http/helpers.py`, `http/request_class.py`,
`cli/db.py`, `cli/start.py`, `addons/web/controllers/database.py`.

Each `exp_*` lives with the operation it exposes rather than all together in
`rpc`: grouping by "is RPC-visible" would re-create a flat module with an extra
hop. `rpc` keeps `dispatch`, the two tables, and the two operations that exist
only for the endpoint (`exp_change_admin_password`, `exp_migrate_databases`).

Deliberately not moved:

- `_db_helpers.py` — also used by `service/model.py` and `service/common.py`, so
  a `service/` helper, not a `db/` one.
- `_env.py` — used by six modules across `service/`.
- `_dump_scanner.py` — db-specific, but `tests/contract/` imports it by path in
  three modules and it is already a well-named sibling.

Every module logs to `odoo.service.db`, spelled literally, as `_db_helpers` and
`_dump_scanner` already did.

## The consequence that needed handling: patch targets

`tests/service/test_db.py` (2700 lines, 232 tests) patched module-level names in
`odoo.service.db` at 196 sites: 137 `patch.object(db_mod, …)`, 59 string
targets, plus `monkeypatch.setattr`. While `db.py` was one module those reached
the binding every caller used. Against a package they do not: `__init__`'s names
are re-exports, so rebinding one leaves `lifecycle.X` — what the code calls —
untouched.

Half of that fails loudly (the package has no `subprocess`, so `patch.object`
raises `AttributeError`). **The other half is silent**, and it bit during this
work: patching `lifecycle._create_empty_database` never reached `restore`'s own
bound name, so `restore_db` ran the real function. Seven tests surfaced it as
`KeyError: 'db_app_name'` — loudly only because the real function needed config
the mock lacked. A cheaper function would have passed while asserting nothing.

Resolved three ways:

1. **Targets follow the caller, not the definition.** Every site was retargeted
   to the module whose binding the code under test uses — `db_mod.lifecycle`,
   `"odoo.service.db.listing.list_dbs"`. Submodules are reachable as package
   attributes, so no new fixtures were needed.
2. **`tests/service/test_db_patch_targets.py` gates it.** It rejects any patch
   aimed at the package and any target naming a submodule that does not bind the
   name, and carries a non-vacuity test proving the detectors fire. Names whose
   production caller genuinely reads the package attribute at call time
   (`check_super`, `list_dbs`, `dispatch`, `restore_db`, `dump_db` — the web
   controller does `from odoo.service import db` then `db.check_super(...)`) are
   listed as `PACKAGE_LEVEL_OK` with that justification.
3. **Three addon-test patches** in `addons/base/tests/test_db_cursor.py` were
   retargeted for the same reason. Those in `addons/web` and `addons/test_http`
   were checked and left: their production callers read the package attribute.

## Alternatives considered

**Leave it flat.** The module works; the cost is diffuse reading cost. Rejected:
the same argument was made and rejected for sql_db.py in ADR-0003, and these
concerns are further apart than that module's were.

**Split without re-exports**, making every importer name a submodule. Cleaner
dependency-wise, and it would have made the patch problem impossible rather than
merely gated. Rejected: it changes the import surface for `cli/`, `http/` and
`addons/web` for no architectural gain, and the façade is what lets the internal
layout keep moving — the bargain ADR-0008 makes for the ORM.

**Bracketed tiers with a `layer_check` contract**, as `db/` and `http/` have.
Not done yet: those contracts were added after their tiers had been measured and
found already-layered. A contract should follow a measurement, not precede one.
The direction here is asserted by construction and documented in the package
`__init__`.

## Consequences

- Five modules of 141–665 lines replace one of 1633; the dependency order is a
  reading order.
- The public surface is one explicit `__all__` rather than whatever happened to
  be module-level.
- **Patching this package requires knowing which module owns the name.** A real
  cost on test authors, and why the gate exists — the failure it prevents is a
  green test that asserted nothing.
- `doc/architecture/module.md`'s subsystem map enumerates `service/`
  exhaustively, so `subsystem_map_check.py` failed until the map named the new
  package.

## Enforcement

`tests/service/test_db_patch_targets.py` (patch targets, and that the package is
still a package), `subsystem_map_check.py` (the map against the tree), and the
standing `tests/service` suite — 232 tests over this code, same count as before
the split.
