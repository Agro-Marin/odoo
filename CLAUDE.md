# Odoo 19 — Core Framework Fork

Fork of Odoo Community 19.0 (`github.com/Agro-Marin/odoo`).

| Document | Role |
|---|---|
| `doc/architecture/module.md` | Canonical subsystem map: what the core contains, how it is layered, which dependencies are legal. Enforced by `tooling/architecture/`. Read before restructuring core. |
| `doc/architecture/ARCHITECTURE.md` | Front door indexing the above: context, design forces, cross-cutting mechanisms, where new code goes. |

> **"Repo root"** = the directory containing this file. Inside it, `odoo/` is the framework core *package*, not the checkout — which is why `ruff check odoo/` measures the core and not `addons/`.

## Branch Model

Diverged from upstream past the point where merging or cherry-picking between the two is possible.

| Branch | Rule |
|---|---|
| `19.0` | Pristine mirror of upstream `github.com/odoo/odoo` 19.0. **Not** an AgroMarin working branch, **not** the stable/production line. Exists to be read: diff against it, source upstream fixes from it, then **re-implement by hand** on `19.0-marin`. Never commit AgroMarin work here. |
| `19.0-marin` | Active AgroMarin production branch, forked from `19.0`. All work lands here, directly or via PR; this is the integration branch to build on. Nothing is ever merged in from `19.0` — **"this would conflict with upstream" is not a reason to hold back a refactor**, there is no merge for it to conflict with. Posture: *Scope and precedence*, `doc/coding_guidelines.rst`. |
| Feature branches | Cut from `19.0-marin`, merged back into it via PR. |

**No branch carries protection as of 2026-09-01 — direct pushes are allowed.** Feature branches and PRs stay preferred for planned work; never force-push a shared branch.

## Checkout Requirements

`tooling/` resolves paths from the `odoo-bin` marker at the repo root rather than by climbing above it (`tooling/_repo_root.py`). The tools work with this repo checked out alone.

| Requirement | Detail |
|---|---|
| Python ≥ 3.14 | Floor is `MIN_PY_VERSION` in `odoo/release.py`, enforced at import by `odoo/init.py`. |
| PostgreSQL | 18. |
| psycopg 3 | `psycopg[binary]>=3.3.4` with `psycopg-pool>=3.3.1` — the only driver `odoo/db/` uses. Never add a `psycopg2` import. |
| Requirements | `pip install -r requirements.txt -r requirements-addons.txt` for runtime; `requirements-dev.txt` for the gates. The two runtime files split on ownership: `requirements.txt` is what a server process imports whatever is installed, `requirements-addons.txt` is what individual bundled addons own and declare in `external_dependencies`. A development checkout wants both; only a deployment that knows which modules it loads wants the first alone. `requirements-test.txt` pulls in both, so every test run is unaffected. |
| `crates/odoo_rust` | Build it into the environment, with a Rust toolchain on `PATH`. With `CI=true` or `ODOO_REQUIRE_NATIVE=1` its absence is an `ImportError` at `odoo/init.py`. Elsewhere its absence is a `RuntimeWarning` and the process runs on the pure-Python twins behind `odoo/libs/accel.py` — slower, not wrong. A *stale* build is still fatal (`assert_fresh`). |

```bash
cd crates/odoo_rust && maturin develop --release
```

### `--release` is not optional

`maturin develop` defaults to the `dev` profile. A debug build is not merely slower — three exports come in slower than the pure Python they exist to delete:

| Export | Debug vs pure Python |
|---|---|
| `origin_ids` | 4.08x |
| `to_prefetch_ids` | 2.53x |
| `sort_ids_by_cache` | 2.41x |

The profile is stamped beside the source fingerprint; `odoo/libs/native.py` refuses to start on a debug build. Escape hatch for attaching a debugger: `ODOO_ALLOW_DEBUG_RUST=1`.

### A stale build is worse than a missing one

The pure-Python twins step in only when the extension is *absent*; a stale `.so` is imported and used. Before the freshness check, a stale build segfaulted on a cyclic `fast_clone` and silently mis-ordered timezone-aware columns; neither failure names its cause. A fresh build never sees it, so it is a long-lived-virtualenv problem only.

Each crate's `build.rs` stamps a CRC of its sources into the binary (`crates/odoo_build`); `odoo/libs/native.py` refuses to proceed when it disagrees with the crate on disk, naming the rebuild command. Rebuild after any `git pull` that touched `crates/`. Escape hatch: `ODOO_SKIP_RUST_FRESHNESS_CHECK=1`.

### `crates/` is a cargo workspace of three

| Crate | Role |
|---|---|
| `odoo_rust` | The runtime extension above. |
| `odoo_lint` | Parallel source scanner behind five `test_lint` gates. **Not** a runtime dependency — build only to run those gates: `cd crates/odoo_lint && maturin develop --release`. Separate wheel because it is test-only and dominated the runtime one: 1156 KB / 35 crates with it, 266 KB / 15 without. |
| `odoo_build` | Shared build-script support, so the fingerprint algorithm that must match `odoo/libs/native.py` exists once. |

Run `cargo fmt --all`, `cargo clippy --workspace`, `cargo test --workspace` from `crates/`, not from a member.

The crate checks are `cargo fmt --all --check`, `cargo clippy --workspace -D warnings`, `cargo test --workspace`, both maturin builds, and the exported symbols — including that `odoo_rust` has **not** regained the scanner.

## Pre-Work Check

Some modules carry a `machine_doc_v<N>/` directory (e.g. `machine_doc_v1/`) with structured, machine-consumable maps of routes, models, architecture, conventions and test tags.

- **Check for `machine_doc_v*/` first and read it before doing anything else.** This eliminates redundant codebase exploration.
- A module's own README.md or CLAUDE.md comes next — named without backticks on purpose: these are file *kinds* a module may carry, not paths, and a backticked path in this repo asserts that one particular file exists.
- That is an enforced rule, not a stylistic note: `factcheck.sh` resolves every backticked path in these directories, including inside a backticked *command*, so a deliberately-absent file is named in plain prose.

### Figures are gated or frozen, never bare

You read these first, so their numbers become your premises (`doc/coding_guidelines.rst` §1.4).

| Kind | Meaning |
|---|---|
| Gated | The module's `factcheck.sh` derives it from the tree and asserts the document cites it (`assert_doc_cites`). The expected value is never a literal in the script — that would make the script a second copy of the tree. |
| Frozen | Pinned to a named base commit, for readings that cannot be re-derived (a profile, a benchmark, an ad-hoc scanner). **Do not "correct" a frozen figure to a current value** — the argument built on it rests on that base. |

Run the module's harness after changing its docs, and before believing them:

```bash
bash addons/<module>/machine_doc_v1/factcheck.sh
```

**And after changing its `tests/`.** A gated figure is derived from the tree, so a page counting test classes and methods is a function of `tests/`, and any commit adding or removing a test invalidates it — while every suite of the changed module still passes, because the page is checked by its harness and not by the tests. Adding four tests to `addons/base` took this harness to 716/1 with `/base` green at 3,721. **A file you did not edit can be invalidated by the one you did, and no run of the changed file will say so**; the harness is blocking and unratcheted, so the cost is a red gate nobody owns.

### The machine_doc harnesses

Every `factcheck.sh` under `odoo` and `addons` blocks.

- Discovery must walk the whole repo. A root list of `odoo/addons addons` missed `odoo/tests/machine_doc_v1`, which shipped and was read as authoritative while nothing could see it.
- A machine_doc with no harness is the standing list of what is ungated. **That list is empty**: every machine doc in this repository is gated and blocking as of 2026-08-27. `base` was the last, and closing it turned up a Model Index giving `ir.mail_server` as `ir.mail.server` (no such model; the lookup raises), a BLAKE3 pointer still at `odoo/tools/hashing.py` after the libs/tools split moved it, and a TEST_TAGS.md claiming 85 test files against 126. An empty warning list is the thing to keep true, not permission to skip checking.

## Tests

### Python — pytest, from the repo root

Two invocations, **mutually exclusive**: the DB-free suites register process-global `sys.modules` stubs (`odoo/_testing_bootstrap.py`) that would shadow the real `import odoo.*` the second group performs.

```bash
pytest                                     # DB-free leaf suites
pytest odoo/orm/tests odoo/http/tests \
       odoo/db/tests odoo/tools/tests \
       tests/service tests/framework       # real-import
```

- **Pass all six paths in the second command.** None is in `pytest.ini`'s `testpaths`, so a shorter command silently skips whole suites while still reporting success — `odoo/orm/tests` alone never touches http or `tests/service`.
- `odoo/db/tests` and `odoo/tools/tests` are real-import suites because they reach state living in a package `__init__.py`, which the Tier-1 stubs replace with a namespace-only module.
- Both run **from the repo root**: `testpaths` and `pythonpath = .` resolve against the rootdir located by `pytest.ini`. Started from a parent, the tree is collected as plain files and fails en masse (~1900 collection errors) rather than skipping quietly.

Two suites are in no `testpaths` and run only when named:

```bash
ODOO_CONTRACT_REQUIRE_DEPS=1 pytest tests/contract   # needs PostgreSQL + psql + pg_dump
pytest tests/process                                 # boots real odoo-bin processes
```

`tests/contract` pins what we *assume* about psycopg, psql and pg_dump against the real programs. It is skip-guarded: without that variable a missing dependency reports green while comparing nothing.

### Integration — through `odoo-bin`

```bash
odoo-bin -d <db> -i <module> --test-enable --stop-after-init
```

**Before re-running one to find out whether a failure is yours, diff it against the recorded set.** `tooling/testbaseline/` holds an expected-failure baseline per suite:

```bash
odoo-bin -d <db> -i <module> --test-enable --stop-after-init \
    --test-tags '/<module>' --logfile run.log
tooling/testbaseline/testbaseline.py /<module> run.log   # 0 new, 0 newly-passing = green
```

It diffs failure **names**, not counts — `quality_control` held at 2 across a day in which one recorded test was fixed and an unrecorded one broke, and a count comparison calls that "both known". `--list` is the roster; a suite with no baseline gets no verdict rather than a guess. Its README carries the measurements behind each choice.

### JS (HOOT) — use the warm runner

`tooling/hoot/hoot` keeps one dev server warm across invocations and drives Chrome through Odoo's own `ChromeBrowser` CDP driver, so a run costs neither an ERP boot nor a bundle build. Prefer it to `odoo-bin`, which pays both every time.

```bash
cd tooling/hoot
./hoot '@web/core/domain'                  # one suite
./hoot --affected <changed files…>         # suites those files touch
./hoot --preset mobile '@web/webclient'    # mobile pass — resizes Chrome, toggles touch
./hoot-shard -j 4                          # the whole WEB suite, sharded
./hoot-shard --addons -j 4 --db-prefix hoot_all   # every addon that ships a suite
```

**`hoot-shard` without `--addons` is web and `html_editor`, which is 849 of the 1,979 JS test files in the workspace.** Its plan comes from each addon's `tests/test_js.py`, and 16 of the 184 addons that ship a `static/tests/**/*.test.js` wrote one — so everything else is reported as neither passed nor failed, not as skipped. `@hr` carried eight failing tests through a run printing `0 failed / 16294 passed` for exactly this reason. `--addons` enumerates from the tree instead; give it its own `--db-prefix`, because a shard installs every module its suites name.

**Name the paths for `--affected`.** Bare, it selects from the entire `git diff`, widening the run beyond your change.

Falling back to `odoo-bin`, select **one file**; the suite path is a bracketed parameter, not a dotted path:

```bash
odoo-bin -d <db> --test-enable --stop-after-init \
    --test-tags '/web:WebSuite.test_core[@web/core/domain]'   # 78 tests, measured 6.1s
```

- Dropping the bracket runs the whole group: 1803 tests, ~50s.
- The `web_js` tag runs for hours. The tag table estimates 1–2 and flags that as an estimate, not a measurement.
- Do not add `-u web`: it is not needed to pick up JS changes and costs ~50%.
- A spec matching no test exits non-zero, but still read `odoo.tests.result: … of N tests`.

Full recipes, preset/tag semantics and the stale-source caveat: `addons/web/machine_doc_v1/TEST_TAGS.md`. Which tag a test carries is a coding standard: `doc/coding_guidelines.rst` §6.7.

## Coding Guidelines

**Before writing or modifying any code in this repo, read and follow `doc/coding_guidelines.rst` (repo root).** It is the single authoritative source for AgroMarin coding standards — built on Odoo 19.0 + OCA conventions, authoritative where it speaks; where silent, follow upstream Odoo 19 / OCA. It supersedes any other `coding_guidelines` file.

Each rule names the gate that catches it — `[ruff CODE]`, `[test_lint CODE]`, `[fixer NAME]` or `[review]`; see *How rules are enforced* at the top of the guide.

Sections: 1. Module Structure · 2. Python · 3. XML · 4. JavaScript (OWL) · 5. CSS/SCSS · 6. Tests · 7. Git (commits, branch naming, task IDs, PRs) · 8. Translations · 9. Code Review Checklist · 10. Security · 11. Performance · 12. Migration Scripts · Appendices A–D (fork field renames, references, retired patterns, document history).

### `ruff.toml` (repo root)

Linter and formatter config, with the rationale for every suppression.

- `ruff check` is **not** expected to be clean: it runs as a ratchet against a committed floor (`tooling/ratchet/baselines/`), and **a ratchet fails in both directions** — lowering a count without committing the new floor fails the build too.
- `pyfunclen_addons` is the single exception, invoked `--mode no-increase` because the bundled-addons tree is too wide to hold still; argument in *The ratchets*.
- Ruff is one of several ratcheted gates. **The baselines directory is the list of debt and `tooling/ratchet/ratchet.py --list` is the reading** — no file states how many there are or what they hold, because a restated floor is a second copy that drifts. The guide's table is a deliberate sample, not the membership. A gate handed to `ratchet.py` with no baseline file is a **hard zero**: it passes at 0 and fails above, and `--update` is what opens a floor.
- Per-gate scope, commands and the `--update` recipe: *The ratchets* in the guide, the canonical account. It also covers the trap that the ruff floor measures `odoo/`, not `addons/`.
- Not in the guide: **`tooling/` and `tests/` are linted at a hard zero**, with no floor to absorb a new finding.

### `odoo/addons/test_lint/`

The fork's own AST checkers and registry gates: SQL built from non-constant values, gettext misuse, N+1 queries, ORM-facade imports, XML/manifest canonical form, asset bundles that do not assemble, UNIQUE declared over a translated (jsonb) column.

Each is an exact-match ratchet, so an undone fix fails as loudly as a new offence. The AST rules run at the narrow scope below; the registry-dependent classes need a fuller install. The AST rules run `E8501`–`E8513`; none is advisory and none fails outright — the floor decides.

**The floors are defined at the narrow scope**, which is `--addons-path=odoo/addons,addons` with only `test_lint` installed. Harvest and verify them there, not against a workspace that also carries `enterprise/` — the two measure different trees, and floors taken from the larger one cannot pass at the narrow scope:

```bash
odoo-bin --addons-path=odoo/addons,addons -d <db> -i test_lint \
    --test-enable --test-tags /test_lint --stop-after-init --no-http
```

**The floors are not in Python.** `LintCase.assert_ratchet` takes a ratchet gate name and reads `tooling/ratchet/baselines/` like every other gate; handed an integer it raises, so one cannot go back. Absence of a baseline file means a floor of zero, which keeps `ratchet.py --list` a list of debt rather than of every assertion. Move one like any other gate:

```bash
python tooling/ratchet/ratchet.py lint_<rule> --count N --update --note '<what moved and why>'
```

Gates that read the *installed registry* rather than the tree cannot be graded at the narrow scope at all:

| Gate | Behaviour at narrow scope |
|---|---|
| `test_docstring` | One-sided ratchet: measures 1 there, 32 on a fuller install. Do not floor it at the former. |
| `TestSchemeDuplication` | Floors are per module; **skips** at that scope rather than passing. 24 of its 28 floors name a module the narrow scope does not install, and `web` reads 91 against a floor of 136 without being able to fail. Grade it on a fuller install. |

`odoo/addons/test_lint/machine_doc_v1/` is the map: two halves (`_rules.py` declares what a rule is, `_py_scan.py` runs the scan), which fixer answers to which document-identity invariant, and what each scope can and cannot measure.

### Other gates

`tooling/` — **check it before assuming a gate does not exist.** The ratchets, architecture, doc-link and typecheck gates all live there; the Rust checks are the crate workspace's own `cargo` commands.

### Changing the guidelines

Edit `doc/coding_guidelines.rst` directly. Its *Change protocol* binds what you do next:

- The same PR updates the `CLAUDE.md` files that summarise the rule — this one included — and adds a row to Appendix D.
- Rules are retired into Appendix C, never deleted silently.
- A rule whose rationale is architectural states that rationale in the rule itself, or in the gate's own module docstring.
