# `odoo/upgrade_code/` — dated source-rewrite scripts

Run by `odoo-bin upgrade_code`. Each script exposes `upgrade(file_manager)` and
rewrites source **in place**, in whatever checkout `--addons-path` points at.
They are not part of the running server; nothing imports them at runtime.

**Read `odoo/cli/upgrade_code.py`'s module docstring before running any of
them.** The short version: until 2026-08 not one of these had a test, and two of
the three audited since were found to corrupt the tree they ran on. They are text
substitutions standing in for code transformations.

Working procedure, in order:

1. `--dry-run` first and read the file list.
2. `--glob` to scope the run. Do not rewrite a whole checkout in one pass.
3. Read the diff. One limitation is inherent, not a defect: whether `x` in
   `x._context` is a recordset cannot be decided statically.
4. Work on a clean tree, so `git diff` is the review and `git checkout` the undo.

## Module map

`Tested` means a suite exercises the script's own rewrite logic, not merely that
the CLI can load it. `Pending` is what the script would still rewrite across
`agromarin` + `enterprise` + `design-themes` + `odoo/addons`, measured with
`--dry-run` (the `content` setter only marks a file dirty when its bytes
actually change, so these are real).

| module | tested | pending | notes |
|---|---|---:|---|
| `17.5-00-example.py` | — | 0 | Template; also the fixture `test_cli.py` runs `--dry-run` against. |
| `17.5-01-tree-to-list.py` | no | 0 | `<tree>` → `<list>`. 10 regex substitutions over `.xml`/`.js`/`.py`, plus an unconditional `" tree view "` → `" list view "` string replace. Spent here. |
| `18.1-00-sql-constraint.py` | **yes** | 0 | `_sql_constraints` → `models.Constraint`. Two tree-corrupting bugs fixed 2026-08; see its docstring. |
| `18.1-02-route-jsonrpc.py` | no | 0 | `type="json"` → `"jsonrpc"`. Requires a **trailing comma**, so `@route(..., type="json")` as the last kwarg is silently missed; also rewrites inside strings and comments. |
| `18.2-00-l10n-translate.py` | no | **548** | Largest pending migration. Edits `.po`/`.pot` through `polib`; measured, 2,449 translation entries genuinely change across an 8-module sample. No `wrapwidth` round-trips cleanly, so every touched file is reformatted whole and real changes land inside large diffs. |
| `18.3-00-l10n-fiscal-position-taxes.py` | no | **141** | 2,390 lines, unaudited. |
| `18.5-00-deprecated-properties.py` | **yes** | 1 | `._cr`/`._uid`/`._context` → `.env.*`. Was a bare regex that produced broken code; now `tokenize`-driven. The 1 remaining hit is a known false positive (`web/controllers/json_helpers.py`, a non-recordset). |
| `18.5-00-domain-dynamic-dates.py` | no | **28** | Carries an `if __name__ == "__main__"` self-test that CI never runs. |
| `18.5-00-no-tax-tag-invert.py` | no | **6** | Unaudited. |

## Deleting a spent script is normal

Upstream removes them once applied — `18.2-01-manifest-author.py` was deleted in
the very commit that applied it, and `17.5-00-tree-to-list.py` and
`18.1-01-rename-class.py` are likewise gone. The four scripts at 0 pending are
candidates.

The four with pending work are **not**: they are the only mechanical path to that
migration, and given the audit record above, the order matters — test the script,
run it, review the diff, *then* delete it.
