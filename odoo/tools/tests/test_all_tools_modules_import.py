import subprocess
import sys
import textwrap
import unittest


class TestAllToolsModulesImport(unittest.TestCase):
    def test_every_tools_module_imports(self):
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
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            "unimportable odoo.tools modules:\n" + (result.stdout + result.stderr),
        )


if __name__ == "__main__":
    unittest.main()
