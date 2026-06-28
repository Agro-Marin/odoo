"""Make ``layer_check`` importable by the sibling test module.

``layer_check.py`` is a standalone script (not part of an installed package), so
add its directory to ``sys.path`` before the test module is collected.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
