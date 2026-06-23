"""The implementation of the ORM (layered architecture).

Layer 0 — Zero-dependency foundations:
  primitives.py    Constants, Command, NewId, type aliases
  parsing.py       Field expression / read_group spec parsing
  validation.py    Name-checking helpers (pg, object, method)
  constants.py     Read group constants (granularity, aggregates, display)

Layer 1 — Field & domain system:
  fields/          Field type definitions
  domain/          Domain expression processing and optimization

Layer 2 — Model system:
  models/          BaseModel, MetaModel, mixins, table objects

Layer 3 — Runtime:
  runtime/         Environment, Transaction, Registry

Cross-cutting:
  decorators.py    API method decorators (@api.depends, @api.constrains, ...)
  registration.py  Model registration and setup
  helpers.py       Shared utility functions
  _typing.py       Composite type aliases (DomainType, ModelType)

Import from the public API packages (odoo.api, odoo.fields, odoo.models)
rather than directly from odoo.orm submodules.
"""

# import first for core setup
import odoo.init
