import sys
import types
from pathlib import Path

__all__ = ["stub_odoo_packages"]


def _stub_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__file__ = str(path / "__init__.py")
    sys.modules[name] = module


def stub_odoo_packages(conftest_file: str) -> None:
    tests_dir = Path(conftest_file).resolve().parent

    intermediates: list[Path] = []
    current = tests_dir.parent
    while current.name and current.name != "odoo":
        intermediates.append(current)
        current = current.parent

    if current.name != "odoo":
        raise RuntimeError(
            f"could not locate the 'odoo' package root above {conftest_file!r}"
        )

    _stub_package("odoo", current)
    name = "odoo"
    for package_dir in reversed(intermediates):
        name = f"{name}.{package_dir.name}"
        _stub_package(name, package_dir)
