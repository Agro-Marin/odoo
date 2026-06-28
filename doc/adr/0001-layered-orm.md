# ADR-0001: Layered ORM (Layer 0–3)

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

Upstream Odoo concentrates the ORM in a handful of very large modules
(`models.py`, `fields.py`, `api.py`). Concerns are interleaved: descriptor
mechanics, SQL generation, the field/domain system, the model metaclass, the
environment, and the registry all reference one another, which makes the import
graph cyclic and forces large files to be understood as a whole. The fork is
free of upstream backward-compatibility constraints on `19.0-marin`.

## Decision

Organise the ORM (`odoo/orm/`) as explicit layers with a single downward
runtime-dependency direction, as documented in `odoo/orm/__init__.py`:

- **Layer 0** — `primitives`, `parsing`, `validation`, `constants`, `_typing`:
  zero intra-`odoo` runtime dependencies.
- **Layer 1** — `fields/`, `domain/`: depend only on Layer 0.
- **Layer 2** — `models/` (`BaseModel`, the mixins, the metaclass): build on 0–1.
- **Layer 3** — `runtime/` (`Environment`, `Registry`, `Transaction`): build on 0–2.

Cross-layer references needed only for typing are permitted **exclusively**
under `if TYPE_CHECKING:`, where they never execute and therefore cannot create
an import cycle.

## Consequences

- Each file can be reasoned about within its layer; the dependency direction is
  predictable.
- New field types or domain optimisations (Layer 1) cannot reach into models or
  runtime, which keeps the field system reusable and the import graph acyclic.
- The cost: a small amount of ceremony (`TYPE_CHECKING` guards, occasional
  deferred imports) where a lower layer must recognise a higher-layer object at
  runtime — see the known exceptions below.

### Layer-1 → Layer-2 inversion seam (resolved 2026-06)

`orm/domain/ast.py` and `orm/fields/relational.py` previously did a
function-local `from ..models import BaseModel` to normalise domain values
(recognise a stray recordset) and to detect a `_search` override. These deferred
imports broke the import *cycle* but were still a Layer-1 → Layer-2 runtime
dependency.

They were replaced by **`orm/_recordset.py`**, a Layer-1 inversion seam: the
model layer injects the concrete `BaseModel` class once at import time
(`orm/models/base.py` calls `set_base_model`), and Layer 1 consumes it through
two predicates, `is_recordset(value)` and `is_search_overridden(model_cls)` —
never naming `BaseModel`. This follows the same injection pattern used between
`db/` and the ORM (ADR-0003) and the components (ADR-0002).

A structural `@runtime_checkable` `Protocol` was considered but rejected: one
call site needs an *exact* recordset check (a structural match risks false
positives that would silently rewrite a domain value), and the other needs the
*actual* base `BaseModel._search` method object to compare against, which a
Protocol cannot provide. Injection gives both, with identical behaviour to the
original code and no import-direction violation.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`orm-layer1-below-models-and-runtime` (currently **clean at zero**). The checker
skips `TYPE_CHECKING` blocks, so the typing-only references (used for
annotations in both files) remain legal while runtime crossings fail CI.
