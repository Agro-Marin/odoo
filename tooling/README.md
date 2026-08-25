# tooling/

Standalone, dependency-light infrastructure for this checkout: the
architecture gates (`architecture/`), the shared count ratchet (`ratchet/`),
the HOOT test runner (`hoot/`), typecheck/codegen/doclink helpers, and this
bootstrap. Each gate documents itself in its module docstring; run any of them
with `--help`.

Two directories here deliberately gate nothing and say so in their own README:
`testbaseline/` (is this red mine, or was it already red?) and `patchorder/`
(is a double-patch allowlist entry still double-patched anywhere?). Both answer
a question CI cannot ask from the scope it runs in, which is the reason each
is a tool rather than a lane — not an omission to be closed by adding one.

Two scripts at this root gate nothing for a different reason: their answer
depends on **what is installed**, so a floor over one would measure the database
rather than the tree. Both run under `odoo shell` and both want the widest
registry available — the defect that occasioned `depends_audit` was invisible
with only `mail` installed and surfaced on 191 modules.

| Script | Asks |
|---|---|
| `depends_audit.py` | which `@api.depends` reads a field it did not declare, resolved through relations — root not watched at all, vs root watched and leaf not |
| `constrains_audit.py` | the same question one decorator over, for `@api.constrains`: a constraint that reads an undeclared field is not re-run when it changes, silently |

`depends_audit.py` is **not** a copy of `odoo/tools/depends_audit.py`, which is
wired into the framework's own tests. That one walks bytecode and reports the
attributes a compute reads; this one walks the AST and then resolves each read
through the registry. Measured on one 90-module registry: 322 findings here
against 30 there, sharing 18. Neither subsumes the other.

## One-time clone setup: install the git hooks

```sh
tooling/install-hooks.sh
```

`.pre-commit-config.yaml` only *declares* hooks — nothing is installed until
`pre-commit install` runs in your clone, once per hook stage. The script runs
all three (`pre-commit`, `commit-msg`, `pre-push`). Without it the pre-push
gate below silently never runs; an audit found every clone in the workspace in
exactly that state.

## How the cross-repo architecture gates deploy

`web` is consumed by sibling checkouts (`enterprise`, `agromarin`,
`design-themes`) that version and merge independently, so the boundary gates
run in three places, each covering what only it can see:

1. **This repo's CI** (`.github/workflows/architecture.yml`) checks out this
   repo alone. `js_public_surface.py` therefore pins its surface *per consumer
   scope* (each pinned specifier records which checkout imports it), and a
   repo-alone run validates only the `odoo` scope. Regenerating the pin
   (`--update`) requires the full workspace and refuses anything less.
2. **Sibling repos' CI** (e.g. `enterprise/.github/workflows/architecture.yml`)
   checks out this repo alongside and re-runs `js_face_boundary`,
   `js_public_surface`, and `named_export_coherence` with both trees present —
   that is where a sibling's new deep import into `@web` internals fails.
3. **The pre-push hook** (`cross_repo_coherence.py`, installed by the script
   above) stops a core push that removes a JS module a sibling still imports —
   the one failure CI can only report after the fact.

`xml_reference_coherence.py` extends the same per-scope pattern to the graph
imports cannot see: the strings view-arch XML resolves in the JS registries
(`widget=`, `js_class=`, `<widget name>`) and OWL template names
(`t-call`/`t-inherit` against `t-name`). Each consumer scope is judged only
when its provider closure (the addons-path dependency direction) is checked
out, so a repo-alone run judges `odoo` and the full workspace judges all
four; the pre-existing danglers are pinned in
`architecture/xml_reference_coherence.txt`, shrink-only per scope.
