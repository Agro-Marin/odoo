# AgroMarin Odoo 19 — Core Framework Fork (`addons/core`)

This repository is **a fork of Odoo Community 19.0**
(`github.com/Agro-Marin/odoo`): the Odoo framework plus its bundled base addons.

> Throughout this file, **"repo root"** means the directory that contains this
> file — the `core` checkout itself.

## Branch Model

This fork tracks upstream Odoo and layers AgroMarin work on top of it:

- **`19.0`** — a pristine **mirror of upstream Odoo's `19.0` branch**: a copy of
  Odoo's 19.0 series, kept in sync with `odoo/odoo`. It is **not** an AgroMarin
  working branch and **not** our stable/production line. No features or fixes are
  committed here directly; its only purpose is to ingest upstream changes and
  serve as the baseline that `19.0-marin` merges from. Committing AgroMarin work
  onto `19.0` would make it diverge from upstream and break the next sync — don't.

- **`19.0-marin`** — the **active AgroMarin production branch**, forked from
  `19.0`. All AgroMarin work lands here (via pull request). This is the
  integration branch you build on: refactoring is allowed, with no upstream
  backward-compatibility constraints.

- **`19.0-t<NNNNN>-<developer>`** — per-task feature branches cut from
  `19.0-marin` and merged back into it via PR (`<NNNNN>` = task id,
  `<developer>` = author handle).

## Pre-Work Check

Some modules contain a `machine_doc_v<N>/` directory (e.g. `machine_doc_v1/`) with
structured, machine-consumable maps of routes, models, architecture, conventions,
and test tags. **When working on any module, check for `machine_doc_v*/` first and
read it before doing anything else.** This eliminates redundant codebase
exploration and provides immediate context.

## Rules Reference

- **Canonical coding guidelines**: `doc/coding_guidelines.rst` (repo root) — the
  single authoritative source for AgroMarin, superseding any other
  `coding_guidelines` file inside a code repo. It is canonical for **all**
  AgroMarin repos in the workspace (`core`, `enterprise`, `agromarin`,
  `design-themes`, `knowledge`), which defer to it. AgroMarin-specific rules are
  tagged **[AM]**; everything else follows upstream Odoo / OCA conventions.
- `ruff.toml` (repo root) — linter and formatter config, aligned with the
  canonical guidelines (§2.6 and §2.9).
- Changes to the canonical guidelines are made by editing
  `doc/coding_guidelines.rst` directly