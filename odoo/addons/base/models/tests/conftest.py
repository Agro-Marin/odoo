import sys
import types
from pathlib import Path

from odoo._testing_bootstrap import stub_odoo_packages

stub_odoo_packages(__file__)


def _stub_pytest_package_chain() -> None:
    tests_dir = Path(__file__).resolve().parent
    for name, path in (
        ("base", tests_dir.parents[1]),
        ("base.models", tests_dir.parents[0]),
    ):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            module.__package__ = name
            module.__file__ = str(path / "__init__.py")
            sys.modules[name] = module


_stub_pytest_package_chain()


def _ensure_tools_stub() -> None:
    tools = sys.modules.get("odoo.tools")
    if tools is None:
        tools_path = Path(__file__).resolve().parents[4] / "tools"
        tools = types.ModuleType("odoo.tools")
        tools.__path__ = [str(tools_path)]
        tools.__package__ = "odoo.tools"
        tools.__file__ = str(tools_path / "__init__.py")
        sys.modules["odoo.tools"] = tools

    if not hasattr(tools, "frozendict"):

        class frozendict(dict):
            pass

        tools.frozendict = frozendict

    if not hasattr(tools, "_"):

        def _(source, *args, **kwargs):
            if args:
                return source % args
            if kwargs:
                return source % kwargs
            return source

        tools._ = _


_ensure_tools_stub()
