import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_name_ownership as gate


def _module(root: Path, name: str, body: str, *, where: str = "models") -> Path:
    module = root / name
    (module / where).mkdir(parents=True, exist_ok=True)
    (module / "__manifest__.py").write_text(
        '{"name": "%s", "depends": ["base"]}\n' % name, encoding="utf-8"
    )
    source = module / where / "m.py"
    source.write_text("from odoo import models\n\n\n" + body, encoding="utf-8")
    return source


DECLARES = """class A(models.Model):
    _name = "some.model"
    _description = "A"
"""

EXTENDS = """class B(models.Model):
    _inherit = "some.model"
"""

DECLARES_WITH_MIXINS = """class C(models.Model):
    _name = "some.model"
    _inherit = ["mail.thread", "mixin.tag"]
    _description = "C"
"""

EXTENDS_LISTING_ITSELF = """class D(models.Model):
    _name = "some.model"
    _inherit = ["some.model", "mail.thread"]
"""


def test_two_modules_declaring_one_name_are_contested(tmp_path):
    _module(tmp_path, "alpha", DECLARES)
    _module(tmp_path, "beta", DECLARES)

    contested = gate.measure([tmp_path])

    assert [model for model, _ in contested] == ["some.model"]
    assert sorted(d.module for _, decls in contested for d in decls) == [
        "alpha",
        "beta",
    ]


def test_a_module_extending_another_module_is_not_contested(tmp_path):
    _module(tmp_path, "alpha", DECLARES)
    _module(tmp_path, "beta", EXTENDS)

    assert gate.measure([tmp_path]) == []


def test_declaring_a_name_beside_mixins_still_owns_the_name(tmp_path):
    """The bug this gate was written twice to get right.

    `res.partner` declares `_name` and lists seven mixins in `_inherit`, and it
    is still the one module that owns that name. A predicate that merely asks
    whether `_inherit` is present excuses every model worth protecting, so the
    gate mirrors `registration.py` instead: an extension is a class whose
    `_name` appears among its own `_inherit` entries.
    """
    _module(tmp_path, "alpha", DECLARES)
    _module(tmp_path, "beta", DECLARES_WITH_MIXINS)

    assert [model for model, _ in gate.measure([tmp_path])] == ["some.model"]


def test_naming_itself_in_inherit_is_an_extension(tmp_path):
    _module(tmp_path, "alpha", DECLARES)
    _module(tmp_path, "beta", EXTENDS_LISTING_ITSELF)

    assert gate.measure([tmp_path]) == []


def test_one_module_declaring_a_name_twice_is_not_contested(tmp_path):
    """Ownership is per module, not per class.

    A module may spell the same model in two files while porting one; that is
    its own business and the registry merges them under one owner.
    """
    module = _module(tmp_path, "alpha", DECLARES).parent
    (module / "second.py").write_text(
        "from odoo import models\n\n\n" + DECLARES, encoding="utf-8"
    )

    assert gate.measure([tmp_path]) == []


def test_test_scaffolding_is_not_a_declaration(tmp_path):
    _module(tmp_path, "alpha", DECLARES)
    _module(tmp_path, "beta", DECLARES, where="tests")

    assert gate.measure([tmp_path]) == []


def test_a_scan_that_reaches_no_module_refuses(tmp_path):
    (tmp_path / "empty").mkdir()

    with pytest.raises(RuntimeError, match="no model declarations"):
        gate.measure([tmp_path])


def test_the_workspace_is_clean():
    """The gate's own subject, at a hard zero with no baseline to absorb one."""
    assert gate.measure() == []
