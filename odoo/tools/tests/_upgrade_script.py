import importlib.util
import pathlib
from types import ModuleType

UPGRADE_CODE = pathlib.Path(__file__).resolve().parents[2] / "upgrade_code"


def load_upgrade_script(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, UPGRADE_CODE / filename)
    if spec is None or spec.loader is None:
        msg = f"cannot load upgrade script {filename!r}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
