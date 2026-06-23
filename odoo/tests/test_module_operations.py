"""Back-compat shim — moved to :mod:`odoo.tests.module_operations`.

The module was renamed to drop the misleading ``test_`` prefix (it is a
standalone module-operations CLI harness, not a pytest test module).  This
keeps the old ``from odoo.tests.test_module_operations import install`` import
and the ``python -m odoo.tests.test_module_operations`` invocation working.
"""

from .module_operations import install  # noqa: F401

if __name__ == "__main__":
    import runpy

    # Re-run the renamed module as __main__ so the CLI behaves identically.
    runpy.run_module("odoo.tests.module_operations", run_name="__main__")
