"""Make the standalone tooling scripts importable by their sibling tests.

The gates and generators here are standalone scripts, not an installed package,
so ``import scope_gate`` only resolves if the script's own directory is on
``sys.path``. Only ``architecture/`` used to carry a conftest doing that, so
``test_ratchet.py`` and ``test_scope_gate.py`` failed collection with
``ModuleNotFoundError`` — and since ``tooling/`` was not in ``testpaths`` either,
a plain ``pytest`` run never surfaced it. One conftest at the tooling root covers
every subdirectory, present and future.

Note the consequence: every tool's directory shares one flat namespace, so two
tools must never ship a module of the same name. The order is sorted rather
than ``iterdir``'s, which is filesystem order — on this checkout that happens
to be ``ratchet, hoot, codegen, typecheck, doclinks, architecture, vendored``,
and on a fresh clone or another filesystem it is something else. A name
collision would then resolve differently per machine, which is the hardest kind
of failure to reproduce.

The insertion runs BACK to front. ``sys.path.insert(0, ...)`` in a loop reverses
whatever order it is fed, so sorting the directories and then inserting them
front to back produced *reverse*-sorted precedence, with ``tooling/`` itself —
the directory holding ``_repo_root`` — last of the nine rather than first. The
resolution order was still deterministic, so nothing broke; it simply was not
the order the paragraph above describes, and a doc that describes a different
order than the code implements is worse than no doc. Iterating in reverse makes
the final ``sys.path`` read ``tooling, architecture, codegen, …``.
"""

import sys
from pathlib import Path

_TOOLING = Path(__file__).resolve().parent

_TOOL_DIRS = sorted(
    p for p in _TOOLING.iterdir() if p.is_dir() and p.name != "__pycache__"
)
for _path in reversed((_TOOLING, *_TOOL_DIRS)):
    sys.path.insert(0, str(_path))
