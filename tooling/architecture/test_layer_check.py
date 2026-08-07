"""Tests for the architecture layering checker.

Stdlib + pytest only — no Odoo imports — so this runs in the same database-free
way as the checker itself. Run with:

    pytest tooling/architecture/test_layer_check.py
"""

import ast
from collections import Counter
from pathlib import Path

import layer_check as lc  # sys.path set by conftest.py


def _violations_for(module: str, src: str) -> list[lc.Violation]:
    """Contract violations a source string makes, as ``module``.

    Goes through the real :func:`layer_check.violations_for`, so the dedupe and
    the matching rules under test are the ones the gate runs.
    """
    collector = lc._ImportCollector(module=module, is_init=False)
    collector.visit(ast.parse(src))
    return lc.violations_for(module, collector.found, f"{module.replace('.', '/')}.py")


# --- relative-import resolution (the subtle part: __init__ vs regular module) ---


def test_resolve_relative_regular_module():
    col = lc._ImportCollector(module="odoo.orm.fields.base", is_init=False)
    # `from ..models import X` inside orm/fields/base.py -> odoo.orm.models
    assert col._resolve_relative("models", 2) == "odoo.orm.models"
    # `from . import x` inside a regular module -> its package
    assert col._resolve_relative(None, 1) == "odoo.orm.fields"


def test_resolve_relative_init_module():
    # In a package __init__.py, `from .x import y` stays within the package.
    col = lc._ImportCollector(module="odoo.libs", is_init=True)
    assert col._resolve_relative("collections", 1) == "odoo.libs.collections"
    assert col._resolve_relative("esbuild", 1) == "odoo.libs.esbuild"


# --- TYPE_CHECKING blocks must be skipped (the crux of the design) ---


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
    assert "x.y" not in targets  # under TYPE_CHECKING -> ignored


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
    # Deferred imports still execute at runtime and must be counted.
    src = "def f():\n    from a.b import C\n    return C\n"
    assert "a.b" in _collect(src)


# --- blind-spot regression: `from <pkg> import <submodule>` must be resolved ---
# Without this, `from .. import models` resolved only to the *package* (odoo.orm)
# and the real Layer-2 target (odoo.orm.models) was invisible. See ADR-0001.


def test_from_relative_pkg_import_submodule_is_resolved():
    # `from .. import models` inside orm/fields/base.py binds odoo.orm.models.
    targets = _collect("from .. import models as _m\n", module="odoo.orm.fields.base")
    assert "odoo.orm.models" in targets


def test_from_odoo_import_shim_submodule_is_resolved():
    # `from odoo import models` pulls in the Layer-2 shim package odoo.models.
    targets = _collect("from odoo import models\n", module="odoo.orm.fields.base")
    assert "odoo.models" in targets


def test_plain_symbol_import_is_not_overcounted():
    # `from odoo.tools import SQL` must NOT manufacture a forbidden package
    # target — SQL is a symbol, odoo.tools.SQL matches no forbidden prefix.
    targets = _collect("from odoo.tools import SQL\n", module="odoo.orm.fields.base")
    assert "odoo.tools" in targets  # the package dependency is still recorded


# --- end-to-end: the evasion forms now produce real violations ---


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
    # The ADR-0001 injection seam was previously outside every contract source.
    sources = {p for c in lc.CONTRACTS for p in c.source}
    assert "odoo.orm._recordset" in sources
    assert _violates("odoo.orm._recordset", "from .models import BaseModel\n")


def test_legitimate_layer1_imports_do_not_violate():
    # Sanity: real, allowed imports in a Layer-1 file must stay clean.
    assert not _violates(
        "odoo.orm.fields.base", "from ..primitives import COLLECTION_TYPES\n"
    )
    assert not _violates(
        "odoo.orm.fields.base", "from .._recordset import is_recordset\n"
    )
    assert not _violates("odoo.orm.fields.base", "from odoo.tools import SQL\n")


# --- facade-boundary: addons reach the ORM only through the public façades ---


def test_addon_importing_orm_internal_is_a_violation():
    # The whole point of ADR-0008: addon code must not reach into odoo.orm.*.
    assert _violates(
        "odoo.addons.base.models.res_users",
        "from odoo.orm._typing import ValuesType\n",
    )
    assert _violates(
        "odoo.addons.base.models.ir_model_data",
        "from odoo.orm.registration import add_field\n",
    )


def test_addon_importing_facades_is_clean():
    # The façades (not under odoo.orm) are exactly how addons should import.
    for src in (
        "from odoo.api import ValuesType, DomainType\n",
        "from odoo.fields import Field, Many2one, COLLECTION_TYPES\n",
        "from odoo.models import BaseModel, add_field, pop_field\n",
        "from odoo import api, fields, models\n",
        "from odoo.tools import SQL\n",
    ):
        assert not _violates("odoo.addons.base.models.res_users", src), src


def test_addon_type_checking_import_of_orm_is_exempt():
    # TYPE_CHECKING imports never execute, so they create no runtime coupling —
    # consistent with every other contract.
    col = lc._ImportCollector(module="odoo.addons.base.models.res_users", is_init=False)
    col.visit(
        ast.parse(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from odoo.orm.fields import Field\n"
        )
    )
    assert "odoo.orm.fields" not in [t for t, _ in col.found]


# --- core-does-not-depend-on-addons (the mirror of facade-boundary) ---


def _core_contract():
    return next(c for c in lc.CONTRACTS if c.name == "core-does-not-depend-on-addons")


def test_core_importing_an_addon_module_is_a_violation():
    # The two inversions this contract was written for, before they were fixed.
    assert _violates(
        "odoo.orm.models.mixins.unlink",
        "from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG\n",
    )
    assert _violates(
        "odoo.tools.formatting",
        "from odoo.addons.base.models.res_lang import format_number\n",
    )


def test_importing_the_addons_namespace_is_allowed():
    """``__path__`` discovery imports the namespace package, never addon code."""
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
    """An addon importing another addon is normal and must stay unflagged."""
    assert not _violates(
        "odoo.addons.base.models.ir_model_data",
        "from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG\n",
    )


def test_core_type_checking_import_of_an_addon_is_exempt():
    """Consistent with every other contract: TYPE_CHECKING never executes.

    ``tools/locale_utils.py`` types ``get_lang`` as returning ``LangData``, which
    is a real addon class. Narrowing that to a protocol would misdescribe the
    return, and the import costs nothing at runtime.
    """
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
    """The source list is explicit, so it must not silently fall behind the tree.

    ``source`` cannot just be ``("odoo",)``: that matches ``odoo.addons`` too,
    and ``check()``'s own-subtree rule would then exempt every import. Naming the
    packages instead means a *new* top-level core package would escape the
    contract unnoticed -- unless something asserts the list is complete.
    """
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
    """The same completeness rule, for the top-level *modules*.

    ``test_core_source_covers_every_core_package`` filters ``p.is_dir()``, so it
    only ever asserted the packages were complete. The six top-level modules --
    ``init.py`` (the bootstrap), ``logutils.py`` (imported by Layer 1),
    ``exceptions.py``, ``release.py``, ``_testing_bootstrap.py``, ``__main__.py``
    -- were therefore in no contract, and because ``iter_source_files`` derives
    its roots from ``source``, **zero** of them were read: any of them could
    import an addon and the gate would stay green forever.

    A directory-only completeness test is the same shape of hole as a
    directory-only scan; both are fixed here.
    """
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


def test_top_level_core_modules_are_actually_scanned():
    """Coverage in ``source`` is worthless if the walk still skips the file.

    ``iter_source_files`` maps a dotted source to a directory and falls back to
    ``root.with_suffix('.py')`` for module-shaped roots -- so naming them is
    enough, but only this assertion proves the walk reaches them.
    """
    scanned = {p.name for p in lc.iter_source_files() if p.parent == lc.ROOT / "odoo"}
    for name in ("init.py", "logutils.py", "exceptions.py", "release.py"):
        assert name in scanned, f"odoo/{name} is still not scanned by layer_check"


#: Top-level ``odoo/orm/*.py`` deliberately outside every *layering* contract.
#: ``model_test_env`` is the DB-free test harness and constructs
#: ``Environment``/``Transaction``/``Registry`` by design; ``__init__`` is the
#: package's own re-export surface. Everything else must be placed in a layer.
_ORM_MODULES_EXEMPT_FROM_LAYERING = frozenset({"model_test_env", "__init__"})


def test_every_top_level_orm_module_sits_in_a_layering_contract():
    """``core-does-not-depend-on-addons`` is not a layering contract.

    Four of the eleven top-level ``odoo/orm/*.py`` -- ``helpers``,
    ``registration``, ``model_test_env``, ``__init__``, together 1296 of 1987
    lines (~65%) -- were in no layering contract at all. They *looked* governed,
    because that addon contract names ``odoo.orm`` and so matches them, but it
    only forbids ``odoo.addons`` and constrains no layer.

    ``helpers.py`` is why this matters: 11 Layer-2 mixins import it, so whatever
    it imports becomes reachable from Layer 2 without Layer 2 importing it --
    the same conduit shape that `tools-does-not-reach-the-orm-runtime` closes
    one level up. Asserting "some contract matches" would have passed while the
    hole was open, so this asserts a *layering* contract matches.
    """
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
    """A facade must not launder a private ORM symbol to addon code.

    ``facade-boundary`` forbids addons importing ``odoo.orm.*``, and it is a
    name-prefix rule -- so re-exporting a private ORM symbol from a facade that
    is *not* under ``odoo.orm`` hands addons the same internal past the gate.
    Verified with the checker's own matcher:
    ``_matches("odoo.orm.runtime.registry._CACHES_BY_KEY", forbidden)`` is True
    while ``_matches("odoo.modules.registry._CACHES_BY_KEY", forbidden)`` is
    False -- same symbol, one path banned, the other allowed. Two production
    addons (``ir_autovacuum``, ``ir_qweb``) were using the allowed one.

    Those two constants are now public (``CACHES_BY_KEY`` / ``REGISTRY_CACHES``)
    because addons genuinely need them: the honest fix for "an addon depends on
    this" is stable API, not a private name with a side door. This keeps the
    door shut generally, rather than pinning the two names that went through it.
    """
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
    """A stale exemption would silently un-cover a package that got renamed."""
    pkg_root = lc.ROOT / "odoo"
    for name in lc.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT:
        assert (pkg_root / name / "__init__.py").exists(), (
            f"{name} is exempted but is not a core package"
        )


def test_the_cron_exception_is_pinned_not_silent():
    """The deliberate service -> ir_cron/ir_job dependency stays visible."""
    pinned = {k.imports for k in lc.KNOWN_VIOLATIONS}
    assert "odoo.addons.base.models.ir_cron" in pinned
    assert "odoo.addons.base.models.ir_job" in pinned
    for k in lc.KNOWN_VIOLATIONS:
        assert len(k.reason) > 80, f"{k.imports} pinned without a real rationale"


def test_facade_boundary_scans_the_addon_tree():
    # iter_source_files derives its roots from contract sources; the contract is
    # worthless if the addon tree is never walked (the bug ADR-0008 fixes).
    assert any("addons" in p.parts for p in lc.iter_source_files())


# --- dynamic imports with a string-literal target are checked like static ones ---


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
    # A variable target can't be resolved statically — must not be invented.
    targets = _collect(
        "import importlib\nname = 'odoo.orm.runtime'\nm = importlib.import_module(name)\n",
        module="odoo.orm.fields.base",
    )
    assert "odoo.orm.runtime" not in targets


def test_dynamic_import_under_type_checking_is_skipped():
    # Consistent with static imports: TYPE_CHECKING bodies never execute.
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import importlib\n"
        "    importlib.import_module('odoo.orm.runtime')\n"
    )
    assert "odoo.orm.runtime" not in _collect(src, module="odoo.orm.fields.base")


# --- prefix matching honours dotted boundaries ---


def test_matches_prefix_on_dot_boundary():
    assert lc._matches("odoo.orm.models.base", ("odoo.orm.models",))
    assert lc._matches("odoo.orm.models", ("odoo.orm.models",))
    # must not match a sibling that merely shares a string prefix
    assert not lc._matches("odoo.orm.modelsx", ("odoo.orm.models",))


# --- test-file detection (tests may cross any boundary) ---


def test_is_test_file():
    assert lc._is_test_file(Path("odoo/orm/components/tests/test_core.py"))
    assert lc._is_test_file(Path("pkg/conftest.py"))
    assert not lc._is_test_file(Path("odoo/orm/fields/base.py"))


# --- the scan counts what it scanned, once ---


def test_the_walk_visits_every_file_exactly_once():
    """Overlapping ``source`` prefixes used to be walked once per covering root.

    ``core-does-not-depend-on-addons`` names ``odoo.orm`` and
    ``orm-layer1-below-models-and-runtime`` names ``odoo.orm.fields``; each root
    was rglob'd independently, so 91 files were scanned twice and every
    violation in them was reported twice.
    """
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
    # ``odoo/http/openapi`` resolves to ``openapi.py``, which ``odoo/http``'s
    # rglob already returns.
    root = lc.ROOT
    collapsed = lc._collapse_nested(
        [root / "odoo" / "http", root / "odoo" / "http" / "openapi"]
    )
    assert collapsed == [root / "odoo" / "http"]


def test_one_import_statement_is_one_violation():
    """``visit_ImportFrom`` emits ``<base>`` and ``<base>.<name>`` on purpose.

    When the base alone already breaks the contract, both records describe the
    same statement: the four pinned cron/job imports rendered as "8 known
    exception(s)", each source line printed twice.
    """
    source = "from odoo.addons.base.models import ir_cron\n"
    violations = _violations_for("odoo.service.probe", source)
    assert len(violations) == 1, [v.imports for v in violations]


def test_the_submodule_record_is_kept_when_it_is_the_one_that_violates():
    """The case the double-emit exists for, which the dedupe must not eat.

    ``orm-layer1-below-models-and-runtime`` forbids ``odoo.models`` but not
    ``odoo``, so only the synthesized ``<base>.<name>`` carries the violation.
    """
    violations = _violations_for("odoo.orm.fields.probe", "from odoo import models\n")
    assert [v.imports for v in violations] == ["odoo.models"]


def test_two_distinct_forbidden_names_on_one_line_are_two_violations():
    # Deduping by line number alone would have collapsed these.
    violations = _violations_for(
        "odoo.orm.fields.probe", "from odoo.orm import models, runtime\n"
    )
    assert sorted(v.imports for v in violations) == [
        "odoo.orm.models",
        "odoo.orm.runtime",
    ]


# --- regression guard: the real framework core stays clean ---


def test_framework_core_has_no_new_violations():
    new, _known = lc.check()
    assert new == [], "new layering violations:\n" + "\n".join(
        f"  {v.path}:{v.lineno}  {v.module} -> {v.imports}  [{v.contract}]" for v in new
    )


def test_core_has_no_tolerated_exceptions():
    """The eight original contracts stay clean at zero — that paydown holds.

    ``core-does-not-depend-on-addons`` (added 2026-08) is the one contract with
    pinned entries, and they are *intentional* rather than debt: the cron/job
    runner threads call ``IrCron._process_jobs`` before a registry exists, so
    there is no env to route through. They are pinned rather than allow-listed
    so they stay scoped to ``odoo.service`` and stay visible in every report.
    """
    unexpected = [
        k
        for k in lc.KNOWN_VIOLATIONS
        if not k.imports.startswith("odoo.addons.base.models.ir_")
    ]
    assert unexpected == [], (
        f"a contract other than core-does-not-depend-on-addons acquired a "
        f"tolerated exception: {unexpected}"
    )


#: The eight boundaries that shipped with ADR-0005, named rather than derived
#: as "everything except the addon contract". That subtraction stopped
#: identifying them once later contracts landed
#: (``db-resilience-below-connectivity`` / ``http-features-below-serving``,
#: 2026-08), and a bare count would also accept a substitution — one original
#: dropped, one new added — while still reading as 8.
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
    """No pinned entry may attach to any of the pre-existing contracts."""
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


# --- the intra-package tier contracts (db/, http/) ---------------------------
#
# Both packages are flat, so these contracts enumerate module paths rather than
# a package prefix. That makes them the two contracts most likely to rot by
# omission: a NEW module added to either package joins no tier and is silently
# unenforced. `test_every_db_and_http_module_is_in_a_tier` below is the guard.


def test_db_resilience_importing_connectivity_is_a_violation():
    assert _violates("odoo.db.breaker", "from .pool import ConnectionPool\n")
    assert _violates("odoo.db.metrics", "from odoo.db.cursor import Cursor\n")


def test_db_connectivity_importing_resilience_is_clean():
    """The sanctioned direction: pool -> budget/leaks/reaper/stats."""
    assert not _violates("odoo.db.pool", "from .budget import ConnectionBudget\n")
    assert not _violates("odoo.db.cursor", "from .metrics import CursorMetrics\n")


def test_db_foundation_is_importable_from_both_tiers():
    """`metrics -> errors` was the lone back-edge; foundation makes it legal."""
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
    """`_protocols.py` really does this, and it must stay legal."""
    src = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .session import Session\n"
    assert not _violates("odoo.http._protocols", src)


def test_every_db_and_http_module_is_in_a_tier():
    """A new flat-package module must be assigned a tier, not silently skipped.

    These two contracts enumerate modules, so an unlisted module is enforced by
    nothing while the gate still reports the package clean — the exact failure
    mode `subsystem_map_check.py` exists to prevent for the *map*, reproduced
    here for the *contracts*.
    """
    # ``lc.ROOT``, not a counted depth: the module under test already resolved
    # the checkout by marker, and a second, differently-derived answer here is
    # how the two drift apart.
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
            tiered |= {"errors", "dsn", "utils"}  # the [foundation] tier
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


# --- odoo/tests/ is the shipped test FRAMEWORK, not tests ---------------------
#
# The exemption of ``odoo.tests`` from ``core-does-not-depend-on-addons`` is
# meant to be revocable: drop ``tests`` from
# ``CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT``, watch
# ``test_core_source_covers_every_core_package`` fail, add ``odoo.tests`` to the
# contract's ``source``. Before the ``_is_test_file`` fix, following that
# workflow correctly enforced NOTHING — the files were dropped one step earlier
# by a directory-name rule, so the contract reported green over 7,145 lines of
# shipped framework it had never read. These pin the fix.


def test_core_test_framework_modules_are_not_test_files():
    """``odoo/tests/common.py`` is framework source, not a test."""
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
    """The property that was silently false: revocation must have teeth.

    Simulates the documented workflow — add ``odoo.tests`` to the addon
    contract's ``source`` — and asserts the guarded ``odoo.addons.bus`` reaches
    in ``tests/common.py`` and ``tests/http.py`` are then found. With the old
    directory-name rule this returned zero, i.e. a false green.
    """
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
    """It stays a deliberate, single-mechanism decision."""
    assert frozenset({"tests"}) == lc.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT
    core = next(c for c in lc.CONTRACTS if c.name == "core-does-not-depend-on-addons")
    assert "odoo.tests" not in core.source, (
        "odoo.tests is exempt via CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT; "
        "listing it in source too would make the exemption ambiguous"
    )
