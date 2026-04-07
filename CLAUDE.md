# Odoo 19.0 Core Framework Fork

> Commit format, branch naming, workflow, environment setup, and dev commands are defined upstream:
> - `~/.claude/CLAUDE.md` (identity, commit/PR format)
> - `~/Odoo/CLAUDE.md` (orchestrator: environment, commands, skills, MCP restrictions)
>
> This file covers **core fork-specific** standards only.

## Overview

Odoo 19.0 core framework fork for Agromarin ERP.

## Branch Context

**Development Branch (19.0-marin):** Active development, refactoring allowed, no backward compatibility constraints.

**Production Branch (19.0):** Backward compatibility REQUIRED, only bug fixes, migration scripts for data model changes.

## Initial Setup: Rust Extension (odoo_rust)

Odoo 19.0 includes a Rust-compiled Python extension (`odoo_rust`) used by `web/controllers/export.py`
for CSV export. The compiled binaries are **not tracked in git** (platform-specific).

**Requirements:** Rust toolchain (`cargo`) and `maturin`.

```bash
# 1. Install Rust (if not present)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# 2. Activate virtualenv and install maturin
source <YOUR_VENV>/bin/activate
pip install maturin

# 3. Build and install the wheel
cd <ODOO_CORE_ROOT>/crates/odoo_rust
maturin build --release
pip install target/wheels/odoo_rust-*.whl
```

**When to redo:** After pulling changes to `crates/odoo_rust/src/`.

**Symptom if missing:** `ModuleNotFoundError: No module named 'odoo_rust'` on startup.

## Pre-Work Check

Some modules contain a `machine_doc_v<N>/` directory (e.g. `machine_doc_v1/`) with structured, machine-consumable maps of routes, models, architecture, conventions, and test tags. **When working on any module, check for `machine_doc_v*/` first and read it before doing anything else.** This eliminates redundant codebase exploration and provides immediate context.

## Rules Reference

- `core/ruff.toml` — Linter and formatter config (enforces `doc/coding_guidelines.rst`)
- `core/doc/coding_guidelines.rst` — Authoritative coding standards
