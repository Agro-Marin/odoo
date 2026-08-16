import sys
from pathlib import Path

_TOOLING = Path(__file__).resolve().parent

_TOOL_DIRS = sorted(
    p for p in _TOOLING.iterdir() if p.is_dir() and p.name != "__pycache__"
)
for _path in reversed((_TOOLING, *_TOOL_DIRS)):
    sys.path.insert(0, str(_path))
