import functools
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest

from . import lint_case
from ._rules import Finding
from ._xml_identity import PARSER
from ._xml_rules import RULES, Context, DataFile

_logger = logging.getLogger(__name__)

DATA_ROOTS = frozenset({"odoo", "data", "openerp"})


@dataclass(frozen=True, slots=True)
class _Module:
    name: str
    root: str
    listed: frozenset[str]


@functools.cache
def _modules() -> tuple[_Module, ...]:
    out = []
    for manifest in Manifest.get_all_addon_manifests():
        root = str(Path(manifest.path))
        listed = frozenset(
            os.path.normpath(str(Path(root, rel)))
            for key in ("data", "demo")
            for rel in manifest.declared.get(key) or ()
        )
        out.append(_Module(manifest.name, root, listed))
    return tuple(sorted(out, key=lambda m: -len(m.root)))


def _module_of(path: str) -> _Module | None:
    for module in _modules():
        if path.startswith(module.root + os.sep):
            return module
    return None


@functools.cache
def _python_sources_by_module() -> dict[str, str]:
    sources: dict[str, list[str]] = {}
    for path in lint_case.module_file_paths():
        if not path.endswith(".py") or "/static/" in path:
            continue
        module = _module_of(path)
        if module is None:
            continue
        try:
            sources.setdefault(module.name, []).append(
                Path(path).read_text(encoding="utf-8")
            )
        except OSError, UnicodeDecodeError:
            continue
    return {name: "\n".join(chunks) for name, chunks in sources.items()}


def _mentioned_in_python(module: _Module, path: str) -> bool:
    relative = os.path.relpath(path, module.root)
    source = _python_sources_by_module().get(module.name, "")
    return relative in source or Path(relative).name in source


@functools.cache
def data_files() -> tuple[DataFile, ...]:
    out = []
    for path in lint_case.core_data_files():
        module = _module_of(str(path))
        if module is None:
            continue
        try:
            tree = etree.parse(str(path), PARSER)
        except etree.XMLSyntaxError:
            continue
        root = tree.getroot()
        if root.tag not in DATA_ROOTS:
            continue
        resolved = os.path.normpath(str(path))
        out.append(
            DataFile(
                path=str(path),
                module=module.name,
                root=root,
                listed=resolved in module.listed,
                loaded_from_python=_mentioned_in_python(module, resolved),
            )
        )
    return tuple(out)


@functools.cache
def context() -> Context:
    return Context(
        declared_models=lint_case.declared_models(),
        known_modules=frozenset(module.name for module in _modules()),
    )


@functools.cache
def findings() -> dict[str, list[Finding]]:
    files = data_files()
    ctx = context()
    by_rule: dict[str, list[Finding]] = {rule.name: [] for rule in RULES}
    for data_file in files:
        for rule in RULES:
            for lineno, message in rule.check(data_file, ctx):
                by_rule[rule.name].append(
                    Finding(data_file.path, lineno, rule.name, message)
                )
    _logger.info(
        "scanned %s XML data files, %s finding(s) across %s rule(s)",
        len(files),
        sum(map(len, by_rule.values())),
        sum(1 for found in by_rule.values() if found),
    )
    return by_rule
