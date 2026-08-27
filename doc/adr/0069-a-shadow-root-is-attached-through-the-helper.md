# ADR-0069: A shadow root is attached through the helper, so its host can be found

- **Status:** Accepted
- **Date:** 2026-08-27

## Context

A shadow root is the one DOM boundary that is **invisible to a query**. There is
no `:has-shadow-root` selector, no `MutationObserver` notification when a root is
attached, and `querySelectorAll` does not descend through one. The only way to
discover that a subtree contains a host is to walk every element in it and read
`.shadowRoot`.

That matters because several core helpers exist precisely to cross the tree:
`getTabableElements` builds the tab order a focus trap enforces,
`closestScrollableY` finds the scroller `scrollTo` should move, and each of them
was answering as though the shadow content were not there. Not failing —
answering, wrongly, in silence. Measured before the fix, a light-DOM container
holding a host returned only its light-DOM buttons.

This is not a hypothetical corner of the client. Three sites attach a shadow
root, and two of them mount a **whole Owl `App`** inside one: the portal chatter
on every public portal document page, the livechat embed on third-party pages,
and the body of every email-type message.

**The obvious fix is the expensive one.** Discovering hosts by walking every
element costs, measured on an 8 000-element form, about **+1.3 ms on top of
3.2 ms** — roughly +40% on `getTabableElements`, which runs once per Tab
keypress on every form in the product. Paying that on every page so that three
of them are traversed correctly is the wrong trade, and it was rejected on that
number rather than on taste.

## Decision

**A shadow root is attached through `attachShadowRoot` from
`@web/core/utils/dom/ui`, which marks its host with an attribute.**

The mark moves the cost from traversal time, where there are thousands of
elements, to attach time, where there is exactly one host. Helpers that must
cross the boundary then find hosts with the query they were already running.
`getTabableElements` keeps a fast path for the overwhelmingly common case of a
subtree with no host at all, and measured interleaved against the previous
implementation over 8 000 elements it is **not slower** (−0.5%, −4.0%, −2.4%
across three runs).

## Alternatives considered

**Walk every element and read `.shadowRoot`.** Correct, needs no discipline from
callers, and cannot be bypassed. Rejected on the measurement above: +40% on a
per-keystroke path, paid by every form, to serve three pages.

**Keep a registry of hosts in a module-level `WeakSet`, populated by the
helper.** Same discipline requirement as the attribute, and it still cannot be
*queried* — finding which hosts are inside a given subtree means walking the
subtree and testing membership, which is the rejected alternative again with an
extra data structure.

**Make the helpers take an explicit list of roots to search.** Pushes the problem
to callers, who are components that do not know which of their descendants host a
shadow root; the focus trap in `ui_service` is handed one container and nothing
else.

**Replace `isVisible` with `Element.checkVisibility` to buy back the cost.** It
is genuinely cheaper (0.91 ms against 1.52 for 2 000 elements) but it is not the
same predicate: it disagrees on `visibility:hidden` (false where `isVisible` says
true), on zero-size elements (true where `isVisible` says false), and on a
`display:contents` container (false where `isVisible` recurses into children).
Swapping it would change what "visible" means across every caller — a decision
that deserves its own record, not a footnote in this one.

**Do nothing and document the gap.** This was the position for one pass of the
audit, and it is why the measurement exists. It stopped being defensible once
the marking approach turned out to cost nothing.

## Consequences

Root-crossing helpers can be written against a selector, so the next one — a
containment test, a serializer, a screenshot walker — costs a query rather than a
tree walk. The tab order a focus trap enforces now matches the browser's across
the boundary, including that a positive `tabIndex` inside a shadow root sorts
ahead of a `0` outside it.

The cost is a discipline: a raw `attachShadow` produces a tree that every
root-crossing helper steps over, and it does so silently. That is the failure
mode this record exists to stop, and it is why the rule is a gate rather than a
convention. Third-party or vendored code that attaches its own root is outside
the rule and outside the traversal, which is a real limit and is pinned by a test
asserting exactly that, so the next reader meets it as a statement rather than a
mystery.

## Enforcement

`tooling/architecture/js_shadow_root.py`, drift-zero with no tolerated list, run
as a blocking step in `.github/workflows/architecture.yml`. It scans every
addon's `static/src` and reports any `.attachShadow(` outside the helper's own
file, with the line. Tests are not scanned: a test that attaches a raw shadow
root to prove the traversal ignores it is asserting this rule, not breaking it.

`tooling/architecture/test_js_shadow_root.py` covers the gate itself — that it
catches a raw call, that a call through the helper is clean, that the helper is
exempt only under its own path, that every call in a file is reported rather than
the first, and that the word alone in a comment is not a call. The traversal's
own behaviour is pinned in `addons/web/static/tests/core/shadow_root_focus.test.js`.
