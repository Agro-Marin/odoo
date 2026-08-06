# tooling/

Standalone, dependency-light infrastructure for this checkout: the
architecture gates (`architecture/`), the shared count ratchet (`ratchet/`),
the HOOT test runner (`hoot/`), typecheck/codegen/doclink helpers, and this
bootstrap. Each gate documents itself in its module docstring; run any of them
with `--help`.

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
