# AgroMarin Odoo 19 — Core Framework Fork

This repository is **a fork of Odoo Community 19.0**
(`github.com/Agro-Marin/odoo`): the Odoo framework plus its bundled base addons.

> This repo is deployed as one checkout inside a larger workspace. Environment
> setup, launch commands, addons_path priority, and concurrent-session rules
> live in that workspace's root `CLAUDE.md` — wherever the checkouts are
> assembled. This file covers only what is specific to the `odoo` checkout,
> wherever it is cloned.
>
> Throughout this file, **"repo root"** means the directory that contains this
> file — the `odoo` checkout itself.

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

## Running JS (HOOT) tests — read before your first run

Select **one file**, never a whole group. The suite path is a bracketed
parameter, not a dotted path:

```bash
odoo-bin -d <db> --test-enable --stop-after-init \
    --test-tags '/web:WebSuite.test_core[@web/core/domain]'      # 78 tests, ~6s
```

The bare `--test-tags '/web:WebSuite.test_core'` runs 1803 tests (~50 s), and
the `web_js` tag runs for an hour. Do not add `-u web` — it changes nothing for
JS and costs ~50%. A spec matching no test now exits non-zero, but still read
`odoo.tests.result: … of N tests`.

`tooling/hoot/hoot` keeps a server warm and takes plain suite
paths (`./hoot '@web/core/domain'`, `./hoot --affected`, `./hoot-shard`).
Full recipes, preset/tag semantics and the stale-source caveat:
`addons/web/machine_doc_v1/TEST_TAGS.md`. The *rule* for which tag a test
carries is a coding standard, not a recipe: `doc/coding_guidelines.rst` §6.7.

## Coding Guidelines

**Before writing or modifying any code in this repo, read and follow
`doc/coding_guidelines.rst` (repo root).** It is the **single authoritative
source** for AgroMarin coding standards — built on Odoo 19.0 + OCA conventions,
and authoritative where it speaks; where it is silent, follow upstream Odoo 19 /
OCA. It supersedes any other `coding_guidelines` file inside a code repo and is
canonical for **all** AgroMarin Odoo-code repos — sibling checkouts defer to
it. Each rule names the
gate that catches it — `[ruff CODE]`, `[test_lint CODE]`, `[fixer NAME]` or
`[review]`; see *How rules are enforced* at the top of the guide.

The guide is comprehensive — consult the relevant section for the work at hand:

1. Module Structure · 2. Python · 3. XML · 4. JavaScript (OWL) · 5. CSS/SCSS
· 6. Tests · 7. Git (commits, branch naming, task IDs, PRs) · 8. Translations
· 9. Code Review Checklist · 10. Security · 11. Performance · 12. Migration
Scripts (+ Appendices A–D: fork field renames, references, deprecated patterns,
document history)

Related:

- `ruff.toml` (repo root) — linter and formatter config, with the rationale for
  every suppression. Note `ruff check` is **not** expected to be clean: CI runs it
  as a ratchet against a committed floor (`tooling/ratchet/baselines/`, scope
  `odoo/` only). The ratchet runs in `exact` mode, so **lowering** the count fails
  the build too — commit the new floor with
  `python tooling/ratchet/ratchet.py ruff --count <N> --update` in the same PR.
  Ruff is one of several ratcheted gates (`mypy`, `tsc`, `eslint`, JS
  size/privacy checks — see the baselines dir). See *The ratchets* in the guide.
- `odoo/addons/test_lint/` — the fork's own AST checkers and registry gates. Not
  wired into CI; run it yourself with
  `odoo-bin -d <db> -i test_lint --test-enable --stop-after-init`.
- Changes to the guidelines are made by editing `doc/coding_guidelines.rst`
  directly