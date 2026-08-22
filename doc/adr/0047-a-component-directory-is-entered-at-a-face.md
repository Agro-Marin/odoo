# ADR-0047: A component directory is entered at a face

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

`js_face_boundary` refuses an import that reaches *past* a face — a `foo.js`
sitting beside `foo/`, re-exporting what the directory offers. It says nothing
about which directories should have one, because a face is discovered, not
declared: the gate globs for the pairing and enforces entry wherever it finds it.

That leaves the prior question unanswered, and `components/` is where the silence
shows. Twelve of its directories carry a face — `barcode`, `datetime`,
`dropdown`, `dropzone`, `errors`, `file_upload`, `file_viewer`,
`model_field_selector`, `pager`, `record_selectors`, `signature`, `tree_editor`
— and seventeen do not, while being imported from outside `web` the same way.

The split looks like it should mean something and does not. Measured: every one
of those directories is reached through **exactly one** module from outside
`web`, faced or not. The faced ones are reached at their face; the others at
whatever inner module holds the component. `color_picker` is reached through two
and has no face — the combination a "more than one consumer module" theory would
have predicted least.

So it is history, not design. A new component's author has no rule to apply, and
CI cannot tell them they got it wrong — which is how `hr` came to import
`@web/components/record_selectors/avatar_models` past a face that existed
(`ab86f97b678`).

## Decision

**A directory under `components/` that is imported from outside `web` has a
face.** Outside consumers enter at `@web/components/<name>`; what the directory
keeps behind it is the directory's business.

Enforced by `tooling/architecture/js_component_face.py` against a pinned list of
directories that do not yet comply — **shrink-only**. A new faceless directory
reached from outside fails the build; a directory that gains a face leaves the
pin in the same commit.

The seventeen are not migrated here: 171 import sites across 150 files in three
repositories, a coordinated change in `odoo`, `enterprise` and `agromarin`
rather than a commit. The pin makes each one a task with a known scope.

## Alternatives considered

**Require a face on every directory, reached from outside or not.** Uniform and
simpler to state. Rejected because the reason for a face is the boundary: a
directory only `web` imports has no outside entry to constrain, and demanding a
re-export module for it is ceremony that would itself need a suppression list.

**Drop faces entirely and let everyone import the deep path.** Also uniform, and
what seventeen directories already do. Rejected because it discards what the face
buys — the directory can move a file, split a component or rename an internal
module without touching three repositories.

**Infer the rule from consumer count** — a face once two modules are reached.
The tree refutes it: every directory is reached through one module, and the only
two-module case (`color_picker`) is faceless. A rule the current tree contradicts
in its single distinguishing case was never followed.

**Migrate the seventeen in this commit.** Rejected on blast radius, not merit:
171 sites across three repositories, in a workspace where other sessions hold
uncommitted work in all three.

## Consequences

New components get a rule and a failing build when they miss it. The seventeen
become an enumerated backlog, each entry costing one face module and its
consumers' imports.

`js_public_surface` moves with each migration: the deep specifier stops being
imported from outside `web` and leaves the pin, the face specifier joins it. The
same trade `ab86f97b678` made for `record_selectors/avatar_models`, and it
shrinks the surface — one entry per directory instead of one per module.

## Enforcement

`tooling/architecture/js_component_face.py --check`, blocking in
`architecture.yml`. `tooling/architecture/test_js_component_face.py` pins the
detector: that a face is `foo.js` beside `foo/`, that a directory imported only
from inside `web` is not required to have one, and that the pin fails in both
directions. `test_every_gate_refuses_an_empty_tree` covers the empty scan.
