"""Tests for the pure half of the model-type generator.

``generate_model_types.py`` is 440 lines and had no tests, while its sibling
``generate_service_types.py`` had ten. Everything below runs without an Odoo
registry: rendering a ``fields_get`` dict to TypeScript is a pure function of
that dict, and it is the half that decides whether ``record.data.partner_id``
resolves to ``Many2one<"res.partner">`` or silently to ``any``.

The emitted ``.d.ts`` feeds ``tooling/typecheck/scope_gate.py``. A wrong type
here does not fail loudly — it removes an error from a locked file, which under
the gate's ``exact`` mode reads as an improvement to commit.
"""

from types import SimpleNamespace

import generate_model_types as G
import pytest


class TestNameMapping:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("sale.order", "SaleOrder"),
            ("sale.order.line", "SaleOrderLine"),
            ("res.partner", "ResPartner"),
            ("ir.model", "IrModel"),
        ],
    )
    def test_interface_name_is_pascal_case(self, model, expected):
        assert G._interface_name(model) == expected

    def test_file_name_flattens_dots(self):
        assert G._file_name("sale.order.line") == "sale_order_line.d.ts"

    def test_two_models_can_collide_on_one_file_name(self):
        # `.` -> `_` is not injective. `generate` detects this and raises
        # rather than letting the second emission overwrite the first; this
        # test pins the collision itself so the detector keeps having a reason
        # to exist.
        assert G._file_name("res.partner.category") == G._file_name(
            "res.partner_category"
        )


class TestFieldTypes:
    @pytest.mark.parametrize(
        ("ttype", "expected"),
        [
            ("char", "string"),
            ("text", "string"),
            ("integer", "number"),
            ("monetary", "number"),
            ("boolean", "boolean"),
            ("date", "string"),
            ("datetime", "string"),
            ("binary", "string | false"),
            ("json", "unknown"),
        ],
    )
    def test_scalars(self, ttype, expected):
        assert G._render_field_type({"type": ttype}) == expected

    def test_unknown_type_degrades_to_unknown_not_any(self):
        # `unknown` forces a narrowing at the use site; `any` would silently
        # switch type checking off for every reader of the field.
        assert G._render_field_type({"type": "some_future_type"}) == "unknown"

    def test_many2one_carries_its_relation(self):
        assert (
            G._render_field_type({"type": "many2one", "relation": "res.partner"})
            == 'Many2one<"res.partner">'
        )

    def test_many2one_without_a_relation_stays_generic(self):
        assert G._render_field_type({"type": "many2one"}) == "Many2one<string>"

    @pytest.mark.parametrize(
        ("ttype", "brand"), [("one2many", "One2many"), ("many2many", "Many2many")]
    )
    def test_x2many_brands(self, ttype, brand):
        rendered = G._render_field_type({"type": ttype, "relation": "sale.order.line"})
        assert rendered == f'{brand}<"sale.order.line">'

    def test_selection_becomes_a_string_literal_union(self):
        field = {"type": "selection", "selection": [("draft", "D"), ("sale", "S")]}
        assert G._render_field_type(field) == '"draft" | "sale"'

    def test_empty_selection_falls_back_to_string(self):
        assert G._render_field_type({"type": "selection", "selection": []}) == "string"

    def test_a_huge_selection_falls_back_to_string(self):
        # Past the cap the union is noise in every tooltip and error message.
        field = {
            "type": "selection",
            "selection": [(f"k{i}", f"L{i}") for i in range(G._SELECTION_KEY_CAP + 1)],
        }
        assert G._render_field_type(field) == "string"

    def test_a_selection_at_the_cap_is_still_a_union(self):
        field = {
            "type": "selection",
            "selection": [(f"k{i}", f"L{i}") for i in range(G._SELECTION_KEY_CAP)],
        }
        assert G._render_field_type(field).startswith('"k0" |')


class TestOptionality:
    def test_required_without_a_default_is_required(self):
        assert G._is_required({"type": "char", "required": True}) is True

    def test_required_with_a_default_is_optional(self):
        # Auto-filled on create, so client code never observes it unset.
        assert (
            G._is_required({"type": "char", "required": True, "default": "x"}) is False
        )

    def test_plain_field_is_optional(self):
        assert G._is_required({"type": "char"}) is False


class TestBrandImports:
    def test_only_the_brands_actually_used_are_imported(self):
        fields = {
            "name": {"type": "char"},
            "partner_id": {"type": "many2one", "relation": "res.partner"},
        }
        assert G._scan_used_brands(fields) == {"Many2one"}

    def test_a_scalar_only_model_imports_nothing(self):
        assert G._scan_used_brands({"name": {"type": "char"}}) == set()
        assert G._emit_imports(set()) == ""


class TestRendering:
    FIELDS = {
        "name": {"type": "char", "required": True},
        "state": {"type": "selection", "selection": [("draft", "D"), ("sale", "S")]},
        "partner_id": {"type": "many2one", "relation": "res.partner"},
        "x_custom": {"type": "char"},
    }

    def _render(self):
        return G._model_to_dts("sale.order", self.FIELDS, "sale")

    def test_declares_the_interface_and_registers_the_model(self):
        out = self._render()
        assert "interface SaleOrder {" in out
        assert '"sale.order": SaleOrder;' in out

    def test_custom_x_fields_are_never_emitted(self):
        # They are per-deployment; emitting them would couple the type repo to
        # one database.
        assert "x_custom" not in self._render()

    def test_required_and_optional_markers(self):
        out = self._render()
        assert "        name: string;" in out
        assert "        partner_id?: " in out

    def test_output_is_marked_generated_with_its_regen_command(self):
        out = self._render()
        assert "GENERATED — do not edit." in out
        assert "--modules=sale" in out

    def test_rendering_is_deterministic(self):
        # `--check` compares committed bytes against a fresh render, so any
        # ordering instability would report permanent, unfixable drift.
        assert self._render() == self._render()

    def test_fields_are_emitted_in_sorted_order(self):
        out = self._render()
        assert out.index("name") < out.index("partner_id") < out.index("state")


class _FakeRec:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __bool__(self):
        return True


class _FakeModel:
    _original_module = "base"
    _abstract = False

    def fields_get(self):
        return {"name": {"type": "char"}}


class _FakeEnv:
    """Enough of an Environment to drive `generate()` without a database."""

    def __init__(self, models=("res.partner",), installed=("base",)):
        self.registry = list(models)
        self._installed = installed

    def __getitem__(self, key):
        if key == "ir.model":
            return SimpleNamespace(
                search=lambda *a, **kw: _FakeRec(transient=False, modules="base")
            )
        if key == "ir.module.module":
            return SimpleNamespace(
                search=lambda *a, **kw: [
                    SimpleNamespace(name=n) for n in self._installed
                ]
            )
        return _FakeModel()


class TestCheckDetectsOrphans:
    """A DELETED model leaves its .d.ts behind, and registry->disk cannot see it.

    The orphan keeps declaring an `interface` and a `Models` entry for a model
    the server no longer has, while `--check` reports "up to date". Every
    sibling gate detects its own version of this — scope_gate's `stale`,
    py_cycle_check's `stale_pins`, package_index_check's `phantom`.
    """

    def _seeded(self, tmp_path):
        G.generate(_FakeEnv(), models=["res.partner"], output_dir=tmp_path, quiet=True)
        return tmp_path

    def test_a_freshly_generated_tree_is_clean(self, tmp_path):
        out = self._seeded(tmp_path)
        assert (
            G.generate(
                _FakeEnv(),
                models=["res.partner"],
                output_dir=out,
                quiet=True,
                check=True,
            )
            == {}
        )

    def test_an_orphan_is_reported(self, tmp_path):
        out = self._seeded(tmp_path)
        orphan = out / "base" / "deleted_model.d.ts"
        orphan.write_text("// a model that no longer exists\n", encoding="utf-8")
        stale = G.generate(
            _FakeEnv(), models=["res.partner"], output_dir=out, quiet=True, check=True
        )
        assert list(stale.values()) == [orphan]
        assert next(iter(stale)).startswith("(orphan)")

    def test_an_untargeted_module_directory_is_not_reported(self, tmp_path):
        """With `--modules sale`, every other module's file is untouched, not
        orphaned — otherwise a scoped run would condemn the whole tree."""
        out = self._seeded(tmp_path)
        (out / "other").mkdir()
        (out / "other" / "x.d.ts").write_text("// another module\n", encoding="utf-8")
        stale = G.generate(
            _FakeEnv(), models=["res.partner"], output_dir=out, quiet=True, check=True
        )
        assert stale == {}

    def test_a_stale_body_is_still_reported(self, tmp_path):
        out = self._seeded(tmp_path)
        target = out / "base" / "res_partner.d.ts"
        target.write_text("// hand-edited\n", encoding="utf-8")
        stale = G.generate(
            _FakeEnv(), models=["res.partner"], output_dir=out, quiet=True, check=True
        )
        assert stale == {"res.partner": target}


class TestModuleSelectionIsValidated:
    def test_an_uninstalled_module_raises_instead_of_emitting_nothing(self, tmp_path):
        """`--modules sales` used to exit 0 having written nothing, which is
        indistinguishable from a module that declares no models."""
        with pytest.raises(ValueError, match="not installed"):
            G.generate(_FakeEnv(), modules=["sales"], output_dir=tmp_path, quiet=True)

    def test_an_installed_module_is_accepted(self, tmp_path):
        G.generate(_FakeEnv(), modules=["base"], output_dir=tmp_path, quiet=True)
        assert (tmp_path / "base" / "res_partner.d.ts").is_file()
