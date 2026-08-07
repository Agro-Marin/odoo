from .module_operations import install

if __name__ == "__main__":
    import runpy

    runpy.run_module("odoo.tests.module_operations", run_name="__main__")
