import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_bytes())
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Rule":
        if node.args and isinstance(first := node.args[0], ast.Constant):
            if isinstance(first.value, str):
                sys.stdout.write(first.value + "\n")
