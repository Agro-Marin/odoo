"""Layer 0 — Zero-dependency foundations:
  primitives.py
  parsing.py
  validation.py
  constants.py
  _typing.py
  _protocols.py

Layer 1 — Field & domain system:
  fields/
  domain/

Layer 2 — Model system:
  models/

Layer 3 — Runtime:
  runtime/

Below runtime, above layer 0:
  helpers.py
  registration.py
  _recordset.py
  decorators.py

Pure-Python, no odoo import:
  components/

Test support:
  model_test_env.py
"""

import odoo.init
