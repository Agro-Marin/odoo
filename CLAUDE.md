# Odoo 19.0 Core Framework Fork

Main Odoo source code: the ORM, web framework, base module, and all standard addons.
This is AgroMarin's fork — we fix bugs, improve design, and modernize aggressively.

## What Lives Here

- `odoo/` — ORM, tools, CLI, HTTP server, service layer
- `addons/` — All standard Odoo modules (account, sale, stock, mail, web, etc.)
- `crates/odoo_rust/` — Rust-compiled Python extension for CSV export
- `doc/coding_guidelines.rst` — Authoritative coding standards

For AgroMarin's custom business modules, see [agromarin/CLAUDE.md](../agromarin/CLAUDE.md).
For the project root, see [CLAUDE.md](../../CLAUDE.md).

## Branch Strategy

- **`19.0`** (production): backward compatibility REQUIRED, only bug fixes, PRs mandatory
- **`19.0-marin`** (integration): active development, refactoring allowed
- **Feature branches**: `19.0-<tag>-<topic>` (e.g., `19.0-imp-mail-ruff-styling`)

## Development Commands

All commands assume you're in the project root (`~/Odoo`), not inside `core/`.
See [root CLAUDE.md](../../CLAUDE.md) for the full quick reference (run, test,
fresh database, check results).

## Rust Extension (odoo_rust)

Odoo 19.0 includes a Rust-compiled Python extension (`odoo_rust`) used by
`web/controllers/export.py` for CSV export. Compiled binaries are not tracked in git
(platform-specific). Each developer must compile and install once.

**Requirements:** Rust toolchain (`cargo`) and `maturin`.

```bash
# 1. Install Rust (if not present)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# 2. Activate virtualenv and install maturin
source ./venv/odoo/bin/activate
pip install maturin

# 3. Build and install the wheel
cd addons/core/crates/odoo_rust
maturin build --release
pip install target/wheels/odoo_rust-*.whl
cd ../../..
```

**When to redo:** After pulling changes to `crates/odoo_rust/src/`.

**Symptom if missing:** `ModuleNotFoundError: No module named 'odoo_rust'` on startup.

## Font Awesome 7 (upgraded from FA4)

This fork uses **Font Awesome Pro 7.2.0** (`web/static/src/libs/fontawesome7/`).
Upstream Odoo uses Font Awesome 4. Key differences when writing views and templates:

| FA4 (upstream Odoo) | FA7 (this fork) |
|---------------------|-----------------|
| `fa fa-pencil` | `fa-solid fa-pencil` |
| `fa fa-trash-o` | `fa-regular fa-trash-can` |
| `fa fa-cog` | `fa-solid fa-gear` |
| `fa fa-times` | `fa-solid fa-xmark` |
| `fa fa-warning` | `fa-solid fa-triangle-exclamation` |
| `fa fa-check-square-o` | `fa-regular fa-square-check` |

**Prefix changes**: `fa` alone is no longer valid. Use `fa-solid`, `fa-regular`, or `fa-brands`.
Many icon names changed — check the [FA7 icon gallery](https://fontawesome.com/icons) when unsure.

## Documentation in This Repo

| File | What it covers |
|------|---------------|
| `doc/coding_guidelines.rst` (66KB) | **Authoritative** coding standards for all Odoo code |
| `doc/FORK_CHANGELOG.md` (52KB) | Complete history of every fork change vs upstream |
| `doc/orm_comparison.md` (35KB) | ORM patterns reference and comparison |
| `ruff.toml` (18KB) | Core-specific linter config (413 lines of rules) |

## Machine Documentation

Three modules have pre-built architecture docs in `machine_doc_v1/`:

| Module | Files | Key docs |
|--------|-------|----------|
| `addons/web/machine_doc_v1/` | 9 files | ARCHITECTURE, JS_FILE_INDEX, STATE_MANAGEMENT, ROUTE_MAP |
| `addons/mail/machine_doc_v1/` | 7 files | ARCHITECTURE, JS_ARCHITECTURE, MODELS, ROUTE_MAP |
| `addons/gamification/machine_doc_v1/` | 4 files | architecture, models, conventions |

**Always check `machine_doc_v1/` before exploring** a module — it saves significant context.

## See Also

- [Root CLAUDE.md](../../CLAUDE.md) — Project structure, test commands, coding standards
- [agromarin/CLAUDE.md](../agromarin/CLAUDE.md) — Business modules, MCP, task management
- [.claude/rules/](../../.claude/rules/) — Python modernization, Odoo 19 patterns, performance
