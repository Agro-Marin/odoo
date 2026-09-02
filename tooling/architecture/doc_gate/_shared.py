from __future__ import annotations

import ast
from pathlib import Path

import _ast_cache
import _doc_measures

ROOT = _doc_measures.ROOT

_ARCH_DOCS = ROOT / "doc" / "architecture"
DOC_PATH = _ARCH_DOCS / "ARCHITECTURE.md"
DOC_PATHS = (
    DOC_PATH,
    _ARCH_DOCS / "module.md",
    _ARCH_DOCS / "runtime.md",
    _ARCH_DOCS / "data.md",
    _ARCH_DOCS / "deployment.md",
    _ARCH_DOCS / "scenarios.md",
    _ARCH_DOCS / "gates.md",
    _ARCH_DOCS / "risks.md",
    _ARCH_DOCS / "qualities.md",
)
_on_disk = {p.name for p in _ARCH_DOCS.glob("*.md")}
_listed = {p.name for p in DOC_PATHS}
if _on_disk != _listed:
    raise AssertionError(
        f"DOC_PATHS and doc/architecture/ disagree — missing from the suite: "
        f"{sorted(_on_disk - _listed)}; listed but absent from disk: "
        f"{sorted(_listed - _on_disk)}. This suite pins the whole set, so "
        f"either is a broken gate rather than a lighter one."
    )


def read_docs() -> str:

    return "\n\n".join(p.read_text(encoding="utf-8") for p in DOC_PATHS)


DOC = read_docs()

DOC_FLAT = " ".join(DOC.split())


def _class_bases(source: Path, class_name: str) -> list[str]:

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [b.id for b in node.bases if isinstance(b, ast.Name)]
    raise AssertionError(f"class {class_name} not found in {source}")


def _imported_modules(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


_number_word = _doc_measures.number_word
_ordinal_word = _doc_measures.ordinal_word
NUMBER_WORDS = _doc_measures.NUMBER_WORDS
NUMBER_WORD_BY_VALUE = _doc_measures.NUMBER_WORD_BY_VALUE


def _rule_table_gates(tests: Path) -> set[str]:
    source = tests / "_rules.py"
    if not source.is_file():
        return set()
    tree = _ast_cache.parse_file(source)
    gates: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if called != "Rule" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            gates.add("lint_" + first.value.replace("-", "_"))
    return gates
