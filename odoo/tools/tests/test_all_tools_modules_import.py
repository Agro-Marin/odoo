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
            root = pathlib.Path(t.__path__[0])
            failures = []
            scanned = 0
            # rglob, not glob: the non-recursive version skipped 9 of the 39
            # modules -- all of assets/ (5), babel_extractors/ (2) and pdf/ (2),
            # which are precisely the subpackages carrying import-time side
            # effects (pdf/__init__.py patches pypdf.filters.decompress and
            # DictionaryObject.get at module scope).
            for path in sorted(root.rglob("*.py")):
                if path.stem == "__init__":
                    continue
                if "tests" in path.parts or "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(root).with_suffix("")
                name = "odoo.tools." + ".".join(rel.parts)
                scanned += 1
                try:
                    importlib.import_module(name)
                except Exception as exc:  # noqa: BLE001 - report, don't mask
                    failures.append(f"{name}: {type(exc).__name__}: {exc}")
            if failures:
                print("\\n".join(failures))
                sys.exit(1)
            # Guard against the scan silently matching nothing.
            if scanned < 30:
                print(f"only {scanned} modules scanned; the walk is broken")
                sys.exit(2)
            print(f"scanned {scanned}")
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
