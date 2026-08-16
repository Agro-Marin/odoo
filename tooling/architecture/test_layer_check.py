import ast
import re
from collections import Counter
from pathlib import Path

import layer_check as lc


def _violations_for(module: str, src: str) -> list[lc.Violation]:

    collector = lc._ImportCollector(module=module, is_init=False)
    collector.visit(ast.parse(src))
    return lc.violations_for(module, collector.found, f"{module.replace('.', '/')}.py")


def test_resolve_relative_regular_module():
    col = lc._ImportCollector(module="odoo.orm.fields.base", is_init=False)
    assert col._resolve_relative("models", 2) == "odoo.orm.models"
    assert col._resolve_relative(None, 1) == "odoo.orm.fields"


def test_resolve_relative_init_module():
    col = lc._ImportCollector(module="odoo.libs", is_init=True)
    assert col._resolve_relative("collections", 1) == "odoo.libs.collections"
    assert col._resolve_relative("esbuild", 1) == "odoo.libs.esbuild"


def _collect(src: str, *, module="pkg.mod", is_init=False):
    col = lc._ImportCollector(module=module, is_init=is_init)
    col.visit(ast.parse(src))
    return [target for target, _ in col.found]


def test_type_checking_block_is_skipped():
    src = (
        "from typing import TYPE_CHECKING\n"
        "from a.b import C\n"
        "if TYPE_CHECKING:\n"
        "    from x.y import Z\n"
    )
    targets = _collect(src)
    assert "a.b" in targets
    assert "x.y" not in targets


def test_typing_dot_type_checking_is_skipped():
    src = "import typing\nif typing.TYPE_CHECKING:\n    from x.y import Z\n"
    assert "x.y" not in _collect(src)


def test_else_branch_of_type_checking_is_kept():
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from a import X\n"
        "else:\n"
        "    from b import Y\n"
    )
    targets = _collect(src)
    assert "a" not in targets
    assert "b" in targets


def test_function_local_import_is_captured():
    src = "def f():\n    from a.b import C\n    return C\n"
    assert "a.b" in _collect(src)


def test_from_relative_pkg_import_submodule_is_resolved():
    targets = _collect("from .. import models as _m\n", module="odoo.orm.fields.base")
    assert "odoo.orm.models" in targets


def test_from_odoo_import_shim_submodule_is_resolved():
    targets = _collect("from odoo import models\n", module="odoo.orm.fields.base")
    assert "odoo.models" in targets


def test_plain_symbol_import_is_not_overcounted():
    targets = _collect("from odoo.tools import SQL\n", module="odoo.orm.fields.base")
    assert "odoo.tools" in targets


def _violates(module: str, src: str) -> bool:
    col = lc._ImportCollector(module=module, is_init=False)
    col.visit(ast.parse(src))
    for c in lc.CONTRACTS:
        if not lc._matches(module, c.source):
            continue
        for target, _ in col.found:
            if (
                lc._matches(target, c.forbidden)
                and not lc._matches(target, c.allow)
                and target not in c.allow_exact
                and not lc._matches(target, c.source)
            ):
                return True
    return False


def test_layer1_from_pkg_import_models_is_a_violation():
    assert _violates("odoo.orm.fields.base", "from .. import models as _m\nx = _m\n")


def test_layer1_import_of_models_shim_is_a_violation():
    assert _violates("odoo.orm.fields.base", "from odoo import models\n")
    assert _violates("odoo.orm.fields.base", "from odoo.api import Environment\n")


def test_layer0_import_of_higher_shim_is_a_violation():
    assert _violates("odoo.orm.primitives", "from odoo.fields import Field\n")


def test_recordset_seam_is_under_enforcement():
    sources = {p for c in lc.CONTRACTS for p in c.source}
    assert "odoo.orm._recordset" in sources
    assert _violates("odoo.orm._recordset", "from .models import BaseModel\n")


def test_legitimate_layer1_imports_do_not_violate():
    assert not _violates(
        "odoo.orm.fields.base", "from ..primitives import COLLECTION_TYPES\n"
    )
    assert not _violates(
        "odoo.orm.fields.base", "from .._recordset import is_recordset\n"
    )
    assert not _violates("odoo.orm.fields.base", "from odoo.tools import SQL\n")


def test_addon_importing_orm_internal_is_a_violation():
    assert _violates(
        "odoo.addons.base.models.res_users",
        "from odoo.orm._typing import ValuesType\n",
    )
    assert _violates(
        "odoo.addons.base.models.ir_model_data",
        "from odoo.orm.registration import add_field\n",
    )


def test_addon_importing_facades_is_clean():
    for src in (
        "from odoo.api import ValuesType, DomainType\n",
        "from odoo.fields import Field, Many2one, COLLECTION_TYPES\n",
        "from odoo.models import BaseModel, add_field, pop_field\n",
        "from odoo import api, fields, models\n",
        "from odoo.tools import SQL\n",
    ):
        assert not _violates("odoo.addons.base.models.res_users", src), src


def test_addon_type_checking_import_of_orm_is_exempt():
    col = lc._ImportCollector(module="odoo.addons.base.models.res_users", is_init=False)
    col.visit(
        ast.parse(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from odoo.orm.fields import Field\n"
        )
    )
    assert "odoo.orm.fields" not in [t for t, _ in col.found]


def _core_contract():
    return next(c for c in lc.CONTRACTS if c.name == "core-does-not-depend-on-addons")


def test_core_importing_an_addon_module_is_a_violation():
    assert _violates(
        "odoo.orm.models.mixins.unlink",
        "from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG\n",
    )
    assert _violates(
        "odoo.tools.formatting",
        "from odoo.addons.base.models.res_lang import format_number\n",
    )


def test_importing_the_addons_namespace_is_allowed():
    for src in (
        "import odoo.addons\n",
        "from odoo.addons import __path__ as p\n",
    ):
        assert not _violates("odoo.modules.module", src), src


def test_core_importing_the_relocated_definitions_is_clean():
    for src in (
        "from odoo.orm.primitives import MODULE_UNINSTALL_FLAG\n",
        "from odoo.libs.locale import format_number\n",
    ):
        assert not _violates("odoo.tools.formatting", src), src


def test_addon_code_is_not_subject_to_this_contract():
    assert not _violates(
        "odoo.addons.base.models.ir_model_data",
        "from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG\n",
    )


def test_core_type_checking_import_of_an_addon_is_exempt():

    col = lc._ImportCollector(module="odoo.tools.locale_utils", is_init=False)
    col.visit(
        ast.parse(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from odoo.addons.base.models.res_lang import LangData\n"
        )
    )
    assert "odoo.addons.base.models.res_lang" not in [t for t, _ in col.found]


def test_core_source_covers_every_core_package():

    pkg_root = lc.ROOT / "odoo"
    on_disk = {
        p.name
        for p in pkg_root.iterdir()
        if p.is_dir()
        and (p / "__init__.py").exists()
        and p.name not in {"addons", "__pycache__"}
    }
    covered = {
        s.split(".", 1)[1] for s in _core_contract().source if s.startswith("odoo.")
    }
    uncovered = on_disk - covered - lc.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT
    assert uncovered == set(), (
        f"core packages neither covered by core-does-not-depend-on-addons nor "
        f"listed in CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT: {sorted(uncovered)}"
    )


def test_core_source_covers_every_core_module():

    pkg_root = lc.ROOT / "odoo"
    on_disk = {p.stem for p in pkg_root.glob("*.py") if p.name != "__init__.py"}
    covered = {
        s.split(".", 1)[1] for s in _core_contract().source if s.startswith("odoo.")
    }
    uncovered = on_disk - covered
    assert uncovered == set(), (
        f"top-level core modules not covered by core-does-not-depend-on-addons: "
        f"{sorted(uncovered)}"
    )


def test_core_package_init_is_scanned_and_judged():

    init = lc.ROOT / "odoo" / "__init__.py"
    assert init in lc.iter_source_files(), (
        "odoo/__init__.py is not in the walk -- the package root every "
        "`import odoo` executes is being read by nothing."
    )
    judged = lc.violations_for(
        lc.module_name_for(init),
        [("odoo.addons.base.models.ir_cron", 1)],
        "odoo/__init__.py",
    )
    assert [v.contract for v in judged] == ["core-does-not-depend-on-addons"], (
        "odoo/__init__.py is scanned but matches no contract's source, so the "
        "walk reads it and then has nothing to say about it."
    )


def test_source_exact_does_not_drag_in_a_subtree():

    exact = lc._source_exact_files()
    assert exact == [lc.ROOT / "odoo" / "__init__.py"]
    files = lc.iter_source_files()
    assert len(files) == len(set(files)), "iter_source_files returned a duplicate"


def test_top_level_core_modules_are_actually_scanned():

    scanned = {p.name for p in lc.iter_source_files() if p.parent == lc.ROOT / "odoo"}
    for name in ("init.py", "logutils.py", "exceptions.py", "release.py"):
        assert name in scanned, f"odoo/{name} is still not scanned by layer_check"


_ORM_MODULES_EXEMPT_FROM_LAYERING = frozenset({"model_test_env", "__init__"})


def test_every_top_level_orm_module_sits_in_a_layering_contract():

    layering = {
        c.name
        for c in lc.CONTRACTS
        if "layer" in c.name or "seam" in c.name or "below-runtime" in c.name
    }
    uncovered = []
    for path in sorted((lc.ROOT / "odoo" / "orm").glob("*.py")):
        if path.stem in _ORM_MODULES_EXEMPT_FROM_LAYERING:
            continue
        module = f"odoo.orm.{path.stem}"
        if not any(
            lc._matches(module, tuple(c.source))
            for c in lc.CONTRACTS
            if c.name in layering
        ):
            uncovered.append(path.name)
    assert uncovered == [], (
        "top-level orm modules in no layering contract (add them to one, or to "
        f"_ORM_MODULES_EXEMPT_FROM_LAYERING with a reason): {uncovered}"
    )


def test_the_orm_layering_exemptions_are_real_modules():
    for stem in _ORM_MODULES_EXEMPT_FROM_LAYERING:
        assert (lc.ROOT / "odoo" / "orm" / f"{stem}.py").is_file(), stem


def test_facades_do_not_reexport_private_framework_names():

    facades = (
        ("odoo", "api"),
        ("odoo", "fields"),
        ("odoo", "models"),
        ("odoo", "modules", "registry"),
    )
    offenders: list[str] = []
    for parts in facades:
        init = lc.ROOT.joinpath(*parts, "__init__.py")
        if not init.is_file():
            continue
        tree = ast.parse(init.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(getattr(t, "id", "") == "__all__" for t in node.targets):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            for element in node.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    if element.value.startswith("_"):
                        offenders.append(f"{'.'.join(parts)}.{element.value}")

    assert offenders == [], (
        "facades re-export private names, which addon code can then import "
        f"without tripping facade-boundary: {sorted(offenders)}"
    )


def test_the_addon_contract_exemptions_are_real_packages():
    pkg_root = lc.ROOT / "odoo"
    for name in lc.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT:
        assert (pkg_root / name / "__init__.py").exists(), (
            f"{name} is exempted but is not a core package"
        )


def test_the_cron_exception_is_pinned_not_silent():
    pinned = {k.imports for k in lc.KNOWN_VIOLATIONS}
    assert "odoo.addons.base.models.ir_cron" in pinned
    assert "odoo.addons.base.models.ir_job" in pinned
    for k in lc.KNOWN_VIOLATIONS:
        assert len(k.reason) > 80, f"{k.imports} pinned without a real rationale"


def test_facade_boundary_scans_the_addon_tree():
    assert any("addons" in p.parts for p in lc.iter_source_files())


def test_importlib_import_module_literal_is_collected():
    targets = _collect(
        "import importlib\nm = importlib.import_module('odoo.orm.runtime')\n",
        module="odoo.orm.fields.base",
    )
    assert "odoo.orm.runtime" in targets


def test_dunder_import_literal_is_collected():
    targets = _collect(
        "m = __import__('odoo.orm.models')\n", module="odoo.orm.fields.base"
    )
    assert "odoo.orm.models" in targets


def test_bare_import_module_literal_is_collected():
    targets = _collect(
        "from importlib import import_module\nm = import_module('odoo.orm.runtime')\n",
        module="odoo.orm.fields.base",
    )
    assert "odoo.orm.runtime" in targets


def test_layer1_dynamic_import_of_runtime_is_a_violation():
    assert _violates(
        "odoo.orm.fields.base",
        "import importlib\nm = importlib.import_module('odoo.orm.runtime')\n",
    )


def test_non_literal_dynamic_import_is_not_collected():
    targets = _collect(
        "import importlib\nname = 'odoo.orm.runtime'\nm = importlib.import_module(name)\n",
        module="odoo.orm.fields.base",
    )
    assert "odoo.orm.runtime" not in targets


def test_dynamic_import_under_type_checking_is_skipped():
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import importlib\n"
        "    importlib.import_module('odoo.orm.runtime')\n"
    )
    assert "odoo.orm.runtime" not in _collect(src, module="odoo.orm.fields.base")


def test_matches_prefix_on_dot_boundary():
    assert lc._matches("odoo.orm.models.base", ("odoo.orm.models",))
    assert lc._matches("odoo.orm.models", ("odoo.orm.models",))
    assert not lc._matches("odoo.orm.modelsx", ("odoo.orm.models",))


def test_is_test_file():
    assert lc._is_test_file(Path("odoo/orm/components/tests/test_core.py"))
    assert lc._is_test_file(Path("pkg/conftest.py"))
    assert not lc._is_test_file(Path("odoo/orm/fields/base.py"))


def test_the_walk_visits_every_file_exactly_once():

    files = lc.iter_source_files()
    duplicated = [p for p, n in Counter(files).items() if n > 1]
    assert duplicated == [], f"{len(duplicated)} file(s) walked more than once"


def test_nested_roots_are_collapsed_but_disjoint_ones_are_kept():
    root = lc.ROOT
    collapsed = lc._collapse_nested(
        [root / "odoo" / "orm", root / "odoo" / "orm" / "fields", root / "odoo" / "db"]
    )
    assert root / "odoo" / "orm" / "fields" not in collapsed
    assert root / "odoo" / "orm" in collapsed
    assert root / "odoo" / "db" in collapsed


def test_a_module_shaped_root_under_a_directory_root_is_collapsed():
    root = lc.ROOT
    collapsed = lc._collapse_nested(
        [root / "odoo" / "http", root / "odoo" / "http" / "openapi"]
    )
    assert collapsed == [root / "odoo" / "http"]


def test_one_import_statement_is_one_violation():

    source = "from odoo.addons.base.models import ir_cron\n"
    violations = _violations_for("odoo.service.probe", source)
    assert len(violations) == 1, [v.imports for v in violations]


def test_the_submodule_record_is_kept_when_it_is_the_one_that_violates():

    violations = _violations_for("odoo.orm.fields.probe", "from odoo import models\n")
    assert [v.imports for v in violations] == ["odoo.models"]


def test_two_distinct_forbidden_names_on_one_line_are_two_violations():
    violations = _violations_for(
        "odoo.orm.fields.probe", "from odoo.orm import models, runtime\n"
    )
    assert sorted(v.imports for v in violations) == [
        "odoo.orm.models",
        "odoo.orm.runtime",
    ]


def test_framework_core_has_no_new_violations():
    new, _known = lc.check()
    assert new == [], "new layering violations:\n" + "\n".join(
        f"  {v.path}:{v.lineno}  {v.module} -> {v.imports}  [{v.contract}]" for v in new
    )


def test_core_has_no_tolerated_exceptions():

    unexpected = [
        k
        for k in lc.KNOWN_VIOLATIONS
        if not k.imports.startswith("odoo.addons.base.models.ir_")
    ]
    assert unexpected == [], (
        f"a contract other than core-does-not-depend-on-addons acquired a "
        f"tolerated exception: {unexpected}"
    )


ORIGINAL_EIGHT = frozenset(
    {
        "libs-is-dependency-free",
        "db-is-orm-agnostic",
        "orm-components-are-pure-python",
        "orm-layer0-is-foundational",
        "orm-layer1-below-models-and-runtime",
        "orm-models-below-runtime",
        "orm-seams-stay-below-models-and-runtime",
        "facade-boundary",
    }
)


def test_the_eight_original_contracts_are_clean_at_zero():
    assert len(ORIGINAL_EIGHT) == 8
    defined = {c.name for c in lc.CONTRACTS}
    assert defined >= ORIGINAL_EIGHT, (
        f"original contract removed: {ORIGINAL_EIGHT - defined}"
    )
    core_sources = {
        s
        for c in lc.CONTRACTS
        if c.name == "core-does-not-depend-on-addons"
        for s in c.source
    }
    for k in lc.KNOWN_VIOLATIONS:
        assert any(k.module.startswith(s) for s in core_sources), (
            f"{k.module} is pinned but is not a source of the addon contract"
        )


def test_db_resilience_importing_connectivity_is_a_violation():
    assert _violates("odoo.db.breaker", "from .pool import ConnectionPool\n")
    assert _violates("odoo.db.metrics", "from odoo.db.cursor import Cursor\n")


def test_db_connectivity_importing_resilience_is_clean():
    assert not _violates("odoo.db.pool", "from .budget import ConnectionBudget\n")
    assert not _violates("odoo.db.cursor", "from .metrics import CursorMetrics\n")


def test_db_foundation_is_importable_from_both_tiers():
    assert not _violates("odoo.db.metrics", "from .errors import CURSOR_LOGGER_NAME\n")
    assert not _violates("odoo.db.cursor", "from .errors import CURSOR_LOGGER_NAME\n")


def test_http_features_importing_serving_is_a_violation():
    assert _violates("odoo.http.openapi", "from .routing import Route\n")
    assert _violates(
        "odoo.http._params", "from odoo.http.request_class import Request\n"
    )


def test_http_serving_importing_features_is_clean():
    assert not _violates(
        "odoo.http._serve", "from .constants import SESSION_LIFETIME\n"
    )
    assert not _violates("odoo.http.helpers", "from .core import request\n")


def test_http_features_type_checking_import_of_serving_is_exempt():
    src = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .session import Session\n"
    assert not _violates("odoo.http._protocols", src)


def test_every_db_and_http_module_is_in_a_tier():

    repo_root = lc.ROOT
    for pkg, contract_name in (
        ("db", "db-resilience-below-connectivity"),
        ("http", "http-features-below-serving"),
    ):
        contract = next(c for c in lc.CONTRACTS if c.name == contract_name)
        tiered = {
            name.rsplit(".", 1)[1] for name in (*contract.source, *contract.forbidden)
        }
        if pkg == "db":
            tiered |= {"errors", "dsn", "utils"}
        on_disk = {
            p.stem
            for p in (repo_root / "odoo" / pkg).glob("*.py")
            if p.stem != "__init__"
        }
        assert on_disk == tiered, (
            f"odoo/{pkg}/ modules not assigned to a tier of {contract_name}: "
            f"{sorted(on_disk - tiered)}; listed but absent from disk: "
            f"{sorted(tiered - on_disk)}"
        )


def test_every_contract_has_a_source_and_rationale():
    for c in lc.CONTRACTS:
        assert c.source, f"{c.name} has no source"
        assert c.forbidden, f"{c.name} forbids nothing"
        assert c.rationale.strip(), f"{c.name} has no rationale"


UNRECORDED_CONTRACTS = frozenset(
    {
        "tools-does-not-reach-the-orm-runtime",
        "orm-helpers-and-registration-stay-below-runtime",
        "core-does-not-depend-on-addons",
        "db-resilience-below-connectivity",
        "http-features-below-serving",
        "orm-below-the-serving-tier",
    }
)


def test_every_contract_names_an_adr_that_exists():
    adr_dir = lc.ROOT / "doc" / "adr"
    numbers = {p.name[:4] for p in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")}
    for c in lc.CONTRACTS:
        if c.adr == lc.UNRECORDED:
            continue
        assert c.adr in numbers, (
            f"{c.name} names ADR-{c.adr}, which is not in doc/adr/. A contract "
            f"cites the record that argues for it; if the record moved, follow it."
        )


def test_every_contract_names_an_accepted_adr():

    adr_dir = lc.ROOT / "doc" / "adr"
    status_re = re.compile(r"^-\s*\*\*Status:\*\*\s*(\S+)", re.MULTILINE)
    for c in lc.CONTRACTS:
        if c.adr == lc.UNRECORDED:
            continue
        (path,) = adr_dir.glob(f"{c.adr}-*.md")
        match = status_re.search(path.read_text(encoding="utf-8"))
        kind = match.group(1) if match else "<none>"
        assert kind == "Accepted", (
            f"{c.name} cites ADR-{c.adr}, whose status is {kind}. A contract "
            f"enforces a decision that has landed; cite an Accepted record, or "
            f"set adr=UNRECORDED until this one is."
        )


def test_the_unrecorded_contracts_are_pinned_and_shrinking():
    unrecorded = {c.name for c in lc.CONTRACTS if c.adr == lc.UNRECORDED}
    new = unrecorded - UNRECORDED_CONTRACTS
    assert not new, (
        f"contract(s) with no ADR: {sorted(new)}. A boundary worth failing CI "
        f"over is worth a decision record — write one and set adr=, or add the "
        f"name to UNRECORDED_CONTRACTS with your reason for deferring."
    )
    written_up = UNRECORDED_CONTRACTS - unrecorded
    assert not written_up, (
        f"{sorted(written_up)} now name an ADR. Good — remove them from "
        f"UNRECORDED_CONTRACTS so the count cannot drift back up."
    )


def test_core_test_framework_modules_are_not_test_files():
    for name in ("common.py", "http.py", "case.py", "loader.py", "browser.py"):
        path = lc.ROOT / "odoo" / "tests" / name
        assert not lc._is_test_file(path), f"odoo/tests/{name} is framework source"


def test_the_test_frameworks_own_tests_are_still_test_files():
    for name in ("test_cursor.py", "test_module_operations.py"):
        path = lc.ROOT / "odoo" / "tests" / name
        assert lc._is_test_file(path), f"odoo/tests/{name} IS a test"


def test_ordinary_test_packages_are_still_dropped():
    for rel in (
        ("odoo", "orm", "tests", "test_fields.py"),
        ("odoo", "libs", "tests", "test_misc.py"),
        ("odoo", "orm", "tests", "conftest.py"),
    ):
        path = lc.ROOT.joinpath(*rel)
        assert lc._is_test_file(path), f"{'/'.join(rel)} is a test file"


def test_revoking_the_tests_exemption_actually_enforces():

    contracts = tuple(
        lc.Contract(**{**c.__dict__, "source": c.source + ("odoo.tests",)})
        if c.name == "core-does-not-depend-on-addons"
        else c
        for c in lc.CONTRACTS
    )
    original = lc.CONTRACTS
    try:
        lc.CONTRACTS = contracts
        new, known = lc.check()
    finally:
        lc.CONTRACTS = original
    found = {
        (v.path, v.imports) for v in new + known if v.module.startswith("odoo.tests")
    }
    assert found, "revoking the exemption detected nothing — the fix has regressed"
    files = {path for path, _ in found}
    assert files == {"odoo/tests/common.py", "odoo/tests/http.py"}, files


def test_tests_exemption_is_recorded_and_documented():
    assert frozenset({"tests"}) == lc.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT
    core = next(c for c in lc.CONTRACTS if c.name == "core-does-not-depend-on-addons")
    assert "odoo.tests" not in core.source, (
        "odoo.tests is exempt via CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT; "
        "listing it in source too would make the exemption ambiguous"
    )


def test_the_gate_refuses_a_tree_it_cannot_find(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(lc, "ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc:
        lc.main(["--check"])
    assert exc.value.code == 2
