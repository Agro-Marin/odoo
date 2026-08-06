"""Every ``odoo/tools/*.py`` module must import in a real interpreter.

The Tier-1 sweep import-tests all of ``odoo/libs`` (it is in ``pytest.ini``'s
``testpaths`` under ``--doctest-modules``), but only ``odoo/tools/tests`` — never
``odoo/tools/*.py`` itself. That is how ``odoo.tools.float_utils`` shipped
importing a name ``odoo.libs.numbers`` did not export: nothing loaded the module,
so 60 downstream addons would have died at install with no Tier-1 signal.

This closes that gap directly. It runs the imports in a **fresh subprocess** with
a clean interpreter rather than in-process, because the standalone tools/libs
suites register process-global ``sys.modules`` stubs for ``odoo`` / ``odoo.tools``
(``odoo._testing_bootstrap``); importing the real modules in this process would
either hit those stubs or install the real packages and disturb sibling suites.
A subprocess sees neither.
"""

import subprocess
import sys
import textwrap
import unittest


class TestAllToolsModulesImport(unittest.TestCase):
    def test_every_tools_module_imports(self):
        # The child discovers and imports every leaf; it reports failures as
        # "<module>: <ExcType>: <msg>" lines so the assertion names the culprit.
        program = textwrap.dedent(
            """
            import importlib, pathlib, sys
            import odoo.tools as t
            failures = []
            for path in sorted(pathlib.Path(t.__path__[0]).glob("*.py")):
                name = path.stem
                if name == "__init__":
                    continue
                try:
                    importlib.import_module("odoo.tools." + name)
                except Exception as exc:  # noqa: BLE001 - report, don't mask
                    failures.append(f"{name}: {type(exc).__name__}: {exc}")
            if failures:
                print("\\n".join(failures))
                sys.exit(1)
            sys.exit(0)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,  # returncode is asserted below with a named message
        )
        self.assertEqual(
            result.returncode,
            0,
            "unimportable odoo.tools modules:\n" + (result.stdout + result.stderr),
        )


if __name__ == "__main__":
    unittest.main()
