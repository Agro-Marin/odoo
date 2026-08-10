"""The implementation of the ORM (layered architecture).

The layer of each module below is the one ``layer_check.py`` enforces, so this
docstring and the gate cannot disagree; ``doc/architecture/module.md`` is
the prose companion. Note ``_typing.py`` is Layer 0, not cross-cutting: the
``orm-layer0-is-foundational`` contract names it alongside primitives/parsing/
validation/constants, and it may import no higher ORM layer.

Layer 0 — Zero-dependency foundations:
  primitives.py    Constants, Command, NewId, type aliases
  parsing.py       Field expression / read_group spec parsing
  validation.py    Name-checking helpers (pg, object, method)
  constants.py     Read group constants (granularity, aggregates, display)
  _typing.py       Composite type aliases (DomainType, ModelType)
  _protocols.py    What the framework requires of the addon-owned models it
                   reaches by string key; typing-only at runtime

Layer 1 — Field & domain system:
  fields/          Field type definitions
  domain/          Domain expression processing and optimization

Layer 2 — Model system:
  models/          BaseModel, MetaModel, mixins, table objects

Layer 3 — Runtime:
  runtime/         Environment, Transaction, Registry

Cross-cutting:
  components/      Pure-Python FieldCache / ComputeEngine / UnitOfWork /
                   ModelGraph. Imports nothing from odoo but odoo.libs;
                   Layers 2 and 3 use it, Layers 0 and 1 never do.
  decorators.py    API method decorators (@api.depends, @api.constrains, ...)
  registration.py  Model registration and setup
  helpers.py       Shared utility functions

Seams (cross-layer, deliberately not in any layer):
  _recordset.py    The Layer-1 inversion point: the model layer injects
                   BaseModel here so fields/ and domain/ can recognise a
                   recordset without importing Layer 2.
  model_test_env.py  DB-free test environment over components.storage.

Import from the public API packages (odoo.api, odoo.fields, odoo.models)
rather than directly from odoo.orm submodules.
"""

import odoo.init
