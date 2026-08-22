# ADR-0005: Enforce architectural boundaries in CI

- **Status:** Accepted
- **Date:** 2026-06-23

## Context

ADRs 0001–0004 establish four load-bearing boundaries: ORM layering, the purity
of `orm/components`, the ORM-agnosticism of `db/`, the dependency-freedom of
`libs/`. They held by convention alone — an `orm/__init__.py` docstring and
reviewer habit. One innocent import re-introduces a cycle or drags the
framework into a dependency-free module, and nothing catches it until it causes
a problem far away.

Off-the-shelf import linters (`import-linter` and kin) are a poor fit: this
layering *depends on* `TYPE_CHECKING`-guarded cross-layer imports, which they
flag by default.

## Decision

Add a stdlib-only checker, `tooling/architecture/layer_check.py`, that:

- parses each module's AST and counts **runtime** imports only, skipping
  `if TYPE_CHECKING:` blocks;
- resolves relative imports to absolute dotted paths;
- evaluates the boundary contracts — the Layer 0→3 ordering
  (`orm-layer0-is-foundational`, `orm-layer1-below-models-and-runtime`,
  `orm-models-below-runtime`) plus the purity contracts (`libs`, `db`,
  `orm/components`), six at this decision. The live set is `layer_check.py`'s
  `CONTRACTS`;
- treats the annotated `KNOWN_VIOLATIONS` allowlist as tolerated debt and fails
  on any new crossing.

Its own stdlib-only suite (`tooling/architecture/test_layer_check.py`) covers
relative-import resolution, `TYPE_CHECKING` skipping, prefix matching, and that
the core stays at zero violations.

Gate it in `.github/workflows/architecture.yml`. The convention is warn-first,
then blocking; it reported zero new violations, so it goes in **blocking** —
its tests first, then the check.

## Consequences

- The six boundaries become verified invariants rather than aspirations.
- At this decision the core has **zero** tolerated exceptions; an unavoidable
  one is pinned in `KNOWN_VIOLATIONS`, visible and unable to multiply.
- Fork-local code to maintain, itself tested. A new boundary means a new
  contract entry, and ideally a new record.

## Enforcement

The checker enforces itself: `python tooling/architecture/layer_check.py --check`.

## Amendments

### 2026-08-07 — two counts re-dated to the decision that made them

The Decision said "six" contracts and the Consequences that the core
"currently has zero tolerated exceptions". Both were true on 2026-06-23 and
neither is a claim an immutable record can keep: the contract set has grown,
and the pinned-violation count belongs to `layer_check.py`. Both now say when
they were measured and where the live value lives.
