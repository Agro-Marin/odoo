# Odoo 19 — Core Framework Fork

This repository is **a fork of Odoo Community 19.0**
(`github.com/Agro-Marin/odoo`). What the framework core contains, how it is
layered, and which dependencies are legal is `doc/architecture/module.md` —
the canonical subsystem map, CI-enforced by `tooling/architecture/`. Read it
before restructuring core. `doc/architecture/ARCHITECTURE.md` is the front
door that indexes it: context, the forces the design answers to, the
cross-cutting mechanisms, and where new code goes.

> Throughout this file, **"repo root"** means the directory that contains this
> file. Inside it, `odoo/` is the framework core *package*, not the checkout —
> which is why `ruff check odoo/` measures the core and not `addons/`.

## Branch Model

This fork was cut from upstream Odoo and has since diverged past the point where
merging or cherry-picking between the two is possible:

- **`19.0`** — a pristine **mirror of upstream Odoo's `19.0` branch**: a copy of
  Odoo's 19.0 series, kept in sync with `github.com/odoo/odoo`. It is **not** an
  AgroMarin working branch and **not** our stable/production line. No features or
  fixes are committed here directly. Its purpose is to be **read**: a clean
  reference to diff against and to source upstream fixes from, which are then
  **re-implemented by hand** on `19.0-marin`. Dont committing AgroMarin work onto `19.0`.

- **`19.0-marin`** — the **active AgroMarin production branch**, originally forked
  from `19.0`. All AgroMarin work lands here (via pull request). This is the
  integration branch to build on. Nothing is ever merged in from `19.0`, so
  **"this would conflict with upstream" is not a reason to hold back a refactor**
  — there is no merge for it to conflict with. The wider posture this follows
  from (upstream is a baseline, not a ceiling) is *Scope and precedence* in
  `doc/coding_guidelines.rst`.

- **Feature branches** — cut from `19.0-marin` and merged back into it via PR.


## What this checkout needs

Everything under `tooling/` resolves
paths from the `odoo-bin` marker at the repo root rather than by climbing above it
(`tooling/_repo_root.py`), and CI checks this repo out alone.

- **Python ≥ 3.14** — the floor is `MIN_PY_VERSION` in `odoo/release.py`, enforced
  at import by `odoo/init.py`.
- **PostgreSQL** — every CI lane runs 18.
- **`pip install -r requirements.txt -r requirements-addons.txt`** for the
  runtime; `requirements-dev.txt` for the gates. The two runtime files split on
  ownership: `requirements.txt` is what a server process imports whatever is
  installed, `requirements-addons.txt` is what individual bundled addons own and
  declare in their `external_dependencies`. A development checkout wants both;
  only a deployment that knows which modules it loads wants the first alone.
  `requirements-test.txt` pulls in both, so every test lane is unaffected.
- **psycopg 3** (`psycopg[binary]>=3.3.4`, with `psycopg-pool>=3.3.1`) is the only
  driver `odoo/db/` uses. Never add a `psycopg2` import.
- **`crates/odoo_rust` must be built into the environment.** with a Rust toolchain on `PATH`:

  ```bash
  cd crates/odoo_rust && maturin develop
  ```

  **A build that has fallen behind the crate is worse than a missing one**: with
  no fallback, a stale `.so` segfaults on a cyclic `fast_clone` and silently
  mis-orders timezone-aware columns, and neither failure names its cause. CI
  never sees it — every lane builds the extension fresh — so it is a
  long-lived-virtualenv problem only. `crates/odoo_rust/build.rs` therefore
  stamps a CRC of the crate sources into the binary and `odoo/init.py` refuses
  to start when it disagrees with the crate on disk, naming the rebuild command.
  Rebuild after any `git pull` that touched `crates/`; the escape hatch, should
  you ever need it, is `ODOO_SKIP_RUST_FRESHNESS_CHECK=1`.

  `.github/workflows/rust.yml` gates `cargo fmt --check`,
  `cargo clippy -D warnings`, `cargo test`, the maturin build and the exported
  symbols. It blocks; it does not warn.


## Pre-Work Check

Some modules contain a `machine_doc_v<N>/` directory (e.g. `machine_doc_v1/`) with
structured, machine-consumable maps of routes, models, architecture, conventions,
and test tags. **When working on any module, check for `machine_doc_v*/` first and
read it before doing anything else.** This eliminates redundant codebase
exploration and provides immediate context. A module's own README.md or
CLAUDE.md comes next — named without backticks on purpose: these are file
*kinds* a module may carry, not paths, and a backticked path in this repo
asserts that one particular file exists.

## Tests

### Python — pytest, from the repo root

Two invocations, **mutually exclusive**: the DB-free suites register
process-global `sys.modules` stubs (`odoo/_testing_bootstrap.py`) that would
shadow the real `import odoo.*` the second group performs.

```bash
pytest                                                # DB-free leaf suites
pytest odoo/orm/tests odoo/http/tests tests/service   # real-import suites
```

**Pass all three paths in the second command.** None of them is in `pytest.ini`'s
`testpaths`, so a shorter command silently skips whole suites while still
reporting success — `odoo/orm/tests` alone never touches http or `tests/service`.

Both must run **from the repo root**: `testpaths` and `pythonpath = .` resolve
against the rootdir located by `pytest.ini`. Started from a parent, the tree is
collected as plain files and fails en masse (~1900 collection errors) rather than
skipping quietly.

Two suites are in no `testpaths` and run only when named
(CI: `.github/workflows/service_suites.yml`):

```bash
ODOO_CONTRACT_REQUIRE_DEPS=1 pytest tests/contract   # needs PostgreSQL + psql + pg_dump
pytest tests/process                                 # boots real odoo-bin processes
```

`tests/contract` pins what we *assume* about psycopg, psql and pg_dump against the
real programs — it is skip-guarded, so without that variable a missing dependency
reports green while comparing nothing.

Integration tests need a database and run through `odoo-bin`:

```bash
odoo-bin -d <db> -i <module> --test-enable --stop-after-init
```

### JS (HOOT) — use the warm runner

`tooling/hoot/hoot` keeps one dev server warm across invocations and drives Chrome
through Odoo's own `ChromeBrowser` CDP driver, so a run costs neither an ERP boot
nor a bundle build. Prefer it to `odoo-bin`, which pays both every time.

```bash
cd tooling/hoot
./hoot '@web/core/domain'                  # one suite
./hoot --affected <changed files…>         # suites those files touch
./hoot --preset mobile '@web/webclient'    # mobile pass — resizes Chrome, toggles touch
./hoot-shard -j 4                          # the whole web suite, sharded
```

**Name the paths for `--affected`.** Bare, it selects from the entire `git diff`,
so any unrelated modification in the checkout widens the run beyond your change.

Falling back to `odoo-bin`, select **one file**; the suite path is a bracketed
parameter, not a dotted path:

```bash
odoo-bin -d <db> --test-enable --stop-after-init \
    --test-tags '/web:WebSuite.test_core[@web/core/domain]'   # 78 tests, measured 6.1s
```

Dropping the bracket runs the whole group (1803 tests, ~50s), and the `web_js` tag
runs for hours (the tag table below estimates 1–2, and flags that as an estimate
rather than a measurement). Do not add `-u web`: it is not needed to pick up JS
changes and
costs ~50%. A spec matching no test exits non-zero, but still read
`odoo.tests.result: … of N tests`.

Full recipes, preset/tag semantics and the stale-source caveat:
`addons/web/machine_doc_v1/TEST_TAGS.md`. The *rule* for which tag a test carries
is a coding standard, not a recipe: `doc/coding_guidelines.rst` §6.7.

## Coding Guidelines

**Before writing or modifying any code in this repo, read and follow
`doc/coding_guidelines.rst` (repo root).** It is the **single authoritative
source** for AgroMarin coding standards — built on Odoo 19.0 + OCA conventions,
and authoritative where it speaks; where it is silent, follow upstream Odoo 19 /
OCA. It supersedes any other `coding_guidelines` file. Each rule names the gate that catches it —
`[ruff CODE]`, `[test_lint CODE]`, `[fixer NAME]` or `[review]`; see *How rules
are enforced* at the top of the guide.

The guide is comprehensive — consult the relevant section for the work at hand:

1. Module Structure · 2. Python · 3. XML · 4. JavaScript (OWL) · 5. CSS/SCSS
· 6. Tests · 7. Git (commits, branch naming, task IDs, PRs) · 8. Translations
· 9. Code Review Checklist · 10. Security · 11. Performance · 12. Migration
Scripts (+ Appendices A–D: fork field renames, references, retired patterns,
document history)

Related:

- `ruff.toml` (repo root) — linter and formatter config, with the rationale for
  every suppression. Note `ruff check` is **not** expected to be clean: CI runs it
  as a ratchet against a committed floor (`tooling/ratchet/baselines/`), and **a
  ratchet fails in both directions** — lowering a count without committing the new
  floor fails the build too. Ruff is one of several ratcheted gates; **the
  baselines directory is the list and `tooling/ratchet/ratchet.py --list` is the
  reading — no file states how many there are or what they hold**, because a
  restated floor is a second copy that drifts, and this line said "eleven" against
  thirteen baseline files. Per-gate scope, commands and the `--update` recipe are
  *The ratchets* in the guide, the canonical account; it also covers the trap that
  the ruff floor measures `odoo/` and not `addons/`. One thing the guide does not:
  `.github/workflows/ruff.yml` lints **`tooling/` and `tests/` at a hard zero** in
  a separate blocking step, with no floor to absorb a new finding.
- `odoo/addons/test_lint/` — the fork's own AST checkers and registry gates: SQL
  built from non-constant values, gettext misuse, N+1 queries, ORM-facade imports,
  XML/manifest canonical form, asset bundles that do not assemble, UNIQUE
  declared over a translated (jsonb) column. Each is an
  exact-match ratchet, so an undone fix fails as loudly as a new offence. CI runs
  it in `.github/workflows/test_lint.yml` (whole module, every PR, no `paths:`
  filter) and `.github/workflows/asset_lint.yml` (the registry-dependent
  classes).

  **The floors are defined at the CI scope**, which is
  `--addons-path=odoo/addons,addons` with only `test_lint` installed. Harvest
  and verify them there, not against a workspace that also carries
  `enterprise/` — the two measure different trees, and floors taken from the
  larger one cannot pass in CI:

  ```bash
  odoo-bin --addons-path=odoo/addons,addons -d <db> -i test_lint \
      --test-enable --test-tags /test_lint --stop-after-init --no-http
  ```

  The handful of gates that read the *installed registry* rather than the tree
  (`test_docstring`) are one-sided ratchets for that reason, and say so.

- `.github/workflows/` — **check it before assuming a gate does not exist.** The
  suites, ratchets, architecture, doc-link, free-threading, Rust and vendored-lib
  lanes all live there.
- Changes to the guidelines are made by editing `doc/coding_guidelines.rst`
  directly. Its *Change protocol* binds what you do next: the same PR updates the
  `CLAUDE.md` files that summarise the rule — this one included — and adds a row
  to Appendix D. Rules are retired into Appendix C, never deleted silently.
