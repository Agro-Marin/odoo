# Odoo framework core — architecture review, 2026-08-04

Scope: `addons/odoo/odoo` — the framework core (92,794 LOC across 328 files,
excluding tests) plus its bundled addon tree `odoo/addons/` (55,441 LOC / 185
files). Mandate: deep investigation, propose improvements, best-in-class
architecture as the goal.

Working brief from the reviewer: **question everything, even the gate.** That
turned out to be the productive frame — the codebase's own quality machinery is
good enough that the interesting defects are in what it *cannot see*, not in
what it reports.

---

## Summary

This is a well-architected codebase. The ORM's 4-layer decomposition is real and
holds: 156 files, **zero module-level import cycles**, eight boundary contracts
clean at zero, a mixin `self`-call graph that has been driven to a DAG. The
tooling (`layer_check`, `mixin_coupling_check`, ratchets, doc gates) is better
than most production codebases ever build.

So the findings below are mostly not "this is broken". They are: **the enforced
boundaries and the real coupling surfaces have drifted apart.** Every gate
reasons about *imports*; the framework's two widest dependencies — the `env`
seam and the `odoo.libs` surface — are not import-shaped, and are ungated.

| # | Finding | Severity |
|---|---|---|
| F0 | CI was red on `19.0-marin` — **resolved 2026-08-04, both `REM` commits reverted** | ~~blocking~~ |
| F4 | Layer→runtime `env` seam is ungated; Layer 1 is the heaviest user of runtime privates | **high** |
| F6 | `odoo.libs` internals unprotected; addons drifted 348 imports deep | **high** |
| F2 | `odoo/tests/` (7,145 LOC of shipped framework) invisible to every contract | medium |
| F5 | `odoo.tools` / `odoo.exceptions` — large public surfaces, no `__all__` | medium |
| F7 | Decomposition stopped at the framework boundary | medium |
| F1 | 25 in-code `ADR-NNNN` citations gated by nothing | medium |
| F3 | No Python import-cycle gate (JS has one) | low-med |

---

## F0 — CI was red on `19.0-marin` (RESOLVED)

> **Resolved 2026-08-04.** Both `REM` commits were reverted
> (`a93e170a1fe`, `f782ec2a6e9`), restoring `doc/adr/0001–0013`, `doc/adr/README.md`
> and the three audit documents — 3,558 lines. `pytest tooling/architecture/`
> is now **264 passed, 37 subtests passed, 0 failed**. Retained below as the
> record of what happened and why the gate mattered.

Commits `15b446af61e` and `cca359576a6` (both titled `REM`, 2026-08-04 21:45)
deleted `doc/adr/0001–0013*.md`, `doc/adr/README.md` and three architecture audit
documents — 4,291 lines.

`odoo/ARCHITECTURE.md` still cites those ADRs 14 times, and that **is** gated:

```
FAILED tooling/architecture/test_architecture_doc.py::TestReferencedArtifacts::test_adrs_exist
FAILED tooling/architecture/test_architecture_doc.py::TestReferencedArtifacts::test_adr_range_is_complete
2 failed, 262 passed, 37 subtests passed
```

The `Architecture Boundaries` workflow runs `pytest tooling/architecture/`
*before* the seven checkers, so the whole job fails. Credit where due: the gate
worked exactly as designed and caught the deletion within minutes.

Two secondary observations:

- `test_adr_range_is_complete` fails with `IndexError: list index out of range`
  (`on_disk[0]` on an empty glob) rather than a clean assertion. A test that
  crashes instead of asserting gives a worse diagnostic than the one next to it,
  which says plainly *"ARCHITECTURE.md references ADR-0001, which does not
  exist"*. Worth a one-line guard.
- The half-state was the only bad option: either the ADRs exist, or the
  apparatus comes out of `odoo/ARCHITECTURE.md`, `layer_check.py` (12 citations),
  `coding_guidelines.rst` (3), `environment.py` (2) and five other files.
  Resolved by restoring.

## F1 — 25 in-code `ADR-NNNN` citations are gated by nothing

`test_adrs_exist` (F0) covers `odoo/ARCHITECTURE.md` only. The other **25**
`ADR-NNNN` citations — `layer_check.py` (12), `test_layer_check.py` (4),
`coding_guidelines.rst` (3), `orm/runtime/environment.py` (2),
`tools/assets/__init__.py`, `orm/components/core.py`, and two test files — are
checked by nothing.

`doc_link_gate.py` does not help, and the reason is structural rather than a
baseline escape: it extracts only **`.md` paths** (markdown links and backticked
paths). `odoo/ARCHITECTURE.md` cites the *directory* `` `doc/adr/` `` — no `.md`
suffix — and in-code citations use the bare `ADR-0002` form, which is not a path
at all. The gate enforces a convention it invented (backtick your `.md` paths)
rather than the citation convention the codebase actually uses.

**Implemented (2026-08-05):** `doc_link_gate.py` now recognises the
`ADR-NNNN` citation form and resolves it against `doc/adr/` by number (globbed,
so the filename slug can change without a tree-wide edit). **96 citations across
2,125 files** are now checked, up from the 14 in one file that
`test_adrs_exist` covered. 11 self-tests added.

Scanned **separately** from the `.md` references, with its own wider glob set,
and that separation is the design decision: simply adding `.py`/`.rst` to
`DEFAULT_SCAN_GLOBS` would also subject those files to the `.md` patterns, which
surfaces **28 unrelated broken references** — real rot (stale paths like
`addons/core/addons/web/...` from an earlier layout, and `.claude/rules/*.md`
outside the repo), but a different job, and one that would either turn a
zero-tolerance gate red or need a 28-entry baseline it has never had. Those 28
are recorded here as a follow-up rather than absorbed.

Proven to fail rather than assumed: removing `doc/adr/0002-*.md` reports 12
dangling citations and exits 1; removing `0006` likewise, and the self-tests go
red with it. Restoring returns the gate to clean.

One trap found while writing it: the gate's own prose cited a real ADR number to
illustrate the form, which its new grammar read as a live citation — the same
"cannot tell a citation from an assertion" problem `package_index_check`
documents for backticked paths. The prose now spells the form with letters, and
a test (`test_this_gate_plants_no_live_citation_of_its_own`) keeps it that way.

## F4 — The ORM layer model gates imports; the real Layer→runtime dependency is ungated

**This is the headline finding.**

`orm-layer1-below-models-and-runtime` and `orm-models-below-runtime` forbid
Layers 1 and 2 from *importing* `orm/runtime`. They are clean, and they always
will be — because that is not how those layers reach the runtime. They reach it
through `self.env`, on every call, and `env.registry` or
`env._field_cache_memo` produces no import edge at all.

`mixin_coupling_check.py` exists precisely because `self`-collaboration is
invisible to the import graph. The identical argument applies one level up, at
the seam between the layers and Layer 3, and nobody had made it. Measured:

| Consumer | public `env` members | unsanctioned private | accesses |
|---|---|---|---|
| `orm/fields` (Layer 1) | 19 | **5** | 10 |
| `orm/models` (Layer 2) | 21 | 2 | 3 |
| `orm/domain` (Layer 1) | 3 | 0 | 0 |
| `orm/components` | **0** | **0** | 0 |

**Layer 1 — the layer declared *furthest below* the runtime — is the heaviest
consumer of the runtime's private internals, wider than Layer 2.** The layering
story is true of the import graph and false of the runtime graph.

`orm/components` measuring 0 is the good news: its purity claim survives this
stricter test too, which is the runtime half of what
`orm-components-are-pure-python` asserts about imports.

The sharpest case is `Environment._field_cache_memo`, a `functools.cached_property`
whose own docstring reads **"Do not use it."** Layer 1 uses it six times — four
of them as `env.__dict__["_field_cache_memo"]`, reaching into the instance dict
to skip the descriptor on a hot path:

- `orm/fields/base.py:1362`, `:1821`
- `orm/fields/textual.py:82`
- `orm/fields/relational/many2one.py:85`

**Verified not a bug:** all four are `try/except KeyError`-guarded with a
`self._get_cache(env)` fallback, so an unmaterialised `cached_property` is
handled correctly. It is a deliberate, sound optimisation.

It is still real debt, and the risk is specific and demonstrable. I renamed
`Environment._field_cache_memo` on the live tree and measured what catches it:

| Tool | Result |
|---|---|
| `ruff` | 31 errors before **and after** — blind |
| `mypy` (`-p odoo.orm`) | 931 → **933**: catches only the 2 plain-attribute sites, as an anonymous +2 in a count-ratcheted pool |
| the 4 `__dict__["…"]` sites | **caught by nothing** |

Those four would silently keep raising `KeyError`, the fallback would swallow it,
and the fast path would quietly become a permanent slow path. **No test fails.**

### Delivered: `tooling/architecture/env_surface_check.py`

Written, passing, and wired to the same conventions as its siblings
(`--check` / `--json`, `KNOWN_VIOLATIONS` with reasons, drift-zero).

- Collects `<x>.env.<attr>` and bare `env.<attr>` across Layers 0/1/2 and
  `components/`, resolving `env.__dict__["key"]` to the member it actually names.
- Fails on any unsanctioned private reach. Two private names are sanctioned by
  design: `env._` (gettext; private spelling, public intent) and `env._core`
  (the curated `OrmCore` cache/compute facade).
- Fails when a referenced member **does not exist on `Environment`** — the hole
  above. Members are resolved from the class body *plus* `Mapping`, since
  `env.get` is inherited and would otherwise false-positive.
- `components/` carries an empty allow-list: it may reach `env` for nothing.
- The 13 current reaches are pinned with individual rationales, so the debt stays
  visible and cannot spread.

Verified end-to-end: with the rename applied the gate exits 1 and names all six
sites; restored, it is green. `test_env_surface_check.py` adds **17 tests**
covering the ways the gate itself could lie — silence on a real reach, silence on
a rename, double-counting `__dict__`, stale pins, and miscounting `Environment`'s
members. One cross-checks the AST parse against the imported `Environment` class.

**Next step (not done — it is a design decision, not a cleanup):** promote
`_field_depends_context`, `_ir_defaults`, `_context_defaults` and `_lang` to
public `Environment` accessors and drop them from `KNOWN_VIOLATIONS`. That
converts the pins into an explicit, documented Layer-3 interface — at which
point the allow-list *is* the Protocol the layer model has been missing.

## F6 — `odoo.libs` has no façade for 87% of itself, so its file layout is de-facto public API

**Corrected 2026-08-04** after reading the restored ADR-0004. My first pass said
addons were "bypassing" a curated 32-name surface. That was wrong, and the real
situation is worse in a more interesting way: for most of `odoo.libs` **there is
nothing to bypass.**

`odoo/libs/` is the dependency-free utility layer (ADR-0004): 16,937 LOC, 138
files, 17 subpackages + 14 top-level modules. Its one contract,
`libs-is-dependency-free`, is clean at zero and genuinely enforced — that part is
a real achievement and is not in question here.

The problem is the *outward* surface. `odoo/libs/__init__.py` re-exports from
only **4 of its 31 members** — `collections`, `iteration`, `text`, `utils` — for
32 names total. The other 27, including `numbers`, `datetime`, `json`,
`intervals`, `web`, `xml`, `filesystem`, `locale`, `image`, `profiling`,
`email`, `barcode`, `lru`, `password`, `parse_version`, `set_expression`, are
**not reachable from `odoo.libs` at all**. `odoo.libs.float_round` does not
exist.

So deep imports are not drift — they are the only available route. And
ADR-0004's mitigation is stale: it cites `tools/intervals.py` as a
`DeprecationWarning` shim keeping the old path alive, but that file was deleted
in `cd56bdbb086`, which pushed callers onto the deep path rather than off it.

Measured across the whole workspace (per tree, no double-counting):

| Tree | files | references | distinct modules |
|---|---|---|---|
| `odoo/addons` (bundled) | 55 | 88 | 26 |
| `enterprise` | 105 | 120 | 12 |
| `agromarin` | 6 | 6 | 3 |
| `design-themes` | 0 | 0 | 0 |
| **total** | **166** | **214** | **31** |

(12 of the 214 are stale *comments* in `__manifest__.py` files citing
`odoo.libs.esm_registry`, which ADR-0004 relocated to `odoo/tools/assets/`.
Harmless at runtime, but another instance of F1's blind spot: a module path in a
comment, which `doc_link_gate` cannot see because it is not a `.md` path.)

**The consequence:** the internal file layout of `libs/` is public API by
accident. Renaming `libs/web/urls.py` breaks 51 call sites across three repos;
`libs/numbers/float_utils.py`, 24.

### What makes this cheap to fix

**Every subpackage already has a curated `__init__.py` with `__all__`** —
`numbers` (9 names), `datetime` (25), `json` (9), `text`, `xml`, `filesystem`,
`locale`, `web`. `from odoo.libs.numbers import float_round` **works today**.

Addons are simply reaching one level too deep, past a boundary that already
exists. Exactly **115 references** land on a leaf module rather than its
subpackage:

| leaf module | refs | | leaf module | refs |
|---|---|---|---|---|
| `web.urls` | 51 | | `json.fast_clone` | 5 |
| `numbers.float_utils` | 24 | | `text.html` | 4 |
| `filesystem.mimetypes` | 9 | | `profiling.sourcemap_generator` | 3 |
| `datetime.tz` | 6 | | `_vendor.sessions` | 3 |
| `xml.dsig` | 5 | | `profiling.speedscope`, `lint.scan`, `locale.number_format` | 5 |

(The three `_vendor.sessions` reaches are all in `test_http`, the framework's own
test addon, not business code. Core's own `_vendor` use — `http/session.py`,
`http/wrappers.py`, `tools/sass_embedded.py` — is legitimate and in scope.)

### Implemented 2026-08-04: the subpackage is now the boundary

Option (B) was taken and is done. `odoo.libs.numbers` is public;
`odoo.libs.numbers.float_utils` is not.

**Migration — 124 leaf reaches down to 2.**

- **85 sites** rewritten mechanically onto areas that already exported every
  symbol (`numbers`, `text`, `datetime`, `json`, `profiling`, `locale`).
- **35 sites** rewritten after widening four area façades, following the
  symbol-re-export convention `xml`/`numbers`/`json` already used:
  - `libs/web/__init__.py` — added `urljoin`, `ImportMap`, `import_map_for`
    (`urls.__all__` is exactly `["urljoin"]`, so the area now states it);
  - `libs/filesystem/__init__.py` — added every name `mimetypes` declares
    public, and *only* those;
  - `libs/xml/__init__.py` — added the five `dsig` entry points, which the area
    had never re-exported;
  - `libs/lint/__init__.py` — was a bare docstring with no exports; now exports
    `scan_byte_patterns` / `scan_regex_patterns`.
- **2 sites** merged or corrected by hand (`base/tests/test_tz.py` keeps the `tz`
  module object, which it needs for `tz._timezone_cache`).
- **2 sites** deliberately left and pinned (below).

Note `web` and `filesystem` re-exported *submodules* while `xml`/`numbers`/`json`
re-exported *symbols* — an inconsistency inside `libs/` itself. The widening
above settles it on the symbol convention, keeping the submodule exports for
callers that need the module object.

**Not promoted, deliberately:** `_odoo_guess_mimetype` — the pure-Python
fallback that `test_mimetypes` exists to test *against* python-magic, so that
suite must name the implementation. It stays module-private, and the one site
that needs it is pinned rather than the symbol being made public to suit a test.

**Delivered: `tooling/architecture/libs_facade_check.py`** (+ 18 self-tests).

It is a separate tool rather than a `layer_check` contract, and the reason is
structural: `_ImportCollector` emits a synthetic `<base>.<name>` for every
`from <base> import <name>`, so `from odoo.libs.numbers import float_round`
yields `odoo.libs.numbers.float_round` — indistinguishable *by name* from the
module `odoo.libs.numbers.float_utils`. `Contract.allow` is prefix-matched, so
allowing the area would allow every leaf beneath it. The discriminator is on
disk (**does a module of that path exist?**), which the Contract model has no
way to ask. `TestSymbolVersusModule` pins exactly this.

Areas are read from the tree, not hard-coded, so a new `libs/<area>/` needs no
edit and a deleted one cannot linger as a permanently-satisfied allowance.
Scope is both addon trees in this checkout (8,592 files); sibling checkouts are
separate repositories. Two pins remain, each with a stated reason:
`test_http/utils.py` → `_vendor.sessions` (vendored third-party; a curated
façade would imply a stability promise the vendor makes, not us) and
`test_mimetypes` → `filesystem.mimetypes` (above).

The gate caught two real mistakes of mine while being built: two
`KNOWN_VIOLATIONS` paths I had guessed rather than measured, and — via the
resolution check — one rewrite that moved `_odoo_guess_mimetype` onto a façade
that deliberately does not export it.

**Verification:** 117 files changed. All byte-compile; every rewritten symbol
resolves against the real imported module (0 unresolved). Tier 1 **2,456 passed**
/ 718 subtests, Tier 2 **1,421 passed**, `pytest tooling/architecture/`
**282 passed**. ruff back at its 539 floor (one `I001` I introduced, fixed —
diffed before/after rather than assumed); `ruff format` unchanged.

### The decision, for the record



**(A) Declare `odoo.libs.*` public.** Honest and free, but freezes the file
layout: every leaf module becomes a compatibility surface, and the refactoring
freedom ADR-0004 was written to obtain is gone.

**(B) Make the *subpackage* the public boundary — chosen and implemented.**

- the boundary already exists and is already curated — no new façade to design;
- migration is a mechanical one-line import rewrite at 115 sites;
- it preserves freedom to reorganise inside each area, which is the whole point;
- it is enforceable with the existing machinery — a `libs-facade-boundary`
  contract in `layer_check.py` with `source=("odoo.addons", "addons")`,
  `forbidden=("odoo.libs",)`, and `allow` listing the 31 subpackage/module paths.
  Pin the 115 leaf reaches in `KNOWN_VIOLATIONS`, fix them, delete the pins.

Under (B) the four top-level members with no subpackage to hide behind
(`intervals`, `constants`, `lru`, `barcode`, …) stay public as-is; they are
single modules, so the leaf *is* the area.

Separately, and regardless of A or B: `odoo/libs/__init__.py` re-exporting only
4 of 31 members is itself the anomaly. Either it should cover the package or it
should export nothing and let callers name the area they want. The current
half-measure is what makes `odoo.libs` look like it has a façade when it does not.

## F2 — `odoo/tests/` (7,145 LOC of shipped framework) is invisible to every contract

`layer_check._is_test_file()` drops any path with a `tests` component. Correct
for `orm/tests/`; wrong for **`odoo/tests/`**, which is not tests — it is the
shipped test *framework* (`TransactionCase`, `HttpCase`, `ChromeBrowser`), 17
files, imported by every addon suite in the workspace.

Measured: `odoo/tests/*` in the scanned set = **0 of 6,427 files**. Forcing the
contracts over it anyway yields 8 `core-does-not-depend-on-addons` edges, at
`tests/common.py:1104` and `tests/http.py:461-462` → `odoo.addons.bus`.

Both reaches are correctly guarded (`try/ImportError`, and
`if "bus.bus" in self.env.registry:`), so this is not a live defect. Two real
problems remain:

1. **The exemption is double-applied and therefore irrevocable.**
   `CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT == {"tests"}` (pinned by
   `test_architecture_doc.py:595`) reads like a scoped, reversible decision. It
   is not: `_is_test_file()` already removed those files upstream, and
   `odoo.tests` is absent from the contract's `source` list as well. Removing
   `tests` from the frozenset would enforce **nothing** — anyone "turning the
   contract on" gets a false green.
2. **`odoo/ARCHITECTURE.md` undercounts it** — "its *one* addon reach
   (`tests/http.py` → `odoo.addons.bus`)". There are two sites in two files.

**Proposal:** narrow `_is_test_file()` to *test* files rather than any path
containing `tests` (exempt `odoo/tests/` explicitly, by name, in one place), add
`odoo.tests` to the contract `source`, and let the single documented exemption do
the work it claims to do.

## F5 — `odoo.tools` and `odoo.exceptions`: large public surfaces with no `__all__`

| Surface | `__all__` | names |
|---|---|---|
| `odoo.api` | yes | 21 |
| `odoo.fields` | yes | 31 |
| `odoo.models` | yes | 28 |
| `odoo.libs` | yes | 32 |
| `odoo.http` | yes | 67 |
| **`odoo.tools`** | **no** | 104 re-exported |
| **`odoo.exceptions`** | **no** | — |

`odoo/ARCHITECTURE.md` says the façades "each declare an explicit `__all__`" — true of
`api`/`fields`/`models`. But `odoo.tools` is the framework's *largest* public
utility surface (104 symbols: 15 from 5 `odoo.libs` modules, 89 from elsewhere)
and declares no boundary at all, and `odoo.exceptions` (`UserError`,
`ValidationError` — imported by essentially every addon) likewise. Low effort,
and it is a precondition for F6: you cannot tell addons which path is canonical
until the canonical surface is declared.

## F7 — The decomposition stopped at the framework boundary

The fork's stated posture is that the monoliths were decomposed. They were — but
its own largest consumer was not:

| Tree | files | LOC | LOC in files >800 lines |
|---|---|---|---|
| core (`odoo/` minus addons) | 328 | 92,794 | 23,889 — **25%** |
| `odoo/addons/` | 185 | 55,441 | 33,254 — **59%** |

`ir_qweb.py` 3,477 · `ir_ui_view.py` 3,407 · `ir_attachment.py` 2,879 ·
`ir_actions_report.py` 2,676 · `ir_qweb_assets.py` 2,185. `addons/base` is what
every other addon inherits from, so its shape propagates workspace-wide.

Largest god-classes remaining in core: `configmanager` (`tools/config.py`)
**1,746 LOC / 46 methods** — larger than `Field` (1,621/61) — then `Properties`
(904/26), `Registry` (832/29), `ConnectionPool` (785/28), `Environment` (658/49).

`configmanager` is the best candidate: it is a god-object over a flat key-value
store, it is imported nearly everywhere, and unlike `ir_qweb` it has no
behavioural coupling to the view stack.

## F3 — No Python import-cycle gate

`js_cycle_check.py` gates ESM cycles across every addon's client source. There is
no Python equivalent. Measured directly (module-level runtime imports only;
`TYPE_CHECKING` and function-local imports excluded): 319 core modules, 1,035
edges, **3 cycles over 8 modules**:

- `odoo.service` ⇄ `server` ⇄ `_prefork` / `_threaded` (4 modules)
- `odoo.modules` ⇄ `odoo.modules.db` (2)
- `odoo.cli` ⇄ `odoo.cli.command` (2)

All three are the benign package↔submodule re-export pattern (`from . import x`
against a partially-initialised package). **The ORM — 156 files, the most layered
subsystem — has zero.** The gap was regression protection, not present damage.

**Implemented (2026-08-05):** `tooling/architecture/py_cycle_check.py` (+ 19
self-tests), wired into CI as the tenth blocking gate. Same drift-zero contract
and escape hatch as `js_cycle_check`: the three are pinned in `KNOWN_CYCLES` with
a stated reason, so a fourth has to be argued for. Two design points worth
recording:

- **Function-local imports are deliberately not edges.** A deferred import is the
  sanctioned way to break a cycle in Python; counting one would flag every seam
  that already fixes the problem, and report the framework as tangled exactly
  where it has been untangled.
- **A stale pin fails the gate too.** A pinned cycle that has since been broken
  would otherwise keep the gate green while claiming debt that no longer exists.

Proven to fail rather than assumed: injecting a synthetic
`odoo.exceptions ⇄ odoo.release` edge into the real graph is reported as a new
cycle and drops `report.ok` to `False`.

---

## Recommended order

1. ~~**F0** — unbreak CI.~~ Done: reverted.
2. **F5** — declare `__all__` on `odoo.tools` and `odoo.exceptions`. Cheap,
   unblocks F6.
3. **F6** — `libs-facade-boundary` contract, pinned; then delete the 80
   redundant deep imports. Highest structural payoff.
4. **F4 follow-through** — promote the four pinned private accessors to public
   `Environment` members; the gate is already in place to prove it landed.
5. **F2** — narrow `_is_test_file()` so the documented exemption is real.
6. **F1 / F3** — ADR citation resolution in `doc_link_gate`; Python cycle gate.
7. **F7** — split `configmanager` first; treat `addons/base` as a separate
   programme.

## What was delivered in this pass

**F0 — CI unbroken.** Reverted both `REM` commits (`a93e170a1fe`, `f782ec2a6e9`),
restoring `doc/adr/0001–0013`, `doc/adr/README.md` and the three audit documents.

**F4 — the `env` seam is now gated.**
`tooling/architecture/env_surface_check.py` + `test_env_surface_check.py`
(17 tests). 13 current private reaches pinned with individual rationales.

**F6 — the `odoo.libs` façade is now real and gated.**
`tooling/architecture/libs_facade_check.py` + `test_libs_facade_check.py`
(18 tests). 124 leaf-module imports reduced to 2, both pinned with reasons; four
area façades widened (`web`, `filesystem`, `xml`, `lint`).

**Both gates wired into CI.** `.github/workflows/architecture.yml` gained a step
each, entries in the job summary, and both step ids added to the failure
annotation condition. The existing path filters already covered their inputs
(`odoo/orm/**`, `odoo/libs/**`, both addon trees, `tooling/architecture/**`), so
no filter change was needed. `odoo/ARCHITECTURE.md`'s gate table updated from
seven checkers to nine, with the rationale for each new one.

Worth recording: `test_ci_gate_table_matches_the_workflow` **failed the moment
the workflow gained two steps the doc did not list**, and that is how the doc
came to be updated. The repo's own machinery caught the omission — the intended
behaviour, observed working.

### Verification

| Check | Result |
|---|---|
| files changed | 117 (91 under `addons/`, 25 under `odoo/`, 1 workflow) |
| byte-compile | all pass |
| every rewritten symbol resolves against the real module | 0 unresolved |
| Tier 1 (`pytest`) | **2,456 passed**, 718 subtests |
| Tier 2 (`orm/tests` + `http/tests` + `tests/service`) | **1,421 passed** |
| `pytest tooling/architecture/` | **282 passed**, 79 subtests |
| all 9 CI gates (`--check`) | exit 0 |
| `cross_repo_coherence.py` | coherent |
| `doc_link_gate.py` | 0 new |
| ruff | **539** = floor (one `I001` I introduced, found by before/after diff and fixed) |
| `ruff format` | unchanged (56 pre-existing, none new) |
| workflow YAML | parses; 14 steps |

Two mistakes of mine were caught by the new gate rather than by review: two
`KNOWN_VIOLATIONS` paths I had guessed instead of measured, and a rewrite that
moved `_odoo_guess_mimetype` onto a façade that deliberately does not export it.

### Not done

- **F1, F2, F3, F5, F7** remain as written above.
- The **F4 follow-through** — promoting `_field_depends_context`, `_ir_defaults`,
  `_context_defaults` and `_lang` to public `Environment` accessors — is a design
  change, not a cleanup, and is left for a decision. The gate is in place to
  prove it when it lands.
- Sibling checkouts (`enterprise`, `agromarin`) carry their own `odoo.libs` leaf
  imports — 126 references — and are outside this repo's gate scope. They need
  the same migration under their own branches.

---

## Appendix — pre-existing test failures addressed (2026-08-05)

The `-i base --test-enable` run reported **13 failed of 4,208**. Provenance was
settled by re-running the same 13 classes against a stashed (clean) tree: the
failure sets were **identical, 13 and 13**, so none came from the `odoo.libs`
migration. They were then fixed rather than annotated.

**Result: all 13 addressed, zero new regressions** (218-test re-runs of the
same classes; 8 fixed in the first pass, 3 in the second, 1 in the third, 1 in
the fourth).

| Failure | Root cause | Fix |
|---|---|---|
| `TestTOTP` ×3, `TestAPIKeys.test_apikeys_totp` | `9251982dca8` (retire Bootstrap JS) replaced `<a data-bs-toggle="collapse">` with native `<details>/<summary>`; `totp_flow.js` still triggered on `.modal a:contains("Cannot scan it?")`, so all four tours died on a 10 s timeout | Trigger on `details > summary`, scope the secret lookup to `closest("details")` |
| *(latent — never ran)* | `auth_totp_portal` renders `auth_totp.view_totp_wizard`'s combined arch and carried the **identical** stale selector; invisible because the module is not installed in a base-only run | Same fix applied |
| `WebSuite.test_suite_filters_cover_every_test_file` | `@web/views/settings` matched no CI suite filter — 4 tests that never ran | Registered in the `@web/views/*` catch-all; `hoot-shard` derives its plan from the runner so it stayed in sync automatically. The 4 tests pass |
| `TestWebBundleSize.…frontend_minimal` | 7,983 B vs a 7,800 B budget | **Measured, not guessed**: reverting `cookie.js` to pre-`879bc223104` gives 7,807 B, so 176 of the 183 B are that commit's cookie-**name** escaping (before it, `set("a=b","c")` wrote cookie `a` = `b=c`, and a `;` in a name clobbered another cookie). Budget raised to 8,200 with the measurement recorded in-code; golfing a security-critical escape routine for 176 B would be the wrong trade |
| `AddonSuite.test_web_cohort` | Assertions used `toHaveText`, which reads `innerText` and therefore sees this fork's `text-transform: uppercase` on list headers → `Expected "Start" / Received "START"` | Assert `data-name` instead — presentation-independent, and the idiom the same file already used for its form-view checks |
| `AddonSuite.test_web_gantt` (first cause) | `addons_bundling_unit_tests()` generated a per-file suite for `gantt_view_manual.test.js`, a hand-run benchmark tagged `"manual testing"` whose three tests are all `test.skip` — its `&id=` hash matched nothing and the hardened runner refused to fall back | `has_runnable_tests()` filter in the generator (general, not a special case): 3 such files exist across 1,802 |
| `AddonSuite.test_web_unsplash` | **Production bug.** `rpc()` moved to `fetch()` (`34d4d0640a6`) and later hard-rejected unknown settings (`8e7a2fc2e8e`), so the legacy `{ xhr }` progress handle made **every Unsplash upload throw before sending** | Removed the dead plumbing — it measured a small JSON body, not the server-side image download |
| *(found by the same sweep)* | **POS carried the identical bug**: `hardware_proxy_service.js` keep-alive polled with `{ silent: true, xhr }`, so every tick threw and the proxy read as permanently disconnected | `xhr.timeout = 2500` maps exactly onto rpc's first-class `timeout` (same ms unit) |

### Second pass (2026-08-05) — 5 remaining, 3 more fixed

| Failure | Root cause | Fix |
|---|---|---|
| `WebSuite.test_hoot` | `b567f9a12b3` fixed hoot-dom so `keyup` targets where focus actually **landed** (its message: the old behaviour is what "no browser does"; port of upstream `d0842c1bc86`). The three self-tests that `press("Tab")` then `verifySteps` were never updated, so they still omit the resulting `keyup:Tab` | Added the two `keyup:Tab` steps to all three. The implementation was right; the expectations predated it |
| `MobileWebSuite.test_fields` | `many2many_tags/create-domain follows the record the pager lands on` was **untagged**, so it also ran on mobile — where the widget opens a kanban select-create dialog, not `.o-autocomplete--dropdown-item`. Its two positive assertions failed and its negative one passed **vacuously** | Tagged `desktop`, matching the only two other tests in the file that read that selector. The logic under test is platform-independent and stays covered on desktop |
| `AddonSuite.test_web_gantt` (second cause) | The renderer's `onDragStart` has always called `popover.close()`. The assertion "popover should is still opened as the pill did not move yet" passed only because the overlay's DOM node outlived `close()` by a frame; teardown is deterministic now, so it was asserting the lag, not the behaviour | Assert what the renderer actually does — starting a drag closes the popover, and it stays closed while the pill moves |

### Third pass — `TestUserSwitch` fixed

`0dd99203e84` (an accessibility fix) split the chooser row from a single
`<button class="list-group-item">` carrying `fillForm` into a plain `<div>`
holding two real controls, because the old markup nested the remove `<i>` inside
the row's `<button>` — invalid, and unreachable without a mouse. `fillForm` moved
onto `.o_user_switch_login` with it.

The tour still clicked the **row**. A click dispatched on a container does not
reach a child's handler, so the step **passed while doing nothing** and the
failure surfaced three steps later as "`.oe_login_form .o_user_switch_btn` has
not been found" — a message pointing at the button, not at the click that never
happened.

Diagnosed by probing the component's own unit environment rather than the tour:
after picking a user, `btn=1 inForm=1` — the toggle *does* come back, so the
component was never at fault. Fixed the three `run: "click"` steps to target
`.o_user_switch_login` / `.o_user_switch_remove`; the remaining `.list-group-item`
selectors are presence assertions, where the row is the right thing to name.

Two coverage gaps closed in `user_switch.test.js`, both of which would have
caught this at unit level: the existing "picking a user…" test never asserted the
toggle returns, and nothing pinned that the row is an inert container whose
controls do the work.

### Fourth pass — `AddonSuite.test_web_tour` fixed

The last one, and it was a real defect rather than a stale test: **every tour
step decided its guards against a stale DOM.**

`Macro.advance` chains straight from a step's action into the next step's
`waitForTrigger`, and `waitUntil` evaluates its predicate **synchronously on the
first call**. So a step inspected the page in the same task as the action that
had just changed it, before OWL had rendered anything. `tour_check_modal` is what
exposed it: the step clicked a button behind a dialog because `elementIsInModal`
ran before the dialog it was supposed to notice existed.

Fixed by awaiting one animation frame after each action, in the tour's own macro
step. Two details that decided the shape of it:

- **Where.** The obvious seam is `Macro.advance()`, but `Macro` is also used by
  `barcodes/barcode_handlers.js`, so a change there reaches past tours. The
  action is built in `tour_automatic.js` and is tour-owned, so settling there
  touches nothing else.
- **How much.** One frame, not the 62 ms mutation settle `waitForMutations`
  already provides for `checkForUndeterminisms`. OWL schedules its render with
  `requestAnimationFrame` during the action, so a frame requested *after* it is
  guaranteed to run once that render has landed — and a per-step mutation settle
  would cost every tour in the workspace far more.

Skipped when the step declared `expectUnloadPage`: the page is navigating away
and there is no next step to protect.

This is the same failure mode as `TestUserSwitch`, from the other side — a tour
step that succeeds without achieving anything. There a click missed its handler;
here a guard ran before the thing it guards against existed.

Verified: `@web_tour` 57 passed (run twice — the first full-suite run reported a
`tour_interactive` failure that turned out to be a stale warm-server bundle from
stashing the change, not a regression), `@web/core/macro` 19 passed, and
`AddonSuite.test_web_tour` + `TestUserSwitch` + `TestTOTP` + `TestAPIKeys` = 13
tests, 0 failed, every tour SUCCEEDED.

Earlier diagnosis, unchanged:

- **`web_tour`** — `tour_check_modal` expects the "below a modal" guard to block
  a click; it succeeds. Ruled out: the Dialog still renders `class="modal d-block"`,
  and `:visible` / `:last` are both registered hoot pseudo-classes
  (`hoot-dom/helpers/dom.js:1101`, `:1092`). The guard's selector is sound, so the
  remaining hypothesis is dialog-mount timing relative to the tour macro.
- **`TestUserSwitch`** — fails at step 9/35: after choosing a user, the
  `.oe_login_form .o_user_switch_btn` back-button is not found. The button is
  rendered through `t-portal="'label.form-label'"`, introduced by the same
  2025-09 `[REF] AgroMarin guidelines` commit as the uppercase headers, so its
  DOM position depends on a portal target inside the form. Needs interactive
  browser debugging.
