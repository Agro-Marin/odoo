# ADR-0005: Enforce architectural boundaries in CI

- **Status:** Accepted
- **Date:** 2026-06-23

## Context

ADRs 0001–0004 establish four load-bearing boundaries: the ORM layering, the
purity of `orm/components`, the ORM-agnosticism of `db/`, and the
dependency-freedom of `libs/`. Today these hold only by convention — they are
stated in the `orm/__init__.py` docstring and reviewer habit. As the team grows,
convention erodes: a single innocent import re-introduces a cycle or drags the
framework into a "dependency-free" module, and nothing catches it until it
causes a problem far away.

Off-the-shelf import linters (e.g. `import-linter`) are a poor fit because the
fork's layering *depends on* `TYPE_CHECKING`-guarded cross-layer imports, which
those tools flag by default — the exact pattern the architecture relies on would
be reported as a violation.

## Decision

Add a dependency-free (stdlib-only) checker,
`tooling/architecture/layer_check.py`, that:

- parses each module's AST and counts only **runtime** imports, **skipping
  `if TYPE_CHECKING:` blocks**;
- resolves Odoo's pervasive **relative imports** to absolute dotted paths;
- evaluates the boundary contracts — the full Layer 0→3 ORM ordering
  (`orm-layer0-is-foundational`, `orm-layer1-below-models-and-runtime`,
  `orm-models-below-runtime`) plus the purity contracts (`libs`, `db`,
  `orm/components`) — six in total;
- treats a pinned, annotated `KNOWN_VIOLATIONS` allowlist as tolerated debt and
  fails on **any new** crossing (drift-zero by design).

The checker has its own stdlib-only test suite
(`tooling/architecture/test_layer_check.py`) covering relative-import
resolution, `TYPE_CHECKING` skipping, prefix matching, and a regression guard
that the real framework core stays at zero violations.

Gate it in CI via `.github/workflows/architecture.yml`, following the team's
established phased-gate convention (warn-only first, flip to blocking). Because
the checker already reports **zero new violations**, it runs **blocking** — its
own tests run first, then the check.

## Consequences

- The six boundaries become guaranteed invariants rather than aspirations; the
  full Layer 0→3 layering and the pure-Python / ORM-agnostic claims are verified
  on every PR.
- The framework core currently has **zero** tolerated exceptions; should an
  unavoidable one arise, it is pinned (annotated) in `KNOWN_VIOLATIONS`, visible
  and unable to multiply.
- The checker is fork-local code to maintain (and is itself tested); new
  boundaries require a new contract entry (and ideally a new ADR).

## Enforcement

The checker enforces itself. Run locally with
`python tooling/architecture/layer_check.py --check`.
