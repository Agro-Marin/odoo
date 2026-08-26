from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _ast_cache
import doc_measured
import field_hook_naming
import field_hook_purity
import naming_vocabulary
from _repo_root import find_odoo_root

ADR = "0041"

_ast_cache.enable()

ROOT = find_odoo_root(Path(__file__).resolve())


class Figure(NamedTuple):
    name: str
    path: Path
    pattern: re.Pattern[str]
    measure: Callable[[], tuple[int, ...]]
    render: Callable[[tuple[int, ...]], tuple[str, ...]]
    tolerance: float = 0.0


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


def metadata_call_sites() -> tuple[int, ...]:
    counts = []
    for attr in ("_name", "_fields"):
        pattern = re.compile(rf"self\.{attr}\b")
        counts.append(
            sum(
                len(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
                for tree in ("odoo/addons", "addons")
                for path in (ROOT / tree).rglob("*.py")
            )
        )
    return tuple(counts)


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


def adr_range() -> tuple[int, ...]:
    numbers = sorted(
        int(path.name[:4])
        for path in (ROOT / "doc" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")
    )
    return (numbers[0], numbers[-1])


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
METADATA = ROOT / "odoo" / "orm" / "models" / "mixins" / "_metadata.py"
GUIDELINES = ROOT / "doc" / "coding_guidelines.rst"

FIGURES: tuple[Figure, ...] = (
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
        "metadata_call_sites",
        METADATA,
        re.compile(
            r"``self\._name``\s+has\s+about\s+(\d[\d,]*)\s+sites\s+and\s+"
            r"``self\._fields``\s+about\s+(\d[\d,]*)"
        ),
        metadata_call_sites,
        _rounded,
        tolerance=0.05,
    ),
    Figure(
        "public_surface_specifiers",
        RISKS,
        re.compile(r"stands\s+at\s+\*\*(\d[\d,]*)\s+specifiers\*\*"),
        public_surface_specifiers,
        _plain,
    ),
    Figure(
        "adr_range",
        ARCHITECTURE,
        re.compile(r"architecture\s+decisions,\s+(\d{4})–(\d{4})"),
        adr_range,
        _padded,
    ),
    Figure(
        "vocabulary_population",
        GUIDELINES,
        re.compile(r"population\s+is\s+the\s+(\d[\d,]*)\s+non-test\s+methods"),
        lambda: (naming_vocabulary.census().methods,),
        _grouped,
    ),
    Figure(
        "vocabulary_drift",
        GUIDELINES,
        re.compile(
            r"many\s+ways:\s+(\d[\d,]*)\s+stems\s+are\s+written[\s\S]{0,90}?"
            r"one\s+semantic\s+family,\s+and\s+(\d[\d,]*)\s+groups"
        ),
        lambda: (
            naming_vocabulary.census().family_stems,
            naming_vocabulary.census().identical_bodies,
        ),
        _grouped,
    ),
    Figure(
        "get_definitions",
        GUIDELINES,
        re.compile(r"is\s+not\s+a\s+default\.\*\*\s+At\s+(\d[\d,]*)\s+definitions"),
        lambda: (naming_vocabulary.census().get,),
        _grouped,
    ),
    Figure(
        "get_share",
        GUIDELINES,
        re.compile(r"definitions\s+it\s+is\s+([\d.]+)\s*%"),
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
        "ungoverned_populations",
        GUIDELINES,
        re.compile(
            r"\*\*module\s+level\*\*\s+--\s+\*\*(\d[\d,]*)\*\*\s+of\s+them[\s\S]{0,160}?"
            r"of\s+which\s+there\s+are\s+\*\*(\d[\d,]*)\*\*\s*\n?\s*across\s+\*\*(\d[\d,]*)\*\*\s+classes"
        ),
        lambda: (
            naming_vocabulary.census().module_level_helpers,
            naming_vocabulary.census().helper_class_methods,
            naming_vocabulary.census().helper_classes,
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
        "find_total",
        GUIDELINES,
        re.compile(
            r"the\s+\*\*(\d[\d,]*)\*\*\s+``_find_\*``\s+methods\s+that\s*\n?\s*remain"
        ),
        lambda: (naming_vocabulary.census().find_total,),
        _grouped,
    ),
    Figure(
        "find_orm_read",
        GUIDELINES,
        re.compile(r"\*\*(\d[\d,]*)\*\*\s+perform\s+an\s+ORM\s+read"),
        lambda: (naming_vocabulary.census().find_orm_read,),
        _grouped,
    ),
    Figure(
        "or_create_conversion",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+methods\s+here\s+still\s+spell\s+it\s+``_find_``,\s+against\s*\n?\s*"
            r"\*\*(\d[\d,]*)\*\*\s+spelling\s+it\s+``_get_``"
        ),
        lambda: (
            naming_vocabulary.census().find_or_create,
            naming_vocabulary.census().get_or_create,
        ),
        _grouped,
    ),
    Figure(
        "find_other",
        GUIDELINES,
        re.compile(r"\*\*(\d[\d,]*)\*\*\s+do\s+something\s+else\s+entirely"),
        lambda: (naming_vocabulary.census().find_other,),
        _grouped,
    ),
    Figure(
        "resolve_total",
        GUIDELINES,
        re.compile(
            r"at\s+\*\*(\d[\d,]*)\*\*\s+definitions\s+here\s+against\s+the\s+size\s+of\s+"
            r"``_find_``\s+--\s+\*\*(\d[\d,]*)\*\*"
        ),
        lambda: (
            naming_vocabulary.census().resolve_total,
            naming_vocabulary.census().find_total,
        ),
        _grouped,
    ),
    Figure(
        "prepare_writing",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+of\s+this\s+repository's\s+\*\*(\d[\d,]*)\*\*\s+"
            r"``_prepare_\*``\s+definitions"
        ),
        lambda: (
            naming_vocabulary.census().prepare_writing,
            naming_vocabulary.census().prepare,
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
        "raise_unconditional",
        GUIDELINES,
        re.compile(
            r"unconditional\s+raiser,\s+\*\*(\d[\d,]*)\*\*\s+of\s+those\s+\*\*(\d[\d,]*)\*\*"
        ),
        lambda: (
            naming_vocabulary.census().raise_unconditional,
            naming_vocabulary.census().raise_total,
        ),
        _grouped,
    ),
    Figure(
        "converter_idiom",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+definitions\s+under\s+\*\*(\d[\d,]*)\*\*\s+names\s+are\s+spelled"
        ),
        lambda: (
            naming_vocabulary.census().converter_idiom,
            naming_vocabulary.census().converter_idiom_names,
        ),
        _grouped,
    ),
    Figure(
        "stored_code_binding",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+distinct\s+private\s+method\s+names\s*\n?\s*"
            r"are\s+reached\s+that\s+way\s+from\s+\*\*(\d[\d,]*)\*\*\s+code\s+blocks\s+in\s+"
            r"\*\*(\d[\d,]*)\*\*\s+shipped\s+data\s+files"
        ),
        lambda: (
            naming_vocabulary.census().stored_code_names,
            naming_vocabulary.census().stored_code_blocks,
            naming_vocabulary.census().stored_code_files,
        ),
        _grouped,
    ),
    Figure(
        "sync_family",
        GUIDELINES,
        re.compile(
            r"had\s+never\s+named:\s+\*\*(\d[\d,]*)\*\*\s+"
            r"definitions\s+spell\s+it\s+``_sync_\*``\s+and\s+\*\*(\d[\d,]*)\*\*\s+"
            r"spell\s+it\s+``_synchronize_\*``,\s+against\s+"
            r"``_update_\*``'s\s+\*\*(\d[\d,]*)\*\*"
        ),
        lambda: (
            naming_vocabulary.census().sync,
            naming_vocabulary.census().synchronize,
            naming_vocabulary.census().update,
        ),
        _grouped,
    ),
    Figure(
        "collection_head_order",
        GUIDELINES,
        re.compile(
            r"across\s+\*\*(\d[\d,]*)\*\*\s+of\s+them\s+this\s+repository\s+spells\s+"
            r"\*\*(\d[\d,]*)\*\*\s*\n?\s*definitions\s+head-first\s+against\s+"
            r"\*\*(\d[\d,]*)\*\*\s+the\s+other\s+way"
        ),
        lambda: (
            naming_vocabulary.census().heads_searched,
            naming_vocabulary.census().heads_head_first,
            naming_vocabulary.census().heads_tail_first,
        ),
        _grouped,
    ),
    Figure(
        "fields_family_order",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+definitions\s+under\s+\*\*(\d[\d,]*)\*\*\s+names\s+in\s+this\s*\n?\s*"
            r"repository\s+spell\s+it\s*\n?\s*head-first\s+and\s+\*\*(\d[\d,]*)\*\*\s+spell\s+it\s+the\s+other\s+way"
        ),
        lambda: (
            naming_vocabulary.census().fields_family_head_first,
            naming_vocabulary.census().fields_family_names,
            naming_vocabulary.census().fields_family_tail_first,
        ),
        _grouped,
    ),
    Figure(
        "ondelete_family",
        GUIDELINES,
        re.compile(
            r"opinion,\s+over\s+\*\*(\d[\d,]*)\*\*\s*\n?\s*methods\.[\s\S]{0,900}?"
            r"at\s+\*\*(\d[\d,]*)\*\*\s+of\s+the"
        ),
        lambda: (
            naming_vocabulary.census().ondelete_hooks,
            naming_vocabulary.census().ondelete_canonical,
        ),
        _grouped,
    ),
    Figure(
        "onchange_field_naming",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+of\s+\*\*(\d[\d,]*)\*\*\s+single-field\s*\n?\s*"
            r"onchange\s+hooks\s+are\s+spelled\s+for\s+their\s+field"
        ),
        lambda: (
            naming_vocabulary.census().onchange_named_for_field,
            naming_vocabulary.census().onchange_single,
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
        "constrains_family",
        GUIDELINES,
        re.compile(
            r"fourth\s+and\s+largest,\s+at\s+\*\*(\d[\d,]*)\*\*\s+hooks\."
            r"[\s\S]{0,120}?\*\*(\d[\d,]*)\*\*\s+already\s+carry"
            r"[\s\S]{0,400}?That\s+leaves\s+\*\*(\d[\d,]*)\*\*\s+spelled\s+with"
        ),
        lambda: (
            naming_vocabulary.census().constrains_hooks,
            naming_vocabulary.census().constrains_canonical,
            naming_vocabulary.census().constrains_unruled,
        ),
        _grouped,
    ),
    Figure(
        "constrains_field_naming",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+bind\s+exactly\s+one\s+field\s+and\s+only\s+"
            r"\*\*(\d[\d,]*)\*\*\s+are\s+``_check_<field>``"
            r"[\s\S]{0,400}?\*\*(\d[\d,]*)\*\*\s+multi-field\s+"
            r"constraints\s+are\s+named\s+for\s+exactly\s+one"
        ),
        lambda: (
            naming_vocabulary.census().constrains_single,
            naming_vocabulary.census().constrains_named_for_field,
            naming_vocabulary.census().constrains_multi_named_for_one,
        ),
        _grouped,
    ),
    Figure(
        "infix_abolished",
        GUIDELINES,
        re.compile(
            r"Backlog:\s+\*\*(\d[\d,]*)\*\*\s+model\s+methods\s+put\s+an\s+abolished\s+verb"
        ),
        lambda: (naming_vocabulary.census().infix_abolished,),
        _grouped,
    ),
    Figure(
        "generate_family",
        GUIDELINES,
        re.compile(
            r"come\s+to\s+\*\*(\d[\d,]*)\*\*\s+definitions\s+between\s+them;\s+"
            r"``_generate_``\s+alone\s+is\s+\*\*(\d[\d,]*)\*\*"
        ),
        lambda: (
            naming_vocabulary.census().assemble_verbs,
            naming_vocabulary.census().generate,
        ),
        _grouped,
    ),
    Figure(
        "validation_family",
        GUIDELINES,
        re.compile(
            r"``_check_\*``\s+\((\d[\d,]*)\s+definitions\)[\s\S]{0,110}?"
            r"``_validate_``\s+\((\d[\d,]*)\)[\s\S]{0,90}?"
            r"\((\d[\d,]*)\s+together\)"
        ),
        lambda: (
            naming_vocabulary.census().check,
            naming_vocabulary.census().validate,
            naming_vocabulary.census().validate_synonyms,
        ),
        _grouped,
    ),
    Figure(
        "exec_verbs",
        GUIDELINES,
        re.compile(r"``_handle_``\s+\((\d[\d,]*)\s+definitions\)"),
        lambda: (naming_vocabulary.census().exec_verbs,),
        _grouped,
    ),
    Figure(
        "set_update_split",
        GUIDELINES,
        re.compile(
            r"``_set_\*``\s+\((\d[\d,]*)\s+definitions\)\s+and\s+"
            r"``_update_\*``\s+\((\d[\d,]*)\)"
        ),
        lambda: (naming_vocabulary.census().set_, naming_vocabulary.census().update),
        _grouped,
    ),
    Figure(
        "hook_purity",
        GUIDELINES,
        re.compile(
            r"``\[ratchet\s+hookpurity\]``\.\s+(\d[\d,]*)\s+are\s+not\s+hooks\s+at\s+all"
        ),
        lambda: (len(field_hook_purity.measure()),),
        _grouped,
    ),
    Figure(
        "unbound_hook_prefixes",
        GUIDELINES,
        re.compile(
            r"\*\*(\d[\d,]*)\*\*\s+names,\s+at\s+\*\*(\d[\d,]*)\*\*\s+definitions"
        ),
        field_hook_naming.unbound_prefixes,
        _grouped,
    ),
    Figure(
        "inverse_spellings",
        GUIDELINES,
        re.compile(r"(\d[\d,]*)\s+against\s+(\d[\d,]*)\s+now\s+that\s+the\s+count"),
        field_hook_naming.inverse_spellings,
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
        "duck_typed_hooks",
        GUIDELINES,
        re.compile(
            r"(\d[\d,]*)\s+classes\s+in\s+this\s+repository\s+implement\s+it"
            r"[\s\S]{0,180}?at\s+(\d[\d,]*)\s+and\s+(\d[\d,]*)\."
        ),
        duck_typed_hooks,
        _grouped,
    ),
    Figure(
        "field_hook_exemptions",
        GUIDELINES,
        re.compile(r"\*\*(\d[\d,]*)\*\*\s+hook\s+is\s+exempt\s+today"),
        field_hook_exemptions,
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
    Figure(
        "post_overload",
        GUIDELINES,
        re.compile(
            r"is\s+overloaded\*\*\s+``\[review\]``\.\s+(\d[\d,]*)\s+definitions"
        ),
        lambda: (naming_vocabulary.census().post,),
        _grouped,
    ),
)


def _match(figure: Figure) -> re.Match[str]:
    match = figure.pattern.search(figure.path.read_text(encoding="utf-8"))
    if match is None:
        raise LookupError(
            f"{figure.name}: no sentence in {figure.path.name} matches "
            f"{figure.pattern.pattern!r}. The figure is no longer checked; "
            f"restore the sentence or drop the figure from FIGURES."
        )
    return match


def check() -> list[str]:
    problems = []
    for figure in FIGURES:
        stated = _match(figure).groups()
        measured = figure.measure()
        if figure.tolerance:
            fresh = all(
                _within(s, m, figure.tolerance)
                for s, m in zip(stated, measured, strict=True)
            )
        else:
            fresh = tuple(stated) == figure.render(measured)
        if not fresh:
            problems.append(
                f"{figure.name} in {figure.path.name}: states "
                f"{', '.join(stated)}, measured "
                f"{', '.join(str(m) for m in measured)}"
            )
    return problems


def update() -> list[str]:
    changed = []
    for figure in FIGURES:
        raw = figure.path.read_text(encoding="utf-8")
        match = _match(figure)
        measured = figure.measure()
        if figure.tolerance and all(
            _within(s, m, figure.tolerance)
            for s, m in zip(match.groups(), measured, strict=True)
        ):
            continue
        expected = figure.render(measured)
        text = raw
        for index, value in reversed(list(enumerate(expected, start=1))):
            start, end = match.span(index)
            text = text[:start] + value + text[end:]
        if text != raw:
            figure.path.write_text(text, encoding="utf-8")
            changed.append(f"{figure.name}: {', '.join(expected)}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    if args.update:
        changed = update()
        print("\n".join(changed) if changed else "already fresh")
        return 0
    problems = check()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
