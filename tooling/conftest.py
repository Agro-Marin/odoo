"""Make the standalone tooling scripts importable by their sibling tests.

The gates and generators here are standalone scripts, not an installed package,
so ``import scope_gate`` only resolves if the script's own directory is on
``sys.path``. Only ``architecture/`` used to carry a conftest doing that, so
``test_ratchet.py`` and ``test_scope_gate.py`` failed collection with
``ModuleNotFoundError`` — and since ``tooling/`` was not in ``testpaths`` either,
a plain ``pytest`` run never surfaced it. One conftest at the tooling root covers
every subdirectory, present and future.
"""

import sys
from pathlib import Path

_TOOLING = Path(__file__).resolve().parent

for _path in (_TOOLING, *(p for p in _TOOLING.iterdir() if p.is_dir())):
    if _path.name != "__pycache__":
        sys.path.insert(0, str(_path))
