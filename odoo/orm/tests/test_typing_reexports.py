import ast
import pathlib

import pytest

_ORM_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TYPING = _ORM_ROOT / "_typing.py"


def _names_provided_by(module_path: pathlib.Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    provided: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.ImportFrom(names=names):
                provided |= {a.asname or a.name for a in names}
            case ast.Assign(targets=targets):
                provided |= {t.id for t in targets if isinstance(t, ast.Name)}
            case ast.AnnAssign(target=ast.Name(id=name)):
                provided.add(name)
            case ast.TypeAlias(name=ast.Name(id=name)):
                provided.add(name)
            case ast.ClassDef(name=name) | ast.FunctionDef(name=name):
                provided.add(name)
    return provided


def _typing_imports_across_orm() -> list[tuple[pathlib.Path, str]]:
    edges: list[tuple[pathlib.Path, str]] = []
    for path in _ORM_ROOT.rglob("*.py"):
        if path == _TYPING or "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                "_typing"
            ):
                edges.extend((path, alias.name) for alias in node.names)
    return edges


def test_typing_reexports_every_name_the_orm_imports_from_it():
    provided = _names_provided_by(_TYPING)
    missing = sorted(
        {
            f"{name} (imported by {path.relative_to(_ORM_ROOT)})"
            for path, name in _typing_imports_across_orm()
            if name not in provided
        }
    )
    assert not missing, (
        "names imported from _typing but not provided by it:\n" + "\n".join(missing)
    )


def test_typing_all_matches_module_bindings():
    provided = _names_provided_by(_TYPING)
    tree = ast.parse(_TYPING.read_text(encoding="utf-8"))
    dunder_all: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "__all__" for t in node.targets)
            and isinstance(node.value, ast.List)
        ):
            dunder_all = [
                el.value
                for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            ]
    assert dunder_all, "_typing.py must declare __all__"
    orphans = sorted(set(dunder_all) - provided)
    assert not orphans, f"__all__ names not bound in _typing.py: {orphans}"


@pytest.mark.parametrize("name", ["CommandValue", "Registry"])
def test_regression_specific_missing_reexports(name):
    assert name in _names_provided_by(_TYPING)
