from __future__ import annotations

import ast
from pathlib import Path

TIERS: dict[str, dict[str, list[str]]] = {
    "db": {
        "connectivity": [
            "pool",
            "cursor",
            "ddl",
            "schema",
            "savepoint",
            "schema_cache",
            "bulk",
            "lifecycle",
            "errors",
            "dsn",
            "utils",
        ],
        "resilience": [
            "breaker",
            "lag",
            "budget",
            "leaks",
            "reaper",
            "metrics",
            "stats",
        ],
    },
    "http": {
        "serving": [
            "application",
            "dispatcher",
            "routing",
            "session",
            "request_class",
            "_serve",
            "_response",
            "wrappers",
            "stream",
            "_csrf",
            "controller",
            "core",
        ],
        "features": [
            "openapi",
            "_params",
            "geoip",
            "constants",
            "exceptions",
            "_protocols",
            "helpers",
        ],
    },
}


def count_edges(
    root: Path, package: str, per_symbol: bool
) -> dict[tuple[str, str], int]:
    groups = TIERS[package]
    of = {mod: tier for tier, mods in groups.items() for mod in mods}
    counted: dict[tuple[str, str], int] = {}
    for path in sorted((root / "odoo" / package).glob("*.py")):
        here = of.get(path.stem)
        if here is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        deferred: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                deferred |= {id(inner) for inner in ast.walk(node)}
        for node in ast.walk(tree):
            if id(node) in deferred or not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 1 and node.module:
                targets = [node.module.split(".")[0]]
            elif node.level == 1:
                targets = [alias.name for alias in node.names]
            elif node.module and node.module.startswith(f"odoo.{package}."):
                targets = [node.module.split(".")[2]]
            else:
                continue
            for target in targets:
                there = of.get(target)
                if there is None or there == here:
                    continue
                key = (here, there)
                counted[key] = counted.get(key, 0) + (
                    len(node.names) if per_symbol else 1
                )
    return counted
