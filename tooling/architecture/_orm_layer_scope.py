from __future__ import annotations

from pathlib import Path

SCOPE: dict[str, str] = {
    "orm/__init__.py": "Layer 0",
    "orm/_typing.py": "Layer 0",
    "orm/_protocols.py": "Layer 0",
    "orm/constants.py": "Layer 0",
    "orm/primitives.py": "Layer 0",
    "orm/parsing.py": "Layer 0",
    "orm/validation.py": "Layer 0",
    "orm/_recordset.py": "Layer 1",
    "orm/decorators.py": "Layer 1",
    "orm/fields": "Layer 1",
    "orm/domain": "Layer 1",
    "orm/helpers.py": "Layer 2",
    "orm/registration.py": "Layer 2",
    "orm/models": "Layer 2",
    "orm/components": "components",
}

RUNTIME_PACKAGE = "runtime"

EXEMPT: dict[str, str] = {
    "orm/model_test_env.py": (
        "The DB-free test harness. It CONSTRUCTS Environment, Transaction and "
        "Registry by design, so every reach it makes is the thing it exists to "
        "do. layer_check exempts it from "
        "orm-helpers-and-registration-stay-below-runtime for the same reason."
    ),
}


def iter_scope_files(core: Path) -> list[tuple[Path, str]]:

    out: list[tuple[Path, str]] = []
    for rel, layer in SCOPE.items():
        target = core / rel
        if target.is_dir():
            paths = sorted(target.rglob("*.py"))
        elif target.is_file():
            paths = [target]
        else:
            continue
        for path in paths:
            parts = path.relative_to(core).parts
            if (
                "tests" in parts
                or "__pycache__" in parts
                or path.name.startswith("test_")
            ):
                continue
            out.append((path, layer))
    return out


def unclassified_modules(core: Path) -> list[str]:

    orm = core / "orm"
    if not orm.is_dir():
        return []
    classified = set(SCOPE) | set(EXEMPT) | {f"orm/{RUNTIME_PACKAGE}"}
    missing: list[str] = []
    for child in sorted(orm.iterdir()):
        if child.name in ("__pycache__", "tests"):
            continue
        if child.is_dir():
            if not (child / "__init__.py").is_file():
                continue
            rel = f"orm/{child.name}"
        elif child.suffix == ".py":
            rel = f"orm/{child.name}"
        else:
            continue
        if rel not in classified:
            missing.append(rel)
    return missing
