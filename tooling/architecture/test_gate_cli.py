from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_measured

HERE = Path(__file__).resolve().parent


def gate_modules() -> list[Path]:
    return [
        path
        for path in sorted(HERE.glob("*.py"))
        if not path.name.startswith(("test_", "_"))
        and "def main(" in path.read_text(encoding="utf-8")
    ]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_the_discovery_finds_the_gates():
    found = gate_modules()
    assert len(found) > 40, (
        f"only {len(found)} gates found under {HERE} — the discovery rule is "
        f"broken, and every check here would pass by finding nothing"
    )


def _parser_keywords(tree: ast.Module) -> list[ast.keyword]:
    return [
        keyword
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "ArgumentParser"
        for keyword in node.keywords
    ]


@pytest.mark.parametrize("gate", [p.name for p in gate_modules()])
def test_a_gate_that_passes_its_docstring_to_argparse_has_one(gate):
    path = HERE / gate
    tree = _tree(path)
    passes_doc = any(
        keyword.arg == "description"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "__doc__"
        for keyword in _parser_keywords(tree)
    )
    if not passes_doc:
        return
    docstring = ast.get_docstring(tree)
    assert docstring, (
        f"{gate} passes `description=__doc__` and has no module docstring, so "
        f"`--help` renders no description at all. Write one, or drop the "
        f"keyword."
    )
    assert not docstring.lstrip().startswith(doc_measured.MARKER), (
        f"{gate} passes `description=__doc__` and its docstring is the "
        f"{doc_measured.MARKER!r} block, which `doc_measured` parses out of the "
        f"file. argparse then prints that measurement as the gate's help text. "
        f"Drop the keyword; the block is data and stays where it is."
    )


def _declared_flags(tree: ast.Module) -> set[str]:
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _reads(path: Path, tree: ast.Module, attr: str) -> bool:
    if any(
        isinstance(node, ast.Attribute)
        and node.attr == attr
        and isinstance(node.value, ast.Name)
        and node.value.id == "args"
        for node in ast.walk(tree)
    ):
        return True
    return "_count_gate.run(" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("gate", [p.name for p in gate_modules()])
def test_a_declared_verdict_flag_is_a_flag_the_gate_reads(gate):
    path = HERE / gate
    tree = _tree(path)
    declared = _declared_flags(tree)
    for flag, attr in (("--check", "check"), ("--count", "count")):
        if flag in declared:
            assert _reads(path, tree, attr), (
                f"{gate} declares {flag} and never reads args.{attr}, so the "
                f"flag changes nothing and its help line is false"
            )


def _compiled_constants(tree: ast.Module) -> list[str]:
    return [
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "attr", None) == "compile"
    ]


@pytest.mark.parametrize("gate", [p.name for p in gate_modules()])
def test_a_gate_declares_no_pattern_it_never_uses(gate):
    source = (HERE / gate).read_text(encoding="utf-8")
    tree = ast.parse(source)
    unused = [
        name
        for name in _compiled_constants(tree)
        if sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == name
        )
        < 2
    ]
    assert not unused, (
        f"{gate} compiles {unused} and never reads it. Delete the pattern, or "
        f"wire it to the rule it was written for."
    )


class _Found:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


def _run_count_gate(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    import _count_gate

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _count_gate.run(
            argv,
            script="probe.py",
            gate="probe",
            headline="probe over {where}",
            unit="thing(s)",
            default_addon="core",
            everything="addons",
            siblings=(),
            governed=("core", "addons"),
            addon_src=lambda addon: HERE,
            measure=lambda src: [_Found("a"), _Found("b"), _Found("c")],
            root_name="odoo",
        )
    return rc, out.getvalue()


def test_count_file_writes_the_count_beside_the_report(tmp_path):
    target = tmp_path / "probe.count"
    rc, report = _run_count_gate(["--count-file", str(target)])
    assert rc == 0
    assert target.read_text(encoding="utf-8") == "3\n"
    assert "3 thing(s)   <- the ratcheted number" in report
    _, counted = _run_count_gate(["--count"])
    assert counted.strip() == target.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("script", ["py_function_length", "py_class_length"])
def test_the_own_cli_gates_write_the_same_count_file(script, tmp_path):
    import contextlib
    import io

    module = importlib.import_module(script)
    target = tmp_path / f"{script}.count"
    with contextlib.redirect_stdout(io.StringIO()):
        assert module.main(["--addon", "tooling", "--count-file", str(target)]) == 0
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert module.main(["--addon", "tooling", "--count"]) == 0
    assert target.read_text(encoding="utf-8") == out.getvalue()
