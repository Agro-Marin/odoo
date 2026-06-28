"""Tests for the architecture layering checker.

Stdlib + pytest only — no Odoo imports — so this runs in the same database-free
way as the checker itself. Run with:

    pytest tooling/architecture/test_layer_check.py
"""

import ast
from pathlib import Path

import layer_check as lc  # sys.path set by conftest.py

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
    targets = _collect(
        "from .. import models as _m\n", module="odoo.orm.fields.base"
    )
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


def test_facade_boundary_scans_the_addon_tree():
    # iter_source_files derives its roots from contract sources; the contract is
    # worthless if the addon tree is never walked (the bug ADR-0008 fixes).
    assert any("addons" in p.parts for p in lc.iter_source_files())


# --- dynamic imports with a string-literal target are checked like static ones ---


def test_importlib_import_module_literal_is_collected():
    targets = _collect(
        "import importlib\n"
        "m = importlib.import_module('odoo.orm.runtime')\n",
        module="odoo.orm.fields.base",
    )
    assert "odoo.orm.runtime" in targets


def test_dunder_import_literal_is_collected():
    targets = _collect("m = __import__('odoo.orm.models')\n", module="odoo.orm.fields.base")
    assert "odoo.orm.models" in targets


def test_bare_import_module_literal_is_collected():
    targets = _collect(
        "from importlib import import_module\n"
        "m = import_module('odoo.orm.runtime')\n",
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


# --- regression guard: the real framework core stays clean ---


def test_framework_core_has_no_new_violations():
    new, _known = lc.check()
    assert new == [], "new layering violations:\n" + "\n".join(
        f"  {v.path}:{v.lineno}  {v.module} -> {v.imports}  [{v.contract}]"
        for v in new
    )


def test_core_has_no_tolerated_exceptions():
    # The whole point of the paydown work: zero known exceptions remain.
    assert lc.KNOWN_VIOLATIONS == ()


def test_every_contract_has_a_source_and_rationale():
    for c in lc.CONTRACTS:
        assert c.source, f"{c.name} has no source"
        assert c.forbidden, f"{c.name} forbids nothing"
        assert c.rationale.strip(), f"{c.name} has no rationale"
