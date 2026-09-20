import ast
import sys
from pathlib import Path

CONSTRUCTORS = {"Rule", "XmlRule"}

for path in sys.argv[1:]:
    tree = ast.parse(Path(path).read_bytes())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in CONSTRUCTORS:
            if node.args and isinstance(first := node.args[0], ast.Constant):
                if isinstance(first.value, str):
                    sys.stdout.write(first.value + "\n")
