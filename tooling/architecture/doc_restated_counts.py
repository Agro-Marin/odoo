from __future__ import annotations

import argparse
import ast
import functools
import re
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from itertools import starmap

import _ast_cache
import doc_measured
import field_hook_naming
import field_hook_purity
import naming_vocabulary
from _repo_root import find_odoo_root

_ast_cache.enable()

ROOT = find_odoo_root(Path(__file__).resolve())


class Figure(NamedTuple):
    name: str
    path: Path
    pattern: re.Pattern[str]
    measure: Callable[[], tuple[int, ...]]
    render: Callable[[tuple[int, ...]], tuple[str, ...]]
    tolerance: float = 0.0


class Row(NamedTuple):
    name: str
    section: str
    label: str
    measure: Callable[[], int]


class Table(NamedTuple):
    name: str
    path: Path
    rows: tuple[Row, ...]

    @property
    def start(self) -> str:
        return f".. {self.name}-table-start"

    @property
    def end(self) -> str:
        return f".. {self.name}-table-end"


class Drift(NamedTuple):
    name: str
    page: str
    detail: str

    def __str__(self) -> str:
        return f"{self.name} in {self.page}: {self.detail}"


def _plain(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(str(v) for v in values)


def _grouped(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{v:,}" for v in values)


def _padded(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{v:04d}" for v in values)


def _rounded(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(str(round(v / 10) * 10) for v in values)


def _tenths(values: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{v // 10}.{v % 10}" for v in values)


def _within(stated: str, measured: int, tolerance: float) -> bool:
    return abs(int(stated.replace(",", "")) - measured) <= max(
        2, round(measured * tolerance)
    )


def bundled_modules() -> tuple[int, ...]:
    return (
        sum(
            1
            for path in (ROOT / "addons").iterdir()
            if (path / "__manifest__.py").is_file()
        ),
    )


def _suite_methods(module: str) -> int:
    for tree in ("addons", "odoo/addons"):
        base = ROOT / tree / module / "tests"
        if base.is_dir():
            break
    else:
        raise FileNotFoundError(f"{module}/tests not found in either addon tree")
    return sum(
        sum(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test")
            for node in ast.walk(_ast_cache.parse_file(path, errors="ignore"))
        )
        for path in sorted(base.rglob("*.py"))
    )


def public_surface_specifiers() -> tuple[int, ...]:
    return (
        sum(
            1
            for line in PUBLIC_SURFACE_PIN.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
    )


def dispatch_names() -> tuple[int, ...]:
    def count(root: Path) -> int:
        total = 0
        for path in naming_vocabulary._python_files([root]):
            try:
                tree = _ast_cache.parse_file(path, errors="ignore")
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("getattr", "hasattr")
                    and len(node.args) >= 2
                ):
                    continue
                arg = node.args[1]
                if isinstance(arg, ast.JoinedStr) or (
                    isinstance(arg, ast.BinOp)
                    and isinstance(arg.op, (ast.Mod, ast.Add))
                    and isinstance(arg.left, ast.Constant)
                    and isinstance(arg.left.value, str)
                ):
                    total += 1
        return total

    whole = sum(count(ROOT / r) for r in naming_vocabulary.SCAN_ROOTS)
    return (count(ROOT / "odoo" / "addons" / "base"), whole)


def field_param_typing() -> tuple[int, ...]:
    tally = {("field_name", "str"): 0, ("field_name", "Field"): 0}
    tally |= {("field", "Field"): 0, ("field", "str"): 0}
    for path in naming_vocabulary._python_files(
        [ROOT / r for r in naming_vocabulary.SCAN_ROOTS]
    ):
        try:
            tree = _ast_cache.parse_file(path, errors="ignore")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                if arg.arg not in ("field", "field_name") or arg.annotation is None:
                    continue
                annotation = ast.unparse(arg.annotation)
                if "Field" in annotation:
                    kind = "Field"
                elif "str" in annotation:
                    kind = "str"
                else:
                    continue
                tally[(arg.arg, kind)] += 1
    return (
        tally[("field_name", "str")],
        tally[("field_name", "Field")],
        tally[("field", "Field")],
        tally[("field", "str")],
    )


def field_hook_exemptions() -> tuple[int, ...]:
    import dataclasses

    reported = {dataclasses.astuple(v) for v in field_hook_naming.measure()}
    original = field_hook_naming._DEDICATED_USES
    try:
        field_hook_naming._DEDICATED_USES = sys.maxsize
        uncapped = field_hook_naming.measure()
    finally:
        field_hook_naming._DEDICATED_USES = original
    return (sum(dataclasses.astuple(v) not in reported for v in uncapped),)


def duck_typed_hooks() -> tuple[int, ...]:
    counts = []
    for name in ("_get_report_values", "get_values", "set_values"):
        pattern = re.compile(rf"^\s*def {name}\(", re.MULTILINE)
        counts.append(
            sum(
                len(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
                for path in naming_vocabulary._python_files(
                    [ROOT / r for r in naming_vocabulary.SCAN_ROOTS]
                )
            )
        )
    return tuple(counts)


ARCHITECTURE = ROOT / "doc" / "architecture" / "ARCHITECTURE.md"


def constraint_name_spellings() -> tuple[int, ...]:
    uniq = unique = 0
    for path in naming_vocabulary._python_files(
        [ROOT / r for r in naming_vocabulary.SCAN_ROOTS]
    ):
        try:
            tree = _ast_cache.parse_file(path, errors="ignore")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not naming_vocabulary.is_model_class(node):
                continue
            for item in node.body:
                if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                    continue
                value = item.value
                if not (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr in ("Constraint", "Index", "UniqueIndex")
                ):
                    continue
                targets = (
                    item.targets if isinstance(item, ast.Assign) else [item.target]
                )
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    tail = target.id.rstrip("_").split("_")[-1]
                    uniq += tail == "uniq"
                    unique += tail == "unique"
    return (uniq, unique)


def constraint_po_references() -> tuple[int, ...]:
    reference = "constraint_ir_model_model_uniq"
    i18n = ROOT / "odoo" / "addons" / "base" / "i18n"
    catalogues = [*i18n.glob("*.po"), *i18n.glob("*.pot")]
    return (
        sum(
            reference in path.read_text(encoding="utf-8", errors="ignore")
            for path in catalogues
        ),
    )


def field_record_widgets() -> tuple[int, ...]:
    source = ROOT / "tooling" / "architecture" / "js_field_record_surface.py"
    block = doc_measured.extract(source.read_text(encoding="utf-8"))
    return (block["own_members"], block["widgets"])


def _migration_staging_rule() -> tuple[re.Pattern[str], tuple[str, ...]]:
    source = (ROOT / "odoo" / "modules" / "migration.py").read_text(encoding="utf-8")
    found: dict[str, ast.expr] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    found[target.id] = node.value
    try:
        compile_call, stages = found["VERSION_RE"], found["MIGRATION_STAGES"]
    except KeyError as exc:
        raise LookupError(
            f"modules/migration.py no longer defines {exc.args[0]}; the staging "
            f"rule moved and this figure is measuring the wrong thing"
        ) from None
    if not (isinstance(compile_call, ast.Call) and compile_call.args):
        raise LookupError("VERSION_RE is no longer a re.compile(...) call")
    flags = 0
    for keyword in compile_call.keywords:
        flags |= eval(  # noqa: S307 -- an ast node from a file this repo owns
            compile(ast.Expression(keyword.value), "<flags>", "eval"),
            {"re": re},
        )
    for extra in compile_call.args[1:]:
        flags |= eval(compile(ast.Expression(extra), "<flags>", "eval"), {"re": re})  # noqa: S307
    pattern = re.compile(ast.literal_eval(compile_call.args[0]), flags)
    return pattern, tuple(f"{s}-" for s in ast.literal_eval(stages))


def migration_scripts() -> tuple[int, ...]:
    version_re, stages = _migration_staging_rule()
    counts = {"migrations": 0, "upgrades": 0}
    unstaged = 0
    for tree in ("addons", "odoo/addons"):
        for addon in sorted((ROOT / tree).iterdir()):
            for kind in counts:
                for version in sorted((addon / kind).glob("*")):
                    if not version.is_dir() or version.name == "tests":
                        continue
                    if not version_re.match(version.name):
                        continue
                    for script in sorted(version.glob("*.py")):
                        counts[kind] += 1
                        unstaged += not script.name.startswith(stages)
    return (counts["migrations"], counts["upgrades"], unstaged)


GATES = ROOT / "doc" / "architecture" / "gates.md"
RISKS = ROOT / "doc" / "architecture" / "risks.md"
PUBLIC_SURFACE_PIN = ROOT / "tooling" / "architecture" / "public_surface_web.txt"
GUIDELINES = ROOT / "doc" / "coding_guidelines.rst"


def architecture_checkers() -> tuple[int, ...]:
    workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
        encoding="utf-8"
    )
    return (
        len(set(re.findall(r"python tooling/architecture/([\w.]+\.py)", workflow))),
    )


def py_function_length_budget() -> tuple[int, ...]:
    """The line budget py_function_length.py enforces, read off the script.

    3e2cea4c580 raised MAX_LINES from 80 to 90 on both trees and re-banked every
    floor it moved, but the guideline's gate table went on saying 80. It stayed
    wrong long enough that a session reading the guide computed a ratchet delta
    from the stale threshold and got the right answer by luck -- 99 over 90 and
    99 over 80 differ by ten, and the excess it needed happened not to depend on
    which. Restating a constant is the same debt as restating a count; this puts
    the constant under the same gate.
    """
    import py_function_length

    return (py_function_length.MAX_LINES,)


_MEASUREMENTS: tuple[Figure, ...] = (
    Figure(
        "py_function_length_budget",
        GUIDELINES,
        re.compile(r"core Python, \*\*excess lines\*\* over (\d+)"),
        py_function_length_budget,
        _plain,
    ),
    Figure(
        "architecture_checkers",
        RISKS,
        re.compile(r"(?:all|The)\s+(\d+)\s+(?:are structural|boundary checkers|and)"),
        architecture_checkers,
        _plain,
    ),
    Figure(
        "bundled_modules",
        GATES,
        re.compile(r"the\s+(\d[\d,]*)\s+bundled\s+modules"),
        bundled_modules,
        _plain,
    ),
    Figure(
        "test_orm_methods",
        GATES,
        re.compile(r"\*\*([\d,]+)\s+test\s+methods\*\*"),
        lambda: (_suite_methods("test_orm"),),
        _grouped,
    ),
    Figure(
        "test_read_group_methods",
        GATES,
        re.compile(r"`test_read_group`\s+\((\d[\d,]*)\s+test"),
        lambda: (_suite_methods("test_read_group"),),
        _plain,
    ),
    Figure(
        "test_access_rights_methods",
        GATES,
        re.compile(r"`test_access_rights`\s+\((\d[\d,]*),"),
        lambda: (_suite_methods("test_access_rights"),),
        _plain,
    ),
    Figure(
        "mail_suite_methods",
        GATES,
        re.compile(r"its\s+own\s+\*\*([\d,]+)\*\*-test\s+suite"),
        lambda: (_suite_methods("mail"),),
        _grouped,
    ),
    Figure(
        "field_record_widgets",
        GATES,
        re.compile(
            r"hands\s+all\s+\*\*(\d[\d,]*)\*\*\s+members\s+of\s+a\s+live\s+"
            r"`RelationalRecord`\s+to\s+\*\*(\d[\d,]*)\*\*\s+widgets"
        ),
        field_record_widgets,
        _plain,
    ),
    Figure(
        "hook_purity_gates",
        GATES,
        re.compile(r"hook\s+at\s+all\s+—\s+\*\*(\d[\d,]*)\*\*\s+are\s+also\s+called"),
        lambda: (len(field_hook_purity.measure()),),
        _plain,
    ),
    Figure(
        "migration_scripts",
        RISKS,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+scripts\s+in\s+`migrations/`\s+and\s+"
            r"\*\*(\d[\d,]*)\*\*\s+in\s+`upgrades/`[\s\S]{0,40}?\*\*(\d[\d,]*)\*\*\s+dropped"
        ),
        migration_scripts,
        _plain,
    ),
    Figure(
        "public_surface_specifiers",
        RISKS,
        re.compile(r"stands\s+at\s+\*\*(\d[\d,]*)\s+specifiers\*\*"),
        public_surface_specifiers,
        _plain,
    ),
    Figure(
        "get_share",
        GUIDELINES,
        re.compile(r"is\s+not\s+a\s+default\.\*\*\s+It\s+is\s+([\d.]+)\s*%"),
        lambda: (round(naming_vocabulary.census().get_share * 10),),
        _tenths,
    ),
    Figure(
        "prepare_split",
        GUIDELINES,
        re.compile(
            r"``_prepare_``:\s+(\d[\d,]*)\s+definitions\s+are[\s\S]{0,260}?"
            r"against\s+(\d[\d,]*)\s+already\s+spelled"
        ),
        lambda: (
            naming_vocabulary.census().get_payload,
            naming_vocabulary.census().prepare,
        ),
        _grouped,
    ),
    Figure(
        "bool_return_is_not_a_predicate",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+functions\s+in\s+this\s+repository\s*\n?\s*"
            r"are\s+annotated\s+``->\s+bool``\s+and\s+are\s+not\s+predicates,\s+against\s+"
            r"\*\*(\d[\d,]*)\*\*\s+that\s+are"
        ),
        lambda: (
            naming_vocabulary.census().bool_returning_others,
            naming_vocabulary.census().bool_returning_predicates,
        ),
        _grouped,
    ),
    Figure(
        "nested_backlog",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+open\s+with\s+a\s+verb\s+the\s+abolished\s+"
            r"table\s+reports\s+and\s+\*\*(\d[\d,]*)\*\*\s+with\s+a\s+reserved\s+one"
        ),
        lambda: (
            naming_vocabulary.census().nested_abolished,
            naming_vocabulary.census().nested_reserved,
        ),
        _grouped,
    ),
    Figure(
        "render_dispatch_prefix",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+definitions\s+begin\s+``_render_qweb_``;\s+"
            r"exactly\s+\*\*(\d[\d,]*)\*\*\s+are\s+keys"
        ),
        lambda: (
            naming_vocabulary.census().render_dispatch_prefixed,
            naming_vocabulary.census().render_dispatch_keys,
        ),
        _grouped,
    ),
    Figure(
        "assemble_verb_reach",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+model\s+methods\s+open\s+with\s+one\s+of\s+those\s+four\s+"
            r"verbs\s+and\s+the\s+ratchet\s+flags\s+\*\*(\d[\d,]*)\*\*"
        ),
        lambda: (
            naming_vocabulary.census().assemble_verb_methods,
            naming_vocabulary.census().assemble_verb_flagged,
        ),
        _grouped,
    ),
    Figure(
        "raise_noreturn",
        GUIDELINES,
        re.compile(
            r"never\s+returns\s+is\s+``NoReturn``;\s+\*\*(\d[\d,]*)\*\*\s+of\s+this\s*\n?\s*"
            r"repository's\s+\*\*(\d[\d,]*)\*\*\s+``_raise_\*``\s+model\s+methods"
        ),
        lambda: (
            naming_vocabulary.census().raise_noreturn,
            naming_vocabulary.census().raise_total,
        ),
        _grouped,
    ),
    Figure(
        "constraint_name_spellings",
        GUIDELINES,
        re.compile(
            r"the\s+tree\s+spells\s+that\s+tail\s+``_uniq``\s+\*\*(\d[\d,]*)\*\*\s+times\s+against\s*\n?\s*"
            r"``_unique``'s\s+\*\*(\d[\d,]*)\*\*"
        ),
        constraint_name_spellings,
        _grouped,
    ),
    Figure(
        "constraint_po_references",
        GUIDELINES,
        re.compile(
            r"was\s+named\s+in\s+\*\*(\d[\d,]*)\*\*\s+of\s+``base``'s\s*\n?\s*catalogues"
        ),
        constraint_po_references,
        _grouped,
    ),
    Figure(
        "dispatch_names",
        GUIDELINES,
        re.compile(
            r"``odoo/addons/base``\s+carries\s+(\d+(?:,\d{3})*)\s+of\s+this\s+"
            r"repository's\s+(\d+(?:,\d{3})*)"
        ),
        dispatch_names,
        _grouped,
    ),
    Figure(
        "field_param_typing",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+parameters\s*\n?\s*annotated\s+``field_name``\s+"
            r"are\s+``str``\s+and\s+\*\*(\d[\d,]*)\*\*\s+are\s+a\s+``Field``,\s+against\s*\n?\s*"
            r"``field``'s\s+\*\*(\d[\d,]*)\*\*\s+``Field``\s+and\s+\*\*(\d[\d,]*)\*\*\s+``str``"
        ),
        field_param_typing,
        _grouped,
    ),
)

FIGURES: tuple[Figure, ...] = tuple(
    figure._replace(measure=functools.cache(figure.measure)) for figure in _MEASUREMENTS
)
"""Every figure, with its measurement memoized for the life of the process.

`check()` costs ~40s, and 31s of that is recomputed on a second call: the
figures that dominate walk the tree themselves rather than through a cached
helper -- `field_hook_exemptions` alone is 12s, on the first call and on every
one after it. The gate calls `check()` once and exits, but the suite does not:
the figures are checked per document, and `test_architecture_doc_is_not_vacuous`
re-runs the whole doc suite twice more against a substituted page.

Memoizing is sound because the tree cannot change inside one process -- `main`
either checks or updates, and `update` rewrites the documents, never the code
being measured.
"""

_census = naming_vocabulary.census
_unbound = functools.cache(field_hook_naming.unbound_prefixes)
_inverse = functools.cache(field_hook_naming.inverse_spellings)
_duck_typed = functools.cache(duck_typed_hooks)
_exemptions = functools.cache(field_hook_exemptions)

_CENSUS_ROWS: tuple[Row, ...] = (
    Row(
        "hook_purity",
        "§2.4.1",
        "Field hooks the declaring model also calls on ``self``",
        lambda: len(field_hook_purity.measure()),
    ),
    Row(
        "field_hook_exemptions",
        "§2.4.1",
        "Field hooks exempt from the dedication test",
        lambda: _exemptions()[0],
    ),
    Row(
        "unbound_hook_names",
        "§2.4.1",
        "Names wearing a hook prefix with no binding",
        lambda: _unbound()[0],
    ),
    Row(
        "unbound_hook_definitions",
        "§2.4.1",
        "… definitions under those names",
        lambda: _unbound()[1],
    ),
    Row(
        "onchange_single",
        "§2.4.2",
        "Single-field ``@api.onchange`` hooks",
        lambda: _census().onchange_single,
    ),
    Row(
        "onchange_named_for_field",
        "§2.4.2",
        "… spelled ``_onchange_<field>``",
        lambda: _census().onchange_named_for_field,
    ),
    Row(
        "ondelete_hooks",
        "§2.4.2",
        "``@api.ondelete`` hooks",
        lambda: _census().ondelete_hooks,
    ),
    Row(
        "ondelete_canonical",
        "§2.4.2",
        "… spelled ``_unlink_except_*``",
        lambda: _census().ondelete_canonical,
    ),
    Row(
        "constrains_hooks",
        "§2.4.2",
        "``@api.constrains`` hooks",
        lambda: _census().constrains_hooks,
    ),
    Row(
        "constrains_canonical",
        "§2.4.2",
        "… spelled ``_check_*``",
        lambda: _census().constrains_canonical,
    ),
    Row(
        "constrains_unruled",
        "§2.4.2",
        "… with a first token carrying no rule",
        lambda: _census().constrains_unruled,
    ),
    Row(
        "constrains_single",
        "§2.4.2",
        "… binding exactly one field",
        lambda: _census().constrains_single,
    ),
    Row(
        "constrains_named_for_field",
        "§2.4.2",
        "… of those, spelled ``_check_<field>``",
        lambda: _census().constrains_named_for_field,
    ),
    Row(
        "constrains_multi_named_for_one",
        "§2.4.2",
        "Multi-field constraints named for one trigger",
        lambda: _census().constrains_multi_named_for_one,
    ),
    Row(
        "vocabulary_population",
        "§2.4.3",
        "Non-test methods declared on a model class",
        lambda: _census().methods,
    ),
    Row(
        "family_stems",
        "§2.4.3",
        "Stems spelled with two or more verbs of one family",
        lambda: _census().family_stems,
    ),
    Row(
        "identical_bodies",
        "§2.4.3",
        "Groups of methods sharing a byte-identical body",
        lambda: _census().identical_bodies,
    ),
    Row(
        "infix_abolished",
        "§2.4.4",
        "Model methods with an abolished verb behind a noun",
        lambda: _census().infix_abolished,
    ),
    Row(
        "fields_family_head_first",
        "§2.4.4",
        "``fields`` family: definitions spelled head-first",
        lambda: _census().fields_family_head_first,
    ),
    Row(
        "fields_family_names",
        "§2.4.4",
        "``fields`` family: distinct names spelled head-first",
        lambda: _census().fields_family_names,
    ),
    Row(
        "fields_family_tail_first",
        "§2.4.4",
        "``fields`` family: definitions spelled tail-first",
        lambda: _census().fields_family_tail_first,
    ),
    Row(
        "heads_searched",
        "§2.4.4",
        "Other collection heads the census searches",
        lambda: _census().heads_searched,
    ),
    Row(
        "heads_head_first",
        "§2.4.4",
        "Other heads: definitions spelled head-first",
        lambda: _census().heads_head_first,
    ),
    Row(
        "heads_tail_first",
        "§2.4.4",
        "Other heads: definitions spelled tail-first",
        lambda: _census().heads_tail_first,
    ),
    Row(
        "converter_idiom",
        "§2.4.5",
        "``X_to_Y`` converter definitions",
        lambda: _census().converter_idiom,
    ),
    Row(
        "converter_idiom_names",
        "§2.4.5",
        "… distinct names",
        lambda: _census().converter_idiom_names,
    ),
    Row("get_definitions", "§2.4.7", "``_get_*`` definitions", lambda: _census().get),
    Row(
        "assemble_verbs",
        "§2.4.7",
        "Abolished payload verbs, the four between them",
        lambda: _census().assemble_verbs,
    ),
    Row(
        "generate",
        "§2.4.7",
        "``_generate_*`` definitions",
        lambda: _census().generate,
    ),
    Row(
        "calculate",
        "§2.4.7",
        "``_calculate_*`` model methods",
        lambda: _census().calculate,
    ),
    Row("prepare", "§2.4.7", "``_prepare_*`` definitions", lambda: _census().prepare),
    Row(
        "prepare_writing",
        "§2.4.7",
        "… calling ``create()``, ``write()`` or ``unlink()``",
        lambda: _census().prepare_writing,
    ),
    Row("check", "§2.4.8", "``_check_*`` definitions", lambda: _census().check),
    Row(
        "validate",
        "§2.4.8",
        "``_validate_*`` definitions",
        lambda: _census().validate,
    ),
    Row(
        "validate_synonyms",
        "§2.4.8",
        "``_verify_``, ``_ensure_`` and ``_control_`` together",
        lambda: _census().validate_synonyms,
    ),
    Row(
        "exec_verbs",
        "§2.4.9",
        "Execution-verb definitions, ``_do_`` through ``_handle_``",
        lambda: _census().exec_verbs,
    ),
    Row(
        "raise_total",
        "§2.4.10",
        "``_raise_*`` model methods",
        lambda: _census().raise_total,
    ),
    Row(
        "raise_unconditional",
        "§2.4.10",
        "… raising unconditionally",
        lambda: _census().raise_unconditional,
    ),
    Row("find_total", "§2.4.11", "``_find_*`` methods", lambda: _census().find_total),
    Row(
        "find_orm_read",
        "§2.4.11",
        "… performing an ORM read",
        lambda: _census().find_orm_read,
    ),
    Row(
        "find_other",
        "§2.4.11",
        "… doing something else entirely",
        lambda: _census().find_other,
    ),
    Row(
        "find_or_create",
        "§2.4.11",
        "``_find_or_create_*`` methods",
        lambda: _census().find_or_create,
    ),
    Row(
        "get_or_create",
        "§2.4.11",
        "``_get_or_create_*`` methods",
        lambda: _census().get_or_create,
    ),
    Row(
        "resolve_total",
        "§2.4.11",
        "``_resolve_*`` definitions",
        lambda: _census().resolve_total,
    ),
    Row("set_", "§2.4.12", "``_set_*`` definitions", lambda: _census().set_),
    Row("update", "§2.4.12", "``_update_*`` definitions", lambda: _census().update),
    Row(
        "inverse_canonical",
        "§2.4.12",
        "``inverse=`` targets spelled ``_inverse_<field>``",
        lambda: _inverse()[0],
    ),
    Row(
        "inverse_setter",
        "§2.4.12",
        "``inverse=`` targets spelled ``_set_*``",
        lambda: _inverse()[1],
    ),
    Row("sync", "§2.4.12", "``_sync_*`` definitions", lambda: _census().sync),
    Row(
        "synchronize",
        "§2.4.12",
        "``_synchronize_*`` definitions",
        lambda: _census().synchronize,
    ),
    Row("post", "§2.4.12", "``_post_*`` definitions", lambda: _census().post),
    Row(
        "module_level_helpers",
        "§2.4.13",
        "Module-level functions under ``models/`` and ``wizard/``",
        lambda: _census().module_level_helpers,
    ),
    Row(
        "helper_class_methods",
        "§2.4.13",
        "Methods on plain classes in model files",
        lambda: _census().helper_class_methods,
    ),
    Row(
        "helper_classes",
        "§2.4.13",
        "… such classes",
        lambda: _census().helper_classes,
    ),
    Row(
        "nested_helpers",
        "§2.4.13",
        "Functions nested inside model methods",
        lambda: _census().nested_helpers,
    ),
    Row(
        "stored_code_names",
        "§2.4.14",
        "Private method names reached from stored Python",
        lambda: _census().stored_code_names,
    ),
    Row(
        "stored_code_blocks",
        "§2.4.14",
        "… code blocks reaching them",
        lambda: _census().stored_code_blocks,
    ),
    Row(
        "stored_code_files",
        "§2.4.14",
        "… shipped data files holding those blocks",
        lambda: _census().stored_code_files,
    ),
    Row(
        "report_values_implementers",
        "§2.4.14",
        "Classes implementing ``_get_report_values``",
        lambda: _duck_typed()[0],
    ),
    Row(
        "get_values_implementers",
        "§2.4.14",
        "… ``get_values``",
        lambda: _duck_typed()[1],
    ),
    Row(
        "set_values_implementers",
        "§2.4.14",
        "… ``set_values``",
        lambda: _duck_typed()[2],
    ),
)

CENSUS = Table(
    "census",
    GUIDELINES,
    tuple(row._replace(measure=functools.cache(row.measure)) for row in _CENSUS_ROWS),
)

TABLES: tuple[Table, ...] = (CENSUS,)

ITEMS: tuple[Figure | Table, ...] = (*FIGURES, *TABLES)

_HEADER = ("Section", "Population", "Count")
_ROW = re.compile(r"^(§\S+)\s{2,}(.+?)\s{2,}([\d,]+)$", re.MULTILINE)


def _match(figure: Figure) -> re.Match[str]:
    match = figure.pattern.search(figure.path.read_text(encoding="utf-8"))
    if match is None:
        raise LookupError(
            f"{figure.name}: no sentence in {figure.path.name} matches "
            f"{figure.pattern.pattern!r}. The figure is no longer checked; "
            f"restore the sentence or drop the figure from FIGURES."
        )
    return match


def _block(table: Table) -> re.Match[str]:
    pattern = re.compile(
        rf"^{re.escape(table.start)}$.*?^{re.escape(table.end)}$",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(table.path.read_text(encoding="utf-8"))
    if match is None:
        raise LookupError(
            f"{table.name}: {table.path.name} holds no block between "
            f"{table.start!r} and {table.end!r}. The table is no longer checked; "
            f"restore the markers or drop the table from TABLES."
        )
    return match


def render_table(table: Table, values: dict[str, int]) -> str:
    cells = [(row.section, row.label, f"{values[row.name]:,}") for row in table.rows]
    widths = [max(len(cell[i]) for cell in (_HEADER, *cells)) for i in range(3)]
    rule = "  ".join("=" * width for width in widths)

    def line(section: str, label: str, count: str) -> str:
        return f"{section:<{widths[0]}}  {label:<{widths[1]}}  {count:>{widths[2]}}"

    return "\n".join(
        (
            table.start,
            "",
            rule,
            line(*_HEADER),
            rule,
            *starmap(line, cells),
            rule,
            "",
            table.end,
        )
    )


def _stated_rows(block: str) -> dict[tuple[str, str], str]:
    return {(section, label): count for section, label, count in _ROW.findall(block)}


def figures_for(
    directory: Path, figures: Sequence[Figure | Table] = FIGURES
) -> tuple[Figure | Table, ...]:
    return tuple(f for f in figures if directory in f.path.parents)


def _figure_drifts(figure: Figure) -> list[Drift]:
    stated = _match(figure).groups()
    measured = figure.measure()
    if figure.tolerance:
        fresh = all(
            _within(s, m, figure.tolerance)
            for s, m in zip(stated, measured, strict=True)
        )
    else:
        fresh = tuple(stated) == figure.render(measured)
    if fresh:
        return []
    return [
        Drift(
            figure.name,
            figure.path.name,
            f"states {', '.join(stated)}, measured "
            f"{', '.join(figure.render(measured))}",
        )
    ]


def _table_drifts(table: Table) -> list[Drift]:
    block = _block(table).group(0)
    stated = _stated_rows(block)
    measured = {row.name: row.measure() for row in table.rows}
    drifts = []
    for row in table.rows:
        rendered = f"{measured[row.name]:,}"
        if (row.section, row.label) not in stated:
            drifts.append(
                Drift(
                    f"{table.name}.{row.name}",
                    table.path.name,
                    f"no row labelled {row.label!r}; run --update {table.name}",
                )
            )
        elif stated[row.section, row.label] != rendered:
            drifts.append(
                Drift(
                    f"{table.name}.{row.name}",
                    table.path.name,
                    f"states {stated[row.section, row.label]}, measured {rendered}",
                )
            )
    if not drifts and block != render_table(table, measured):
        drifts.append(
            Drift(
                table.name,
                table.path.name,
                f"the block is not in its generated form; run --update {table.name}",
            )
        )
    return drifts


def drifts(items: Sequence[Figure | Table] = ITEMS) -> list[Drift]:
    found: list[Drift] = []
    for item in items:
        if isinstance(item, Table):
            found.extend(_table_drifts(item))
        else:
            found.extend(_figure_drifts(item))
    return found


def check(items: Sequence[Figure | Table] = ITEMS) -> list[str]:
    return [str(drift) for drift in drifts(items)]


def check_by_page(items: Sequence[Figure | Table] = ITEMS) -> dict[str, list[str]]:
    by_page: dict[str, list[str]] = {}
    for drift in drifts(items):
        by_page.setdefault(drift.page, []).append(f"{drift.name}: {drift.detail}")
    return by_page


def _update_figure(figure: Figure) -> list[str]:
    raw = figure.path.read_text(encoding="utf-8")
    match = _match(figure)
    measured = figure.measure()
    if figure.tolerance and all(
        _within(s, m, figure.tolerance)
        for s, m in zip(match.groups(), measured, strict=True)
    ):
        return []
    expected = figure.render(measured)
    text = raw
    for index, value in reversed(list(enumerate(expected, start=1))):
        start, end = match.span(index)
        text = text[:start] + value + text[end:]
    if text == raw:
        return []
    figure.path.write_text(text, encoding="utf-8")
    return [f"{figure.name}: {', '.join(expected)}"]


def _update_table(table: Table, rows: Collection[str] | None) -> list[str]:
    raw = table.path.read_text(encoding="utf-8")
    match = _block(table)
    stated = _stated_rows(match.group(0))
    values: dict[str, int] = {}
    changed = []
    for row in table.rows:
        kept = stated.get((row.section, row.label))
        if rows is None or row.name in rows or kept is None:
            values[row.name] = row.measure()
            if kept != f"{values[row.name]:,}":
                changed.append(f"{table.name}.{row.name}: {values[row.name]:,}")
        else:
            values[row.name] = int(kept.replace(",", ""))
    rendered = render_table(table, values)
    if rendered == match.group(0):
        return []
    table.path.write_text(
        raw[: match.start()] + rendered + raw[match.end() :], encoding="utf-8"
    )
    return changed or [f"{table.name}: block rewritten in its generated form"]


def update(
    items: Sequence[Figure | Table] = ITEMS, rows: Collection[str] | None = None
) -> list[str]:
    changed: list[str] = []
    for item in items:
        if isinstance(item, Table):
            changed.extend(_update_table(item, rows))
        else:
            changed.extend(_update_figure(item))
    return changed


def select(
    names: Sequence[str], items: Sequence[Figure | Table] = ITEMS
) -> tuple[list[Figure | Table], frozenset[str] | None]:
    by_name = {item.name: item for item in items}
    row_tables = {
        row.name: table
        for table in items
        if isinstance(table, Table)
        for row in table.rows
    }
    chosen: list[Figure | Table] = []
    rows: set[str] = set()
    whole_table = False
    for name in names:
        if name in by_name:
            item = by_name[name]
            whole_table = whole_table or isinstance(item, Table)
        elif name in row_tables:
            item = row_tables[name]
            rows.add(name)
        else:
            known = sorted((*by_name, *row_tables))
            raise LookupError(
                f"{name!r} names no figure, table or table row; known names: "
                + ", ".join(known)
            )
        if item not in chosen:
            chosen.append(item)
    return chosen, (None if whole_table or not rows else frozenset(rows))


def main(
    argv: Sequence[str] | None = None, items: Sequence[Figure | Table] = ITEMS
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--update", nargs="*", metavar="NAME")
    args = parser.parse_args(argv)
    if args.update is not None:
        try:
            chosen, rows = select(args.update, items) if args.update else (items, None)
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 2
        changed = update(chosen, rows)
        print("\n".join(changed) if changed else "already fresh")
        return 0
    by_page = check_by_page(items)
    for page, problems in by_page.items():
        print(page)
        for problem in problems:
            print(f"  {problem}")
    return 1 if (by_page and args.check) else 0


if __name__ == "__main__":
    raise SystemExit(main())
