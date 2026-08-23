# `odoo/upgrade_code/` — dated source-rewrite scripts

Run by `odoo-bin upgrade_code`. Each script exposes `upgrade(file_manager)` and
rewrites source **in place**, in whatever checkout `--addons-path` points at.
They are not part of the running server; nothing imports them at runtime.

**Read `odoo/cli/upgrade_code.py`'s module docstring before running any of
them.** The short version: until 2026-08 not one of these had a test; of the five
audited since, four were found to corrupt the tree they ran on. They are text
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
| `17.5-00-example.py` | **yes** | 0 | Template, and the fixture `test_cli.py` runs `--dry-run` against. It never assigns `file.content`, which reads like the bug every copier would inherit and is **not** one: two tests pin it inert, and its substitutions swap quote styles, so a version range that swept it up would mangle every `models/*.py` for nothing. Adding the write-back was tried on 2026-08-23 and reverted the same hour; the reason is now at the line itself. |
| `17.5-01-tree-to-list.py` | **yes** | 0 | `<tree>` → `<list>`. 10 regex substitutions over `.xml`/`.js`/`.py`, plus an unconditional `" tree view "` → `" list view "` string replace. Spent here. |
| `18.1-00-sql-constraint.py` | **yes** | 0 | `_sql_constraints` → `models.Constraint`. Two tree-corrupting bugs fixed 2026-08; see its docstring. |
| `18.1-02-route-jsonrpc.py` | **yes** | 0 | `type="json"` → `"jsonrpc"`. Requires a **trailing comma**, so `@route(..., type="json")` as the last kwarg is silently missed; also rewrites inside strings and comments. |
| `18.2-00-l10n-translate.py` | **yes** | **548** | Largest pending migration. Edits `.po`/`.pot` through `polib`; measured, 2,449 translation entries genuinely change across an 8-module sample. No `wrapwidth` round-trips cleanly, so every touched file is reformatted whole and real changes land inside large diffs. Read the `.po` and the `.xml` **back from disk** until 2026-08-23 — see *Read `file.content`* below. |
| `18.3-00-l10n-fiscal-position-taxes.py` | **yes** | **141** | 2,390 lines. Two second-run defects found by the idempotence property and fixed 2026-08-23: it appended `fiscal_position_ids`/`original_tax_ids` unconditionally, so a re-run emitted a **duplicated CSV header** (`csv.DictReader` keeps the last of each and drops every earlier value), and a re-run then **erased what the first run derived**, because the fiscal-position CSV it reads from has by then lost the columns the derivation needs. |
| `18.5-00-deprecated-properties.py` | **yes** | 1 | `._cr`/`._uid`/`._context` → `.env.*`. Was a bare regex that produced broken code; now `tokenize`-driven. The 1 remaining hit is a known false positive (`web/controllers/json_helpers.py`, a non-recordset). |
| `18.5-00-domain-dynamic-dates.py` | **yes** | **28** | Its `if __name__ == "__main__"` self-test is now `test_upgrade_code_domain_dynamic_dates.py` and the dead block is gone. |
| `18.5-00-no-tax-tag-invert.py` | **yes** | **6** | Carried a `test_tag_signs` nothing called, asserting signs for real `l10n_be`/`l10n_it` data. Deleted; `remove_sign`'s rule — which is what it was sampling — is pinned directly in `test_upgrade_code_no_tax_tag_invert.py`. Read its `.xml` back from disk until 2026-08-23. |

## The floor every script is held to

`odoo/tools/tests/test_upgrade_code_scripts.py` asserts, for each script found in
this directory, that it is discoverable by name, exposes `upgrade(file_manager)`,
survives an empty selection, leaves Python and XML that still parse, is
idempotent, and **actually rewrites something in the shared corpus** — except
`17.5-00-example.py`, whose inertness the same test asserts in the other
direction. That last property is not ceremony: the first corpus reached three of
the nine scripts, and the other six were passing on air.

Idempotence is the one that earns its keep. Nothing stops a second run — the CLI
keeps no record of what it has applied — and both of the `18.3` defects above are
second-run defects that no single-run test could see.

## Read `file.content`, never the path

`migrate()` builds ONE `FileManager`, runs every selected script against it, and
flushes to disk only at the end. A script that reads its input back from
`file.path` therefore sees the **pre-run** bytes and silently discards whatever an
earlier script changed. In `18.2` and `18.5-00-no-tax-tag-invert` it was worse
than stale: both `ndiff` the parsed tree against `file.content`, so the two
disagreeing would splice two different documents together. Use
`polib.pofile(file.content)` and `etree.parse(BytesIO(file.content.encode()))`.

## Deleting a spent script is normal

Upstream removes them once applied — `18.2-01-manifest-author.py` was deleted in
the very commit that applied it, and `17.5-00-tree-to-list.py` and
`18.1-01-rename-class.py` are likewise gone. The four scripts at 0 pending are
candidates.

The five with pending work are **not**: they are the only mechanical path to that
migration, and given the audit record above, the order matters — test the script,
run it, review the diff, *then* delete it.
