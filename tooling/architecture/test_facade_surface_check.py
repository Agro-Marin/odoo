import ast
import textwrap

import pytest

from . import facade_surface_check as gate


def _surface(source):
    bound, declared = gate._bound_names(ast.parse(textwrap.dedent(source)))
    return bound, declared


class TestBoundNames:
    def test_a_re_export_is_part_of_the_surface(self):
        bound, _ = _surface("from odoo.libs.iteration import groupby, unique")
        assert {"groupby", "unique"} <= bound

    def test_an_aliased_re_export_binds_the_alias(self):
        bound, _ = _surface("from odoo.libs.x import a as b")
        assert "b" in bound and "a" not in bound

    def test_definitions_and_assignments_count(self):
        bound, _ = _surface(
            """
            X = 1
            Y: int = 2
            def f(): ...
            class C: ...
            """
        )
        assert {"X", "Y", "f", "C"} <= bound

    def test_names_bound_under_TYPE_CHECKING_count(self):
        bound, _ = _surface(
            """
            if typing.TYPE_CHECKING:
                from odoo.api import Environment
            """
        )
        assert "Environment" in bound

    def test_names_bound_in_an_import_fallback_count(self):
        bound, _ = _surface(
            """
            try:
                from cryptography.x509 import load_pem_x509_certificate
            except ImportError:
                load_pem_x509_certificate = None
            """
        )
        assert "load_pem_x509_certificate" in bound

    def test_dunder_all_is_read_separately_from_what_is_bound(self):
        bound, declared = _surface(
            """
            from odoo.libs.x import a, b
            __all__ = ["a"]
            """
        )
        assert {"a", "b"} <= bound
        assert declared == {"a"}

    def test_a_star_import_is_not_a_binding_we_can_resolve(self):
        bound, _ = _surface("from odoo.libs.web import *")
        assert bound == set()


class TestSubmoduleNames:
    def test_a_package_facade_exposes_its_submodules(self):
        names = gate._submodule_names("odoo.tools")
        assert {"date_utils", "safe_eval", "misc", "query"} <= names
        assert "pdf" in names, "a package submodule counts too"

    def test_a_plain_module_has_no_submodules(self):
        assert gate._submodule_names("odoo.tools.misc") == set()


class TestCheck:
    def test_the_repository_is_clean(self):
        report = gate.check()
        assert report.missing == (), "\n".join(
            f"{f.path}:{f.lineno} {f.facade} has no {f.name!r}" for f in report.missing
        )
        assert report.ok

    def test_an_empty_scan_refuses_rather_than_passing(self, tmp_path):
        (tmp_path / "empty").mkdir()
        report = gate.check((tmp_path / "empty",))
        assert not report.ok
        assert "scanned" in report.vacuous

    def test_undeclared_names_are_reported_and_do_not_fail(self):
        report = gate.check()
        assert report.undeclared, "misc alone forwards dozens beyond __all__"
        assert report.ok

    @pytest.mark.parametrize(
        ("facade", "name"),
        [
            ("odoo.tools.misc", "itemgetter"),
            ("odoo.tools", "zeep"),
            ("odoo.tools", "mimetypes"),
        ],
    )
    def test_the_real_breaks_are_detected(self, tmp_path, facade, name):
        addon = tmp_path / "addon"
        addon.mkdir()
        (addon / "models.py").write_text(f"from {facade} import {name}\n")
        for i in range(gate._MIN_SCANNED):
            (addon / f"pad_{i}.py").write_text("x = 1\n")
        report = gate.check((addon,))
        assert [f.name for f in report.missing] == [name]
        assert not report.ok
