# List Edit-Mode Render Cost — Investigation & Decision Record

Status: **Row-level waste fixed. Renderer-level amplification investigated and
not pursued.** Date: 2026-08-09.
Scope: what repaints when an editable list enters edition and when edition moves
from one row to another.

## Why this was opened

`ListRecordRow` exists so `t-props` diffing can skip an untouched row, and
`CONVENTIONS.md` asserts that it does. Measuring it found the skip working
exactly as documented — and a different, larger problem sitting next to it.

## What was actually wrong (fixed)

Rows do **not** re-render because prop diffing fails. They re-render
*themselves*: OWL re-targets a reactive prop to the child in both the
`ComponentNode` constructor and `updateAndRender`, so `rowFlags` — a
`reactive()` built with no callback — really does give each row a per-key
subscription.

That is what makes the flags cheap, and also what made a *transient* value
ruinous. Both flags were derived from `list.editedRecord`, which is momentarily
null inside `enterEditMode` between the outgoing record leaving edition and the
incoming one entering it. Moving the edited row therefore published
`false -> true -> false` and repainted every row twice, for a state no frame
ever shows.

| Interaction (40-row list) | Before | After |
|---|---|---|
| Enter edition | 40 row renders | 40 — **correct**, every selector checkbox really does disable |
| Move edition to another row | **81** | **4** |
| Move edition, list with a button column | **81** | **4** |

Fixed by `DynamicList#isEditing` / `StaticList#isEditing`, which span the
handover via a `markRaw` holder. Guarded by
`static/tests/views/list/list_edit_handover.test.js`, which asserts the flag's
value SEQUENCE and a row-render budget — endpoint assertions cannot see this,
because the before and after states are identical either way.

## What remains, and why it was not pursued

The renderer still renders **3 times per edit-move and patches once**: two full
renderer renders are discarded. Each runs an O(rows) `ListGridState.rebuild()`.

Measured at 200 rows, moving edition between rows:

| | |
|---|---|
| renderer renders / patches | 3 / 1 |
| `gridState.rebuild()` calls | 3 |
| total rebuild time | **0.80 ms** |
| attributable to the 2 discarded renders | **~0.5 ms** |

And the other per-render work, at 80 rows x 8 columns:

| | |
|---|---|
| `processAllColumns` | 3 calls, **0.00 ms** (memoised; the column objects are referentially stable, which is why `_toStableColumns` succeeds) |
| `getActiveColumns` | 3 calls, **0.50 ms** |

So the whole renderer-side waste of an edit-move is under a millisecond.

**Do not pursue.** The three renders correspond to real model transitions
published across `await` boundaries — the click, then `leaveEditMode`, then the
`enterEditMode` tail, each behind `model.mutex`. Collapsing them into one render
means restructuring the edit-mode mutex flow, which serialises saves and
validity checks. That is a substantial concurrency change to recover half a
millisecond on a 200-row list, and the rows — the part that scales with list
size and cost 20× more — are already fixed.

## Where this pattern is NOT present

Measured, so it need not be re-derived:

- **Kanban.** Opening or dismissing the quick create repaints **0** cards. A
  progress-bar click repaints the group because the group genuinely reloads.
  Pinned by `static/tests/views/kanban/kanban_render_budget.test.js`.
- **Form.** Focusing a field is **0** renders; editing one field is **1**, on a
  12-field form.
- **Control panel.** Focusing the search input, typing into it, and opening the
  filter dropdown each repaint **0** rows and **0** renderers.
- **Virtualized scrolling.** A 300-row list virtualizes to 27 visible rows; a
  scroll that grows the window to 36 repaints the **9** rows that entered it and
  skips the 27 already there.

## Technique

The questions here are about what a component *subscribed to*, which no
import-graph or export-surface gate can reach (`tooling/architecture/js_forced_render.py`
says as much about its own limits). What answers them:

- `node.__owl__.subscriptions` — OWL's own registry of what that component is
  actually subscribed to, per target and key.
- `node.__owl__.fiber.root.node` — tells a self-triggered render from one driven
  by the parent. If it is the component itself, prop diffing was never
  consulted.
- `__renderTrace` / `__renderStats` with `useRenderCounter` labels
  (`core/utils/render_instrumentation.js`) — render counts per component, without
  patching prototypes.
- Replicating `arePropsDifferent` against the live `node.props` distinguishes
  "props churn" from "the child rendered itself". Comparing successive
  `getRowProps` outputs does **not**: a skipped child keeps stale `node.props`,
  so that is the wrong baseline.

A caveat that cost time: after a `git checkout` / `git apply` cycle the warm
hoot server serves a stale bundle. 101 phantom `@web/fields` failures vanished
on restart. Restart the server before believing a sudden mass failure.

Key files: `views/list/list_renderer.js` (`rowFlags`, `canSelectRecord`) ·
`views/list/list_record_row.js` · `model/relational_model/dynamic_list.js`
(`isEditing`, `_editHandover`) · `model/relational_model/static_list.js` ·
`static/lib/owl/owl.es.js` (prop re-targeting in `ComponentNode`).
