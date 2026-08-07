# Static declarations for the odoo root package.
#
# This stub is not optional. `__init__.py` resolves its public names through a
# module-level `__getattr__` (PEP 562) so that importing `odoo` costs nothing --
# but mypy treats a module with `__getattr__` as having EVERY attribute, which
# silently accepts typos and masks real errors. Measured when this landed:
# without the stub, four genuine `Module has no attribute "evented"` reports
# (service/lifecycle.py x3, http/request_class.py) disappeared, which would have
# looked like a ratchet improvement while actually losing coverage.
#
# With the stub present mypy ignores `__getattr__` and checks against exactly
# these names. Add a name here only when `__init__.py` can really resolve it.

from odoo.orm.primitives import SUPERUSER_ID as SUPERUSER_ID
from odoo.orm.primitives import Command as Command
from odoo.tools.translate import _ as _
from odoo.tools.translate import _lt as _lt

__all__ = ["SUPERUSER_ID", "Command", "_", "_lt", "evented"]

evented: bool
