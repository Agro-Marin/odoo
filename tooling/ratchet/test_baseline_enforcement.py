from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "architecture"))
import _ast_cache

HERE = Path(__file__).resolve().parent
ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_baseline_enforcement")
BASELINES_DIR = HERE / "baselines"
_ASSERT_RATCHET = re.compile(r"assert_ratchet\(")

_PY_CONSUMERS = ("odoo/addons/test_lint/tests",)


def recorded_floors() -> set[str]:
    return {path.stem for path in BASELINES_DIR.glob("*.json")}


def _py_consumer_files() -> list[Path]:
    return [
        path
        for rel in _PY_CONSUMERS
        if (ROOT / rel).is_dir()
        for path in sorted((ROOT / rel).rglob("*.py"))
    ]


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _gate_arg(call: ast.Call) -> ast.AST | None:
    if len(call.args) > 1:
        return call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "gate":
            return keyword.value
    return None


def _rule_gates(tree: ast.Module) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Rule":
            name = _literal_str(node.args[0]) if node.args else None
            if name:
                found.add("lint_" + name.replace("-", "_"))
    return found


def _forwarding_params(tree: ast.Module) -> dict[str, int]:
    forwarding = {}
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        names = [a.arg for a in func.args.args]
        if names and names[0] in ("self", "cls"):
            names = names[1:]
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "assert_ratchet"
            ):
                arg = _gate_arg(node)
                if isinstance(arg, ast.Name) and arg.id in names:
                    forwarding[func.name] = names.index(arg.id)
    return forwarding


def asserted_gates() -> set[str]:
    found: set[str] = set()
    for path in _py_consumer_files():
        tree = _ast_cache.parse_file(path)
        found |= _rule_gates(tree)
        forwarding = _forwarding_params(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) == "assert_ratchet":
                name = _literal_str(_gate_arg(node))
                if name:
                    found.add(name)
                continue
            index = forwarding.get(getattr(node.func, "attr", None)) or forwarding.get(
                getattr(node.func, "id", None)
            )
            if index is not None and len(node.args) > index:
                name = _literal_str(node.args[index])
                if name:
                    found.add(name)
    return found


def test_the_discovery_finds_something():
    assert len(recorded_floors()) > 20, f"only {len(recorded_floors())} baselines found"
    files = _py_consumer_files()
    assert files, f"no Python consumer found under {_PY_CONSUMERS}"
    calls = sum(
        len(_ASSERT_RATCHET.findall(p.read_text(encoding="utf-8"))) for p in files
    )
    assert calls, (
        f"no `assert_ratchet(` call under {', '.join(_PY_CONSUMERS)} — the "
        f"Python-side consumer moved, and every floor it holds would read as "
        f"unenforced"
    )
    assert asserted_gates(), "the consumer scan found nothing"


def test_every_baseline_parses_as_a_floor():
    for path in sorted(BASELINES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data.get("count"), int), f"{path.name}: count is not an int"
        assert data["count"] >= 0, f"{path.name}: negative floor {data['count']}"
        assert data.get("note", "").strip(), (
            f"{path.name} carries no note. Every floor records what moved it and "
            f"why — that is the only account of the number a reviewer gets."
        )


def test_the_python_consumer_scan_is_precise_not_a_haystack():
    found = asserted_gates()
    assert len(found) < 100, (
        f"asserted_gates() returned {len(found)} names. That is haystack "
        f"territory again -- it should be the Rule vocabulary plus the literal "
        f"gate arguments, roughly one name per floor it holds."
    )
    coincidences = {
        "website",
        "qweb",
        "copy_data",
        "pre_init_hook",
        "AttributeError",
        "ValidationError",
    }
    admitted = coincidences & found
    assert not admitted, (
        f"{sorted(admitted)} are ordinary string literals under "
        f"{', '.join(_PY_CONSUMERS)}, not gate names. Admitting them means a "
        f"baseline file with any of those names reads as enforced."
    )
    assert not any(" " in name for name in found), (
        f"a message string reached the gate set: {sorted(n for n in found if ' ' in n)}"
    )
