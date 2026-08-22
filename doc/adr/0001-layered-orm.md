# ADR-0001: Layered ORM (Layer 0–3)

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

Upstream concentrates the ORM in a few very large modules (`models.py`,
`fields.py`, `api.py`). Descriptor mechanics, SQL generation, the field/domain
system, the metaclass, the environment and the registry all reference one
another: the import graph is cyclic and each file must be understood whole.
`19.0-marin` carries no upstream backward-compatibility constraint.

## Decision

Organise `odoo/orm/` as layers with one downward runtime-dependency direction,
documented in `odoo/orm/__init__.py`:

- **Layer 0** — `primitives`, `parsing`, `validation`, `constants`, `_typing`:
  no intra-`odoo` runtime dependencies.
- **Layer 1** — `fields/`, `domain/`: Layer 0 only.
- **Layer 2** — `models/` (`BaseModel`, mixins, metaclass): Layers 0–1.
- **Layer 3** — `runtime/` (`Environment`, `Registry`, `Transaction`): Layers 0–2.

Cross-layer references for typing are permitted **only** under
`if TYPE_CHECKING:`, which never executes and so cannot create a cycle.

## Consequences

- Each file is reasoned about within its layer; the dependency direction is
  predictable.
- New field types and domain optimisations (Layer 1) cannot reach models or
  runtime, keeping the field system reusable and the graph acyclic.
- Cost: `TYPE_CHECKING` guards and occasional deferred imports where a lower
  layer must recognise a higher-layer object at runtime.

### Layer-1 → Layer-2 inversion seam (resolved 2026-06)

`orm/domain/ast.py` and the relational fields module (now the
`orm/fields/relational/` package) did a function-local
`from ..models import BaseModel` to normalise domain values and to detect a
`_search` override. That broke the cycle but kept a Layer-1 → Layer-2 runtime
dependency.

Replaced by **`orm/_recordset.py`**: the model layer injects the concrete
`BaseModel` class once at import time (`orm/models/base.py` calls
`set_base_model`), and Layer 1 consumes it through `is_recordset(value)` and
`is_search_overridden(model_cls)`, never naming `BaseModel`. Same injection
pattern as `db/`↔ORM (ADR-0003) and the components (ADR-0002).

A `@runtime_checkable` `Protocol` was rejected: one call site needs an exact
recordset check (a structural match would silently rewrite a domain value), and
the other needs the actual base `BaseModel._search` method object to compare
against, which a Protocol cannot supply.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`orm-layer1-below-models-and-runtime`. The checker skips `TYPE_CHECKING`
blocks, so typing-only references stay legal and runtime crossings fail CI. Run
the checker for the contract's live status.

## Amendments

### 2026-08-07 — the live contract status is no longer restated here

Enforcement said the contract was "currently **clean at zero**". That is a fact
about a moment in an immutable record, so it could only become false. Replaced
by a citation.

### 2026-08-09 — the relational fields module is a package now

The seam section named a single module. It was decomposed into
`orm/fields/relational/` (`_base.py`, `many2one.py`, `many2many.py`,
`one2many.py`) after this record was written; the seam holds in each file.
Corrected in place — a citation, not the decision.
